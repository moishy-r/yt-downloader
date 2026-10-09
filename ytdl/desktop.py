"""macOS / Windows app: the web UI in a native window (no browser, no terminal).

The local server runs on a random free port, bound to 127.0.0.1 only, and the
window adds native extras the browser version can't have (a folder picker).
"""

from __future__ import annotations

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


def main():
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
