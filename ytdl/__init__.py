"""YT Downloader: download YouTube videos and playlists as MP3 or MP4.

Layout:
    ytdl/core/     all download logic (no UI code)
    ytdl/cli.py    terminal frontend
    ytdl/web/      local web server + the HTML UI
    ytdl/desktop.py  macOS/Windows app: the same HTML UI in a native window
"""

__version__ = "2.0.0"
APP_NAME = "YT Downloader"
