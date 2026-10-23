"""The legal notice every frontend shows. Edit it here and it changes everywhere."""

from __future__ import annotations

from pathlib import Path

from .paths import app_data_dir

LEGAL_TITLE = "Only download what you have permission to download"

LEGAL_NOTICE = (
    "Only download videos you own or have the owner's explicit permission to "
    "download (for example, content under a Creative Commons licence). Downloading "
    "other content may violate YouTube's Terms of Service and copyright law. "
    "You are responsible for how you use this tool."
)

LEGAL_SHORT = "Only download content you own or have permission to download."

# Once the user ticks the notice we remember it on disk, not in browser storage:
# the desktop app's server gets a new port every launch, which wipes localStorage.
_ACK_FILE = "legal-ack-v1"


def legal_acknowledged(data_dir: Path | None = None) -> bool:
    return ((data_dir or app_data_dir()) / _ACK_FILE).exists()


def acknowledge_legal(data_dir: Path | None = None) -> None:
    data_dir = data_dir or app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / _ACK_FILE).write_text("yes\n")
