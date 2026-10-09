"""Terminal frontend. All download logic lives in ytdl.core.

    ytdl                       guided mode: asks for everything
    ytdl <url>                 asks only what you didn't pass as flags
    ytdl <url> -f mp4 -q 720p -s 1,3,5-8 -o '$downloads/Clips' -y
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
from pathlib import Path
import time

from ytdl import __version__
from ytdl.core import (
    DEFAULT_QUALITY, QUALITIES, DownloadJob, FetchError, LEGAL_NOTICE, LEGAL_SHORT,
    LEGAL_TITLE, SelectionError, check_ffmpeg, default_output_dir, fetch,
    format_duration, parse_selection, resolve_path, safe_folder_name, shorthands, validate,
)

# ── Terminal styling (disabled when output isn't a terminal) ───────────────
_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _TTY else text


def bold(t): return _c("1", t)
def dim(t): return _c("2", t)
def red(t): return _c("31", t)
def green(t): return _c("32", t)
def yellow(t): return _c("33", t)


def _width() -> int:
    return min(shutil.get_terminal_size((80, 24)).columns, 100)


def _wrap(text: str, indent: str = "  ") -> str:
    return textwrap.fill(text, _width() - 2, initial_indent=indent, subsequent_indent=indent)


def print_legal(short: bool = False):
    if short:
        print(yellow(f"⚠  {LEGAL_SHORT}"))
        return
    print(yellow(bold(f"⚠  {LEGAL_TITLE}")))
    print(yellow(_wrap(LEGAL_NOTICE, "   ")))
    print()


def _ask(prompt: str, default: str = "") -> str:
    hint = dim(f" [{default}]") if default else ""
    try:
        answer = input(f"{prompt}{hint}: ").strip()
    except EOFError:
        print()
        sys.exit(1)
    return answer or default


def _choose(title: str, options: list[tuple[str, str]], default: str) -> str:
    print(bold(title))
    default_n = "1"
    for n, (value, label) in enumerate(options, 1):
        print(f"   {n}) {label}")
        if value == default:
            default_n = str(n)
    while True:
        a = _ask("   Choose", default_n)
        if a.isdigit() and 1 <= int(a) <= len(options):
            print()
            return options[int(a) - 1][0]
        for value, _ in options:   # typing the value itself ("mp4", "720p") also works
            if a.lower() == value:
                print()
                return value
        print(red(f"   Enter a number from 1 to {len(options)}."))


# ── Steps ──────────────────────────────────────────────────────────────────
def step_url(url: str | None):
    while True:
        if not url:
            url = _ask(bold("YouTube link (video or playlist)"))
        print(dim("   Looking it up…"))
        try:
            result = fetch(url)
            print()
            return result
        except FetchError as e:
            print(red(f"   {e}"))
            if not sys.stdin.isatty():
                sys.exit(1)
            url = None


def show_entries(result):
    entries = result.entries
    print(bold(f"Playlist: {result.title}") + dim(f"  ({len(entries)} videos)"))
    w = len(str(entries[-1].index))
    for e in entries:
        dur = format_duration(e.duration)
        line = f"   {e.index:>{w}})  {e.title}"
        if dur:
            line += dim(f"  {dur}")
        if not e.available:
            line = dim(line + "  (unavailable)")
        print(line)
    print()


def step_select(result, selection: str | None, interactive: bool):
    entries = [e for e in result.entries if e.available] or result.entries
    if not result.is_playlist:
        print(bold("Video: ") + result.title + "\n")
        return result.entries

    show_entries(result)
    available = [e.index for e in entries]
    default = str(result.focus_index) if result.focus_index else "all"

    if selection is None and interactive:
        if result.focus_index:
            print(dim(f"   Your link points at video {result.focus_index} in this playlist."))
        print(dim('   Pick videos: "all", "1,3,5", "2-8", "1-3,7" or "-4" (all except 4)'))
        while True:
            try:
                chosen = parse_selection(_ask("   Videos to download", default), available)
                break
            except SelectionError as e:
                print(red(f"   {e}"))
    else:
        try:
            chosen = parse_selection(selection or default, available)
        except SelectionError as e:
            sys.exit(red(f"✘ {e}"))

    picked = [e for e in entries if e.index in chosen]
    print(green(f"   ✔ {len(picked)} of {len(result.entries)} selected") + "\n")
    return picked


# ── Download with a live progress line ─────────────────────────────────────
class ProgressPrinter:
    def __init__(self):
        self.line_open = False

    def _clear(self):
        if self.line_open:
            if _TTY:
                print("\r" + " " * (_width() - 1) + "\r", end="", flush=True)
            else:
                print()
            self.line_open = False

    def __call__(self, ev: dict):
        t = ev["type"]
        tag = dim(f"[{ev.get('item')}/{ev.get('total')}]") if "item" in ev else ""
        if t == "item_start":
            self._clear()
            print(f"{tag} {ev['title']}")
        elif t == "progress":
            if not _TTY:
                return
            bar_w = 24
            filled = int(ev["percent"] / 100 * bar_w)
            bar = red("█" * filled) + dim("░" * (bar_w - filled))
            extra = "  ".join(x for x in (ev["speed"], ev["eta"] and f"ETA {ev['eta']}") if x)
            print(f"\r      {bar} {ev['percent']:5.1f}%  {dim(extra)}   ", end="", flush=True)
            self.line_open = True
        elif t == "processing":
            self._clear()
            print(dim("      converting…"), end="", flush=True)
            self.line_open = True
        elif t == "item_done":
            self._clear()
            print(green("      ✔ saved"))
        elif t == "item_skipped":
            self._clear()
            print(dim("      ✔ already in folder, skipped"))
        elif t == "item_failed":
            self._clear()
            print(red(f"      ✘ {ev['error']}"))
        elif t == "log":
            self._clear()
            print(dim(f"      {ev['message']}"))


def run_download(entries, fmt, quality, out_dir, playlist_title=None) -> int:
    job = DownloadJob(entries, fmt, quality, out_dir, on_event=ProgressPrinter(),
                      playlist_title=playlist_title)
    out_dir = job.out_dir   # a playlist gets its own subfolder
    job.start()
    try:
        while job._thread.is_alive():
            job._thread.join(0.2)
    except KeyboardInterrupt:
        print(yellow("\n\nStopping… (cleaning up the partial file)"))
        job.cancel()
        job._thread.join()

    print()
    saved, failed = len(job.files), len(job.failed)
    if job.cancelled:
        print(yellow(f"Stopped. {saved} file(s) saved to {out_dir}"))
        return 130
    if failed:
        print(yellow(f"Done with problems: {saved} saved, {failed} failed."))
        for f in job.failed:
            print(red(f"   ✘ {f['index']}) {f['title']}: {f['error']}"))
    else:
        print(green(bold(f"✔ Done! {saved} file(s) saved.")))
    print(f"   Folder: {out_dir}")
    return 1 if failed and not saved else 0


# ── Entry point ────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    keys = "  ".join(shorthands())
    p = argparse.ArgumentParser(
        prog="ytdl",
        description="Download YouTube videos or playlists as MP3 or MP4.\n"
                    "Run with no arguments for a guided, step-by-step mode.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
examples:
  ytdl                                     guided mode
  ytdl "https://youtu.be/VIDEO"            asks only for format/quality/folder
  ytdl "PLAYLIST_URL" -f mp3 -y            whole playlist as 320k MP3, no questions
  ytdl "PLAYLIST_URL" -s 1,3,5-8 -f mp4 -q 720p
  ytdl "PLAYLIST_URL" --list               just print the playlist
  ytdl "URL" -o '$music/YouTube'           (single quotes so the shell leaves $ alone)

folder shorthands: {keys}

{LEGAL_SHORT}
""")
    p.add_argument("url", nargs="?", help="YouTube video or playlist link")
    p.add_argument("--url", dest="url_flag", help=argparse.SUPPRESS)
    p.add_argument("-f", "--format", "--fmt", dest="fmt", choices=list(QUALITIES),
                   help="mp3 (audio) or mp4 (video)")
    p.add_argument("-q", "--quality",
                   help="mp3: 320/192/128   mp4: best/1080p/720p/480p/360p")
    p.add_argument("-s", "--select", "--indices", dest="select",
                   help='playlist videos to get, e.g. "1,3,5-8" (default: all)')
    p.add_argument("-o", "--out", help=f"output folder (default: {default_output_dir()})")
    p.add_argument("-y", "--yes", action="store_true",
                   help="don't ask anything; use defaults for anything not given")
    p.add_argument("--list", action="store_true", help="only list the videos, don't download")
    p.add_argument("-V", "--version", action="version", version=f"ytdl {__version__}")
    return p


