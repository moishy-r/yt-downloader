"""Looking up what's behind a URL (one video or a playlist) without downloading."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qs, urlparse

import certifi
import yt_dlp

from .formats import JS_RUNTIMES

_YT_HOST = re.compile(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$", re.I)


class FetchError(Exception):
    """A user-facing problem with the URL or with looking it up."""


@dataclass
class Entry:
    index: int                 # position in the playlist (1-based); 1 for a single video
    title: str
    url: str
    id: str = ""
    duration: int | None = None   # seconds
    available: bool = True        # False for private/deleted playlist items

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FetchResult:
    title: str
    is_playlist: bool
    entries: list[Entry] = field(default_factory=list)
    # If the URL was a video inside a playlist (watch?v=X&list=Y), the playlist
    # index of that video, so frontends can preselect just it.
    focus_index: int | None = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "is_playlist": self.is_playlist,
            "focus_index": self.focus_index,
            "entries": [e.to_dict() for e in self.entries],
        }


def normalize_url(url: str) -> str:
    """Validate a YouTube URL, adding https:// if it was left off."""
    url = (url or "").strip()
    if not url:
        raise FetchError("Paste a YouTube link first.")
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "https://" + url
    host = urlparse(url).hostname or ""
    if not _YT_HOST.search(host):
        raise FetchError("That doesn't look like a YouTube link "
                         "(it should contain youtube.com or youtu.be).")
    return url


def _friendly_error(exc: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    msg = re.sub(r"^ERROR:\s*", "", msg)
    msg = re.sub(r"^\[[^\]]+\]\s*[\w-]+:\s*", "", msg)   # "[youtube] abc123: "
    low = msg.lower()
    if "private" in low:
        return "This video or playlist is private."
    if "unavailable" in low or "does not exist" in low:
        return "This video or playlist is unavailable (removed, private or region-blocked)."
    if "sign in" in low or ("age" in low and "confirm" in low):
        return "YouTube requires signing in to view this (often age-restricted content)."
    if "getaddrinfo" in low or "network" in low or "timed out" in low:
        return "Couldn't reach YouTube. Check your internet connection."
    return msg or "Couldn't read that link."


def fetch(url: str) -> FetchResult:
    """Look up a URL. Raises FetchError with a readable message on failure."""
    url = normalize_url(url)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ca_cert": certifi.where(),
        "js_runtimes": {k: dict(v) for k, v in JS_RUNTIMES.items()},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # yt-dlp raises DownloadError for almost everything
        raise FetchError(_friendly_error(e)) from None

    if not info:
        raise FetchError("Nothing found at that link.")

    if info.get("_type") != "playlist":
        return FetchResult(
            title=info.get("title") or "Video",
            is_playlist=False,
            entries=[Entry(
                index=1,
                title=info.get("title") or info.get("id") or "Video",
                url=info.get("webpage_url") or url,
                id=info.get("id") or "",
                duration=_int(info.get("duration")),
            )],
        )

    focus_id = (parse_qs(urlparse(url).query).get("v") or [None])[0]
    entries: list[Entry] = []
    focus_index = None
    for i, e in enumerate(info.get("entries") or [], 1):
        if not e:
            continue
        vid = e.get("id") or ""
        title = e.get("title") or vid or f"Video {i}"
        # Flat playlist entries for removed videos have titles like "[Private video]"
        available = not (title.startswith("[") and title.endswith("]")
                         and ("private" in title.lower() or "deleted" in title.lower()))
        entries.append(Entry(
            index=i,
            title=title,
            url=e.get("url") or e.get("webpage_url")
                or f"https://www.youtube.com/watch?v={vid}",
            id=vid,
            duration=_int(e.get("duration")),
            available=available,
        ))
        if focus_id and vid == focus_id:
            focus_index = i

    if not entries:
        raise FetchError("That playlist is empty (or all of its videos are private).")

    return FetchResult(
        title=info.get("title") or "Playlist",
        is_playlist=True,
        entries=entries,
        focus_index=focus_index,
    )


def _int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
