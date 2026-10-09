"""All download logic. Frontends import from here and contain no download code.

    from ytdl.core import fetch, DownloadJob, QUALITIES, resolve_path, LEGAL_NOTICE
"""

import os
import shutil
import sys

import certifi

# ── Environment fixes shared by every frontend ─────────────────────────────
# Use certifi's CA bundle (fixes "SSL: CERTIFICATE_VERIFY_FAILED" on macOS python.org builds)
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# In a PyInstaller build, ffmpeg/ffprobe/deno are bundled next to the app;
# put that folder first on PATH so yt-dlp finds them.
if getattr(sys, "frozen", False):
    _bundle = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    os.environ["PATH"] = _bundle + os.pathsep + os.environ.get("PATH", "")

# macOS apps launched from Finder get a minimal PATH; add Homebrew locations.
if sys.platform == "darwin":
    for _p in ("/opt/homebrew/bin", "/usr/local/bin"):
        if _p not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _p

from .fetch import Entry, FetchError, FetchResult, fetch, format_duration, normalize_url  # noqa: E402
from .formats import DEFAULT_QUALITY, FORMATS, QUALITIES, validate  # noqa: E402
from .job import DownloadJob, safe_folder_name  # noqa: E402
from .legal import LEGAL_NOTICE, LEGAL_SHORT, LEGAL_TITLE  # noqa: E402
from .paths import default_output_dir, resolve_path, shorthands  # noqa: E402
from .selection import SelectionError, parse_selection  # noqa: E402


def check_js_runtime() -> bool:
    """YouTube works best with a JS runtime (deno, node or bun) available."""
    return any(shutil.which(x) for x in ("deno", "node", "bun"))


def check_ffmpeg() -> bool:
    """ffmpeg is required for MP3 conversion and for merging MP4 video+audio."""
    return shutil.which("ffmpeg") is not None


__all__ = [
    "Entry", "FetchError", "FetchResult", "fetch", "format_duration", "normalize_url",
    "DEFAULT_QUALITY", "FORMATS", "QUALITIES", "validate", "DownloadJob", "safe_folder_name",
    "LEGAL_NOTICE", "LEGAL_SHORT", "LEGAL_TITLE",
    "default_output_dir", "resolve_path", "shorthands",
    "SelectionError", "parse_selection", "check_ffmpeg", "check_js_runtime",
]
