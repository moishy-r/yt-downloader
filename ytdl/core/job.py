"""DownloadJob: downloads a list of entries and reports progress as events.

This is the single download loop every frontend uses. Frontends only decide how
to *show* the events:

    job = DownloadJob(entries, "mp3", "320", out_dir, on_event=print)
    job.run()            # blocking; or job.start() for a background thread
    job.cancel()         # from any thread; stops mid-video

Events are plain JSON-safe dicts with a "type":
    start        total, out_dir
    item_start   item, total, index, title
    progress     item, total, percent, overall, speed, eta
    processing   item, total, title           (ffmpeg converting/merging)
    item_done    item, total, title, file
    item_skipped item, total, title, file     (already in the folder)
    item_failed  item, total, title, error
    log          message
    finished     out_dir, files, failed, cancelled
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Callable

import yt_dlp
from yt_dlp.utils import DownloadCancelled

from .fetch import Entry, _friendly_error
from .formats import build_ydl_opts, validate

Event = dict
EventCallback = Callable[[Event], None]


def safe_folder_name(name: str | None) -> str:
    """A folder name that's valid on macOS, Windows and Linux."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "").strip().rstrip(". ")
    name = re.sub(r"\s+", " ", name)[:100].rstrip(". ")
    if name.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                      *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name or "Playlist"


def output_template(out_dir: str, entry: Entry, numbered: bool, width: int = 2) -> str:
    """Single videos are saved as "Title.ext"; playlist items keep their
    original playlist number ("03 - Title.ext") even when only some are chosen."""
    name = "%(title)s.%(ext)s"
    if numbered:
        name = f"{entry.index:0{width}d} - {name}"
    return os.path.join(out_dir, name)


def human_speed(bps: float | None) -> str:
    if not bps:
        return ""
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024 or unit == "GB/s":
            return f"{bps:.0f} {unit}" if unit == "B/s" else f"{bps:.1f} {unit}"
        bps /= 1024
    return ""


