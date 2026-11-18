"""Start Menu shortcut so Box Agent shows up in Windows search."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

SHORTCUT_NAME = "Box Agent.lnk"
# Paths are passed through environment variables so no quoting can break the script.
_PS_SCRIPT = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:BA_LNK);"
    "$s.TargetPath = $env:BA_TARGET;"
    "$s.WorkingDirectory = $env:BA_DIR;"
    "$s.IconLocation = $env:BA_TARGET + ',0';"
    "$s.Description = 'Box Agent - AI that acts inside a box you draw';"
    "$s.Save()"
)


def start_menu_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def default_marker() -> Path:
    from .settings import default_path

    return default_path().parent / "shortcut-target.txt"


def ensure_shortcut(
    target: Path,
    lnk_dir: Path | None = None,
    marker: Path | None = None,
    run=subprocess.run,
) -> bool:
    """Create or refresh the Start Menu shortcut to `target`.

    Skips the work when the shortcut exists and already points at `target` (tracked in a
    marker file, since reading a .lnk back needs COM). Returns True if it was (re)written.
    """
    lnk_dir = lnk_dir or start_menu_dir()
    marker = marker or default_marker()
    lnk = lnk_dir / SHORTCUT_NAME
    if lnk.exists() and marker.exists() and marker.read_text(encoding="utf-8") == str(target):
        return False
    lnk_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "BA_LNK": str(lnk), "BA_TARGET": str(target), "BA_DIR": str(target.parent)}
    run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
        env=env,
        check=True,
        timeout=30,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(target), encoding="utf-8")
    return True