def main(argv: list[str] | None = None):
    args = build_parser().parse_args(argv)
    url = args.url or args.url_flag
    interactive = sys.stdin.isatty() and not args.yes

    if interactive:
        print()
        print(red("▶ ") + bold("YT Downloader") + dim(f"  v{__version__}"))
        print()
        print_legal()
    else:
        print_legal(short=True)

    if not url and not interactive:
        sys.exit(red("✘ No link given. Usage: ytdl <url> [options]   (ytdl -h for help)"))

    if not check_ffmpeg() and not args.list:
        print(yellow("⚠  ffmpeg was not found. MP3 conversion and HD video won't work.\n"
                     "   Install it: macOS `brew install ffmpeg`, Windows `winget install Gyan.FFmpeg`"))
        print()

    try:
        result = step_url(url)
        if args.list:
            show_entries(result) if result.is_playlist else print(result.title)
            return
        entries = step_select(result, args.select, interactive)

        fmt = args.fmt or (_choose("Format", [("mp3", "MP3  (audio only)"),
                                              ("mp4", "MP4  (video)")], "mp3")
                           if interactive else "mp3")
        quality = args.quality
        if quality is None and interactive:
            quality = _choose("Quality", QUALITIES[fmt], DEFAULT_QUALITY[fmt])
        try:
            fmt, quality = validate(fmt, quality)
        except ValueError as e:
            sys.exit(red(f"✘ {e}"))

        if args.out is not None:
            out_dir = resolve_path(args.out)
        elif interactive:
            print(bold("Save to"))
            print(dim("   Shorthands: " + "  ".join(shorthands())))
            if result.is_playlist and len(entries) > 1:
                print(dim("   (the playlist gets its own folder inside this one)"))
            out_dir = resolve_path(_ask("   Folder", default_output_dir()))
            print()
        else:
            out_dir = default_output_dir()

        label = dict(QUALITIES[fmt])[quality]
        print(bold("Ready: ") + f"{len(entries)} video(s) → {fmt.upper()} {label}")
        playlist_title = result.title if result.is_playlist else None
        if playlist_title and len(entries) > 1:
            out_dir_shown = str(Path(out_dir) / safe_folder_name(playlist_title))
        else:
            out_dir_shown = out_dir
        print(dim(f"       {out_dir_shown}"))
        if interactive and _ask("Start? (Y/n)", "y").lower() not in ("y", "yes"):
            print("Cancelled.")
            return
        print()
        sys.exit(run_download(entries, fmt, quality, out_dir, playlist_title))
    except KeyboardInterrupt:
        print("\nBye.")
        sys.exit(130)


if __name__ == "__main__":
    main()
