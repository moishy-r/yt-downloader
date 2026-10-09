"""Output-folder handling: shorthands like $downloads, ~, env vars, relative paths."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


def _win_known_folder(folder_id: str) -> str:
    """Resolve a Windows known folder (handles OneDrive redirection). '' on failure."""
    try:
        import subprocess
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"[Environment]::GetFolderPath('{folder_id}')"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.stdout.strip()
    except Exception:
        return ""


@lru_cache(maxsize=1)
def shorthands() -> dict[str, str]:
    home = Path.home()
    folders = {
        "$desktop":   home / "Desktop",
        "$downloads": home / "Downloads",
        "$documents": home / "Documents",
        "$music":     home / "Music",
        "$videos":    home / ("Movies" if sys.platform == "darwin" else "Videos"),
        "$home":      home,
    }
    if sys.platform == "win32":
        for key, fid in (("$desktop", "Desktop"), ("$documents", "MyDocuments"),
                         ("$music", "MyMusic"), ("$videos", "MyVideos")):
            found = _win_known_folder(fid)
            if found:
                folders[key] = Path(found)
    return {k: str(v) for k, v in folders.items()}


def default_output_dir() -> str:
    return str(Path.home() / "Downloads" / "YT Downloads")


def resolve_path(raw: str) -> str:
    """Turn any user-supplied folder into an absolute path.

    Accepts shorthands ($downloads/Music), ~, $ENV / %ENV% variables,
    relative paths and either slash style. Empty input gives the default folder.
    """
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        return default_output_dir()
    low = raw.lower()
    for key, expansion in shorthands().items():
        if low == key or low.startswith(key + "/") or low.startswith(key + "\\"):
            raw = expansion + raw[len(key):]
            break
    raw = os.path.expanduser(os.path.expandvars(raw))
    return str(Path(raw).resolve())
