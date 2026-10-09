"""Native OS helpers: the system folder picker and "show in Finder/Explorer".

The web server runs on the user's own computer, so it can show the same native
folder picker the desktop app uses, even though the UI is in a browser.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class PickerUnavailable(Exception):
    """No native folder picker could be shown on this system."""


def open_in_file_manager(path: str):
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a local folder we created
    else:
        subprocess.Popen(["xdg-open", path])


def pick_folder(start: str = "", title: str = "Choose where to save downloads") -> str | None:
    """Show the system's folder picker. Returns the chosen folder, or None if
    the user cancelled. Raises PickerUnavailable if there's no picker to show."""
    start = start if start and Path(start).is_dir() else str(Path.home())
    if sys.platform == "darwin":
        return _pick_mac(start, title)
    if sys.platform == "win32":
        return _pick_windows(start, title)
    return _pick_linux(start, title)


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _pick_mac(start: str, title: str) -> str | None:
    choose = (f"choose folder with prompt {_applescript_str(title)} "
              f"default location (POSIX file {_applescript_str(start)})")
    # Asking System Events to show the dialog brings it in front of the browser;
    # if that's blocked by privacy settings, fall back to a plain dialog.
    scripts = [
        f'tell application "System Events"\nactivate\nset f to {choose}\nend tell\nPOSIX path of f',
        f"POSIX path of ({choose})",
    ]
    error = ""
    for script in scripts:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip().rstrip("/") or None
        if "-128" in r.stderr:          # the user pressed Cancel
            return None
        error = r.stderr.strip()
    raise PickerUnavailable(error or "osascript failed")


def _pick_windows(start: str, title: str) -> str | None:
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$d.Description = '{title.replace(chr(39), chr(39) * 2)}';"
        "$d.UseDescriptionForTitle = $true;"
        f"$d.SelectedPath = '{start.replace(chr(39), chr(39) * 2)}';"
        "if ($d.ShowDialog($owner) -eq 'OK') { $d.SelectedPath }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-STA", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        raise PickerUnavailable(str(e)) from None
    if r.returncode != 0:
        raise PickerUnavailable(r.stderr.strip() or "PowerShell failed")
    return r.stdout.strip() or None


def _pick_linux(start: str, title: str) -> str | None:
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", f"--title={title}",
               f"--filename={start.rstrip('/')}/"]
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--getexistingdirectory", start, "--title", title]
    else:
        raise PickerUnavailable("Install zenity or kdialog to get a folder picker.")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None
