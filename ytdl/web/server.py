"""Local web server: serves the HTML UI and a small JSON API over ytdl.core.

Used two ways:
    ytdl-web        → opens in your browser (http://127.0.0.1:8765)
    ytdl-app        → the same UI inside a native macOS/Windows window

Files are saved straight to a folder on this computer (it's a local server),
and the page also offers each finished file as a browser download.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory
from werkzeug.serving import make_server

from ytdl import APP_NAME, __version__
from ytdl.core import (
    DEFAULT_QUALITY, FORMATS, LEGAL_NOTICE, LEGAL_SHORT, LEGAL_TITLE, QUALITIES,
    DownloadJob, Entry, FetchError, check_ffmpeg, default_output_dir, fetch,
    normalize_url, resolve_path, validate,
)
from ytdl.core.system import PickerUnavailable, open_in_file_manager, pick_folder

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 8765   # not 5000: macOS AirPlay Receiver already uses that
MAX_JOBS_KEPT = 20


class JobRecord:
    """A running/finished DownloadJob plus its event history (for the SSE stream)."""

    def __init__(self, job: DownloadJob):
        self.id = uuid.uuid4().hex
        self.job = job
        self.events: list[dict] = []
        self.cond = threading.Condition()
        job.on_event = self._record

    def _record(self, event: dict):
        with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    def events_after(self, n: int, timeout: float) -> list[dict]:
        with self.cond:
            if len(self.events) <= n:
                self.cond.wait(timeout)
            return self.events[n:]


def create_app(mode: str = "web") -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MODE"] = mode
    jobs: dict[str, JobRecord] = {}
    jobs_lock = threading.Lock()

    # ── Local-only safety ────────────────────────────────────────────────────
    # The API can write files and open folders, so only accept requests that
    # really come from this machine's UI: reject foreign Host headers (DNS
    # rebinding) and cross-site requests (other websites poking localhost).
    @app.before_request
    def _guard():
        host = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
        allowed = app.config.get("ALLOWED_HOSTS") or {"127.0.0.1", "localhost", "::1"}
        if host not in allowed:
            abort(403)
        origin = request.headers.get("Origin")
        if origin and origin != "null" and origin.rstrip("/") != request.host_url.rstrip("/"):
            abort(403)
        if request.method == "POST" and not request.is_json:
            abort(415)

    def body() -> dict:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def get_job(job_id: str) -> JobRecord:
        with jobs_lock:
            rec = jobs.get(job_id)
        if not rec:
            abort(404)
        return rec

    # ── UI ───────────────────────────────────────────────────────────────────
    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC_DIR, name)

    # ── API ──────────────────────────────────────────────────────────────────
    @app.get("/api/config")
    def api_config():
        return jsonify({
            "app": APP_NAME,
            "version": __version__,
            "mode": app.config["MODE"],
            "formats": FORMATS,
            "qualities": QUALITIES,
            "default_quality": DEFAULT_QUALITY,
            "default_out_dir": default_output_dir(),
            "ffmpeg": check_ffmpeg(),
            "legal": {"title": LEGAL_TITLE, "text": LEGAL_NOTICE, "short": LEGAL_SHORT},
        })

    @app.post("/api/fetch")
    def api_fetch():
        try:
            return jsonify(fetch(body().get("url", "")).to_dict())
        except FetchError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/jobs")
    def api_start():
        data = body()
        try:
            fmt, quality = validate(data.get("fmt", "mp3"), data.get("quality"))
            entries = [
                Entry(index=int(e["index"]), title=str(e.get("title") or "Video"),
                      url=normalize_url(e["url"]))
                for e in data.get("entries") or []
            ]
        except (ValueError, KeyError, TypeError, FetchError) as e:
            return jsonify({"error": f"Bad request: {e}"}), 400
        if not entries:
            return jsonify({"error": "Select at least one video."}), 400

        out_dir = resolve_path(data.get("out_dir") or "")
        try:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return jsonify({"error": f"Can't use that folder: {e.strerror or e}"}), 400

        playlist_title = (str(data.get("playlist_title") or "Playlist")
                          if data.get("is_playlist") else None)
        rec = JobRecord(DownloadJob(entries, fmt, quality, out_dir,
                                    playlist_title=playlist_title))
        with jobs_lock:
            jobs[rec.id] = rec
            for old in [k for k, r in jobs.items() if r.job.done][:-MAX_JOBS_KEPT]:
                jobs.pop(old, None)
        rec.job.start()
        return jsonify({"job_id": rec.id, "out_dir": rec.job.out_dir})

    @app.post("/api/pick-folder")
    def api_pick_folder():
        # The server runs on the user's own computer, so it can show the native picker.
        try:
            path = pick_folder(str(body().get("start") or ""))
        except PickerUnavailable as e:
            return jsonify({"error": f"Couldn't open a folder picker: {e}"}), 501
        return jsonify({"path": path})

    @app.get("/api/jobs/<job_id>/events")
    def api_events(job_id):
        rec = get_job(job_id)
        # EventSource sends Last-Event-ID when it reconnects, so nothing is replayed twice
        start = (request.headers.get("Last-Event-ID", type=int)
                 or request.args.get("after", 0, type=int))

        def stream():
            n = start
            while True:
                new = rec.events_after(n, timeout=15)
                if not new:
                    yield ": keep-alive\n\n"
                    continue
                for ev in new:
                    n += 1
                    yield f"id: {n}\ndata: {json.dumps(ev)}\n\n"
                    if ev["type"] == "finished":
                        return

        return Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/jobs/<job_id>/cancel")
    def api_cancel(job_id):
        get_job(job_id).job.cancel()
        return jsonify({"ok": True})

    @app.get("/api/jobs/<job_id>/files/<int:n>")
    def api_file(job_id, n):
        rec = get_job(job_id)
        if n < 0 or n >= len(rec.job.files) or not os.path.exists(rec.job.files[n]):
            abort(404)
        path = rec.job.files[n]
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))

    @app.post("/api/jobs/<job_id>/open-folder")
    def api_open_folder(job_id):
        open_in_file_manager(get_job(job_id).job.out_dir)
        return jsonify({"ok": True})

    return app


# ── `ytdl-web` entry point ───────────────────────────────────────────────────
def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="ytdl-web",
                                description="Run YT Downloader in your browser (local only).")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = p.parse_args(argv)

    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  {APP_NAME} (web) v{__version__}")
    print(f"  Open {url} in your browser.  Press Ctrl+C to stop.")
    print(f"  ⚠  {LEGAL_SHORT}\n")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # no per-request log spam
    try:
        make_server("127.0.0.1", args.port, create_app("web"), threaded=True).serve_forever()
    except OSError as e:
        sys.exit(f"  ✘ Couldn't start on port {args.port} ({e.strerror}). "
                 f"Try another: ytdl-web --port 8800")
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
