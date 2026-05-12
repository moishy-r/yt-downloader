"""
web/app.py
----------
Flask backend for the YT Downloader web frontend.
All download logic is imported from core/downloader.py.

Run locally:
    cd <repo root>
    pip install -r web/requirements.txt
    python web/app.py

Then open http://localhost:5000 in your browser.
"""

import os
import sys
import json
import uuid
import threading
import queue
import tempfile
import shutil
from pathlib import Path

from flask import (
    Flask, request, jsonify, Response,
    send_file, render_template, stream_with_context,
)

# -- Locate core/ from the repo root ------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.downloader import (
    fetch_entries, build_ydl_opts, make_outtmpl, format_eta,
    MP3_QUALITIES, MP4_QUALITIES,
)
import yt_dlp

app = Flask(__name__, template_folder="templates")

# -- In-memory job store -------------------------------------------------------
# Each download gets a UUID. Progress events are queued here and streamed to
# the browser via Server-Sent Events. Completed files sit in a temp dir until
# the browser downloads them, then are cleaned up.

_jobs: dict[str, dict] = {}   # job_id -> {queue, thread, out_dir, status}
_jobs_lock = threading.Lock()


# -- Routes --------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html",
                           mp3_qualities=MP3_QUALITIES,
                           mp4_qualities=MP4_QUALITIES)


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    """Fetch playlist/video metadata without downloading."""
    data = request.get_json(force=True)
    url  = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided."}), 400
    try:
        entries = fetch_entries(url)
        if not entries:
            return jsonify({"error": "No videos found at that URL."}), 404
        return jsonify({"entries": entries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download", methods=["POST"])
def api_download():
    """
    Start a download job. Returns a job_id immediately.
    The client then connects to /api/progress/<job_id> for SSE updates,
    and fetches /api/file/<job_id> when done.
    """
    data     = request.get_json(force=True)
    entries  = data.get("entries", [])
    fmt      = data.get("fmt", "mp3")
    quality  = data.get("quality", "320")

    if not entries:
        return jsonify({"error": "No entries provided."}), 400

    job_id  = str(uuid.uuid4())
    out_dir = tempfile.mkdtemp(prefix=f"ytdl_{job_id}_")
    q       = queue.Queue()

    with _jobs_lock:
        _jobs[job_id] = {
            "queue":   q,
            "out_dir": out_dir,
            "status":  "running",
            "files":   [],
        }

    t = threading.Thread(
        target=_download_worker,
        args=(job_id, entries, fmt, quality, out_dir, q),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    """
    Server-Sent Events stream for a job.
    Each event is a JSON object with a 'type' field:
        {type: "progress", video: int, total: int, pct: float, speed: str, eta: str}
        {type: "log",      message: str}
        {type: "done",     files: [{name, id}]}
        {type: "error",    message: str}
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return Response("data: {\"type\":\"error\",\"message\":\"Job not found\"}\n\n",
                        mimetype="text/event-stream", status=404)

    def generate():
        q = job["queue"]
        while True:
            try:
                msg = q.get(timeout=30)
            except queue.Empty:
                # Heartbeat to keep connection alive
                yield "data: {\"type\":\"ping\"}\n\n"
                continue

            yield f"data: {json.dumps(msg)}\n\n"

            if msg.get("type") in ("done", "error"):
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if proxied
        },
    )


@app.route("/api/file/<job_id>/<file_id>")
def api_file(job_id, file_id):
    """Serve a completed file for download, then clean it up."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready or job not found."}), 404

    # Find the file by its id (index in the files list)
    try:
        idx      = int(file_id)
        fileinfo = job["files"][idx]
    except (ValueError, IndexError):
        return jsonify({"error": "Invalid file id."}), 404

    path = fileinfo["path"]
    name = fileinfo["name"]

    if not os.path.exists(path):
        return jsonify({"error": "File not found on disk."}), 404

    return send_file(path, as_attachment=True, download_name=name)


@app.route("/api/cleanup/<job_id>", methods=["POST"])
def api_cleanup(job_id):
    """Remove the temp directory for a finished job."""
    with _jobs_lock:
        job = _jobs.pop(job_id, None)
    if job:
        shutil.rmtree(job["out_dir"], ignore_errors=True)
    return jsonify({"ok": True})


# -- Download worker -----------------------------------------------------------

def _download_worker(job_id, entries, fmt, quality, out_dir, q):
    total     = len(entries)
    is_single = total == 1
    files     = []

    try:
        for i, entry in enumerate(entries, 1):
            outtmpl = make_outtmpl(out_dir, entry, is_single)

            # We need to know the final filename after yt-dlp is done.
            # Capture it from the progress hook's 'finished' status.
            finished_files = []

            def make_hooks(idx=i, tot=total, ff=finished_files):
                def progress_hook(d):
                    if d["status"] == "downloading":
                        pct_s = d.get("_percent_str", "0").strip().replace("%", "")
                        try:    pct = float(pct_s)
                        except: pct = 0.0
                        q.put({
                            "type":  "progress",
                            "video": idx,
                            "total": tot,
                            "pct":   round(pct, 1),
                            "speed": d.get("_speed_str", "").strip(),
                            "eta":   format_eta(d),
                        })
                    elif d["status"] == "finished":
                        fname = d.get("filename", "")
                        if fname:
                            ff.append(fname)
                        q.put({
                            "type":    "log",
                            "message": f"Processing: {os.path.basename(fname)}",
                        })

                def log_hook(msg):
                    if msg and msg.strip() and not msg.startswith("[debug]"):
                        q.put({"type": "log", "message": msg.strip()})

                return progress_hook, log_hook

            ph, lh = make_hooks()
            opts   = build_ydl_opts(fmt, quality, outtmpl, ph, lh)

            q.put({
                "type":    "log",
                "message": f"[{i}/{total}] {entry['title']}",
            })

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([entry["url"]])

            # Find the final output file (after postprocessing, extension may differ)
            # Search out_dir for files modified in the last 60s that match the entry
            for f in finished_files:
                # The postprocessor may have changed the extension (e.g. .webm -> .mp3)
                base = os.path.splitext(f)[0]
                for ext in ([".mp3"] if fmt == "mp3" else [".mp4", ".mkv", ".webm"]):
                    candidate = base + ext
                    if os.path.exists(candidate):
                        files.append({
                            "path": candidate,
                            "name": os.path.basename(candidate),
                        })
                        break
                else:
                    # Fallback: just use whatever yt-dlp reported
                    if os.path.exists(f):
                        files.append({"path": f, "name": os.path.basename(f)})

        # If finished_files approach missed anything, scan out_dir as a safety net
        if not files:
            ext_filter = ".mp3" if fmt == "mp3" else (".mp4", ".mkv", ".webm")
            for fname in sorted(os.listdir(out_dir)):
                if fname.endswith(ext_filter):
                    files.append({
                        "path": os.path.join(out_dir, fname),
                        "name": fname,
                    })

        with _jobs_lock:
            _jobs[job_id]["files"]  = files
            _jobs[job_id]["status"] = "done"

        q.put({
            "type":  "done",
            "files": [{"name": f["name"], "id": i}
                      for i, f in enumerate(files)],
        })

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
        q.put({"type": "error", "message": str(e)})
        shutil.rmtree(out_dir, ignore_errors=True)


# -- Entry point ---------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("  YT Downloader - Web")
    print("  Running at http://localhost:5000")
    print("  Press Ctrl+C to stop.")
    print()
    app.run(debug=False, threaded=True, host="127.0.0.1", port=5000)