def human_eta(d: dict) -> str:
    eta = d.get("eta")
    if eta is None:
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done, speed = d.get("downloaded_bytes"), d.get("speed")
        if total and done and speed and done < total:
            eta = (total - done) / speed
    if eta is None or eta < 0:
        return ""
    m, s = divmod(int(eta), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class DownloadJob:
    def __init__(self, entries: list[Entry], fmt: str, quality: str, out_dir: str,
                 on_event: EventCallback | None = None, playlist_title: str | None = None):
        """`out_dir` is the folder the user chose. When several videos come from a
        playlist (`playlist_title` given), they go into a subfolder named after the
        playlist and keep their playlist numbers; a single video goes straight in."""
        self.fmt, self.quality = validate(fmt, quality)
        self.entries = list(entries)
        self.numbered = bool(playlist_title) and len(self.entries) > 1
        self.out_dir = (os.path.join(out_dir, safe_folder_name(playlist_title))
                        if self.numbered else out_dir)
        self.on_event = on_event or (lambda _e: None)
        self._width = max(2, len(str(max((e.index for e in self.entries), default=1))))
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self.files: list[str] = []
        self.failed: list[dict] = []
        self.done = False

    # ── control ────────────────────────────────────────────────────────────
    def start(self) -> threading.Thread:
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return self._thread

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ── main loop ──────────────────────────────────────────────────────────
    def run(self) -> dict:
        Path(self.out_dir).mkdir(parents=True, exist_ok=True)
        total = len(self.entries)
        self._emit("start", total=total, out_dir=self.out_dir)
        for item, entry in enumerate(self.entries, 1):
            if self.cancelled:
                break
            self._download_one(item, total, entry)
        result = self._emit("finished", out_dir=self.out_dir, files=list(self.files),
                            failed=list(self.failed), cancelled=self.cancelled)
        self.done = True
        return result

    def _emit(self, type_: str, **data) -> Event:
        event = {"type": type_, **data}
        try:
            self.on_event(event)
        except Exception:
            pass  # a broken UI callback must never kill the download
        return event

    def _download_one(self, item: int, total: int, entry: Entry):
        base = dict(item=item, total=total, title=entry.title)
        self._emit("item_start", index=entry.index, **base)

        state = {"phase": 0, "phases": 1, "file": None, "last": -1.0}
        seen: set[str] = set()   # temp files yt-dlp wrote, for cleanup on cancel

        def progress_hook(d: dict):
            if self.cancelled:
                raise DownloadCancelled()
            if d.get("status") != "downloading":
                return
            fname = d.get("filename")
            seen.update(p for p in (fname, d.get("tmpfilename")) if p)
            if state["file"] is not None and fname != state["file"]:
                state["phase"] = min(state["phase"] + 1, state["phases"] - 1)
            state["file"] = fname
            total_b = d.get("total_bytes") or d.get("total_bytes_estimate")
            frac = (d.get("downloaded_bytes") or 0) / total_b if total_b else 0.0
            pct = (state["phase"] + min(frac, 1.0)) / state["phases"] * 100
            # Throttle: only report visible changes
            if pct - state["last"] < 0.5 and pct < 100:
                return
            state["last"] = pct
            self._emit("progress", item=item, total=total,
                       percent=round(pct, 1),
                       overall=round(((item - 1) + pct / 100) / total * 100, 1),
                       speed=human_speed(d.get("speed")), eta=human_eta(d))

        announced = {"processing": False}

        def pp_hook(d: dict):
            if self.cancelled:
                raise DownloadCancelled()
            if d.get("status") == "started" and not announced["processing"]:
                announced["processing"] = True
                self._emit("processing", **base)

        # YouTube sometimes answers a download with 403 Forbidden; a fresh lookup
        # (new signed URLs) almost always fixes it, so retry once before giving up.
        for attempt in (1, 2):
            try:
                self._attempt(entry, base, progress_hook, pp_hook, state)
                return
            except DownloadCancelled:
                self._cleanup_partials(seen)
                return
            except Exception as e:
                error = _friendly_error(e)
                if attempt == 1 and "403" in error and not self.cancelled:
                    self._cleanup_partials(seen)
                    state.update(phase=0, file=None, last=-1.0)
                    self._emit("log", message="YouTube refused the download (403), retrying…")
                    continue
                self.failed.append({"index": entry.index, "title": entry.title, "error": error})
                self._emit("item_failed", error=error, **base)
                return

    def _attempt(self, entry: Entry, base: dict, progress_hook, pp_hook, state: dict):
        opts = build_ydl_opts(
            self.fmt, self.quality,
            output_template(self.out_dir, entry, self.numbered, self._width),
            progress_hook=progress_hook, postprocessor_hook=pp_hook,
            log=lambda m: self._emit("log", message=m),
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(entry.url, download=False)
            if self.cancelled:
                raise DownloadCancelled()
            state["phases"] = max(1, len(info.get("requested_formats") or [None]))
            path = self._final_path(ydl, info)
            if path and os.path.exists(path):
                self.files.append(path)
                self._emit("item_skipped", file=path, **base)
                return
            info = ydl.process_ie_result(info, download=True)
        path = self._final_path(ydl, info)
        if path:
            self.files.append(path)
        self._emit("item_done", file=path, **base)

    def _final_path(self, ydl, info: dict) -> str | None:
        downloads = info.get("requested_downloads") or []
        if downloads and downloads[-1].get("filepath"):
            return downloads[-1]["filepath"]
        # Not downloaded yet: predict the name the postprocessors will produce
        try:
            name = ydl.prepare_filename(info)
        except Exception:
            return None
        return os.path.splitext(name)[0] + "." + self.fmt

    @staticmethod
    def _cleanup_partials(paths: set[str]):
        """Remove the .part / per-stream files left behind by a cancelled video."""
        for p in paths:
            for candidate in (p, p + ".part", p + ".ytdl"):
                try:
                    os.remove(candidate)
                except OSError:
                    pass
