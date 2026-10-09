"""macOS / Windows app: the web UI in a native window (no browser, no terminal).

The local server runs on a random free port, bound to 127.0.0.1 only, and the
window adds native extras the browser version can't have (a folder picker).
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from werkzeug.serving import make_server

from ytdl import APP_NAME
from ytdl.web.server import create_app


class NativeApi:
    """Methods the page can call as window.pywebview.api.<name>()."""

    def __init__(self):
        self.window = None

    def pick_folder(self, start: str = "") -> str | None:
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
        if kind is None:
            kind = webview.FOLDER_DIALOG
        start_dir = start if start and Path(start).is_dir() else str(Path.home())
        # pywebview's dialog is attached to the app window (nicer than a free-floating one)
        result = self.window.create_file_dialog(kind, directory=start_dir)
        return result[0] if result else None


def _storage_dir() -> str:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path.home() / "AppData" / "Local"
    else:
        base = Path.home() / ".local" / "share"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def self_test(report: str | None = None) -> int:
    """Check a built app works without opening a window (used by CI on the
    packaged .app/.exe): bundled ffmpeg, yt-dlp, UI files, server, GUI backend.
    Windowed builds have no console, so results can also go to a file."""
    import shutil
    import subprocess
    import traceback
    import urllib.request

    from ytdl.web.server import STATIC_DIR

    results: list[str] = []

    def check(name, fn):
        try:
            detail = fn()
            results.append(f"PASS {name}{': ' + str(detail) if detail else ''}")
        except Exception:
            results.append(f"FAIL {name}\n{traceback.format_exc()}")

    def tool(name):
        path = shutil.which(name)
        if not path:
            raise RuntimeError(f"{name} not found on PATH")
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle and not os.path.realpath(path).startswith(os.path.realpath(bundle)):
            raise RuntimeError(f"{name} is not the bundled copy: {path}")
        subprocess.run([path, "-version"], check=True, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return path

    def ui_files():
        missing = [f for f in ("index.html", "app.js", "app.css") if not (STATIC_DIR / f).exists()]
        if missing:
            raise RuntimeError(f"missing {missing} in {STATIC_DIR}")

    def server():
        srv = make_server("127.0.0.1", 0, create_app("desktop"), threaded=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_port}"
            page = urllib.request.urlopen(base + "/", timeout=10).read().decode()
            config = urllib.request.urlopen(base + "/api/config", timeout=10).read().decode()
            if "YT Downloader" not in page or '"ffmpeg":true' not in config.replace(" ", ""):
                raise RuntimeError(f"unexpected response: {config[:200]}")
        finally:
            srv.shutdown()

    def gui_backend():
        import importlib
        backend = {"darwin": "webview.platforms.cocoa",
                   "win32": "webview.platforms.winforms"}.get(sys.platform, "webview")
        importlib.import_module(backend)
        return backend

    def yt_dlp_ready():
        import yt_dlp
        import yt_dlp_ejs  # noqa: F401  (YouTube JS challenge solver scripts)
        return yt_dlp.version.__version__

    check("ffmpeg", lambda: tool("ffmpeg"))
    check("ffprobe", lambda: tool("ffprobe"))
    check("yt-dlp", yt_dlp_ready)
    check("UI files", ui_files)
    check("local server", server)
    check("GUI backend", gui_backend)

    ok = all(r.startswith("PASS") for r in results)
    text = "\n".join(results + [f"SELF-TEST {'PASSED' if ok else 'FAILED'}"])
    if report:
        Path(report).write_text(text + "\n", encoding="utf-8")
    try:
        print(text)
    except Exception:
        pass  # windowed builds may have no stdout
    return 0 if ok else 1


def main():
    if "--self-test" in sys.argv:
        i = sys.argv.index("--self-test")
        report = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        sys.exit(self_test(report))

    try:
        import webview
    except ImportError:
        sys.exit("The desktop app needs pywebview:  pip install pywebview\n"
                 "Or use the browser version instead:  ytdl-web")

    if sys.platform == "win32":
        try:   # crisp text on high-DPI screens
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    server = make_server("127.0.0.1", 0, create_app("desktop"), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"

    api = NativeApi()
    api.window = webview.create_window(
        APP_NAME, url, js_api=api,
        width=760, height=900, min_size=(520, 600),
        background_color="#111111", text_select=True,
    )
    try:
        webview.start(private_mode=False, storage_path=_storage_dir())
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
