"""Formats, qualities and the yt-dlp options that produce them."""

from __future__ import annotations

from typing import Callable

import certifi

FORMATS = [
    ("mp3", "MP3 (audio only)"),
    ("mp4", "MP4 (video)"),
]

QUALITIES = {
    "mp3": [
        ("320", "320 kbps (best)"),
        ("192", "192 kbps"),
        ("128", "128 kbps (smallest)"),
    ],
    "mp4": [
        ("best",  "Best available"),
        ("1080p", "1080p"),
        ("720p",  "720p"),
        ("480p",  "480p"),
        ("360p",  "360p (smallest)"),
    ],
}

DEFAULT_QUALITY = {"mp3": "320", "mp4": "best"}

# YouTube needs a JavaScript runtime to unlock all formats. yt-dlp only tries
# deno by default; also accept node/bun if that's what the user has installed.
JS_RUNTIMES = {"deno": {}, "node": {}, "bun": {}}


def validate(fmt: str, quality: str | None) -> tuple[str, str]:
    """Normalise a (format, quality) pair, raising ValueError if it's not offered."""
    fmt = (fmt or "").lower().strip()
    if fmt not in QUALITIES:
        raise ValueError(f"Format must be one of: {', '.join(QUALITIES)}")
    quality = (quality or DEFAULT_QUALITY[fmt]).lower().strip()
    if quality.isdigit() and fmt == "mp4":
        quality += "p"
    if quality.endswith("k") and fmt == "mp3":
        quality = quality[:-1]
    valid = [q for q, _ in QUALITIES[fmt]]
    if quality not in valid:
        raise ValueError(f"Quality for {fmt.upper()} must be one of: {', '.join(valid)}")
    return fmt, quality


def _mp4_selector(quality: str) -> str:
    # Prefer H.264 + AAC so files play in QuickTime / Windows Media Player
    # without re-encoding, then fall back to anything at that height.
    h = "" if quality == "best" else f"[height<={quality[:-1]}]"
    return (
        f"bestvideo[vcodec^=avc1]{h}+bestaudio[acodec^=mp4a]"
        f"/bestvideo{h}+bestaudio"
        f"/best{h}/best"
    )


class _Logger:
    """Routes yt-dlp's own messages to a callback instead of stdout."""

    def __init__(self, log: Callable[[str], None]):
        self._log = log

    def debug(self, msg: str):
        pass  # yt-dlp is very chatty at debug level; our events cover progress

    info = debug

    def warning(self, msg: str):
        self._log(f"Warning: {msg}")

    def error(self, msg: str):
        pass  # errors are raised as exceptions and reported per video


def build_ydl_opts(fmt: str, quality: str, outtmpl: str,
                   progress_hook: Callable[[dict], None] | None = None,
                   postprocessor_hook: Callable[[dict], None] | None = None,
                   log: Callable[[str], None] | None = None) -> dict:
    """yt-dlp options for downloading ONE video in the given format/quality."""
    fmt, quality = validate(fmt, quality)
    opts: dict = {
        "outtmpl":            outtmpl,
        "noplaylist":         True,
        "quiet":              True,
        "no_warnings":        log is None,
        "noprogress":         True,
        "windowsfilenames":   True,   # safe filenames on every OS
        "overwrites":         False,
        "ca_cert":            certifi.where(),
        "js_runtimes":        {k: dict(v) for k, v in JS_RUNTIMES.items()},
        "progress_hooks":     [progress_hook] if progress_hook else [],
        "postprocessor_hooks": [postprocessor_hook] if postprocessor_hook else [],
        "logger":             _Logger(log or (lambda _m: None)),
    }

    if fmt == "mp3":
        opts.update({
            "format": "bestaudio/best",
            "writethumbnail": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": quality},
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg",
                 "when": "before_dl"},
                {"key": "EmbedThumbnail"},
            ],
        })
    else:
        opts.update({
            "format": _mp4_selector(quality),
            "merge_output_format": "mp4",
            "postprocessors": [
                {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ],
        })
    return opts
