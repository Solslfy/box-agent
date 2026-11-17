"""Self-update from GitHub Releases."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import httpx

from .version import __version__

log = logging.getLogger(__name__)

REPO = "Solslfy/box-agent"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ASSET_NAME = "BoxAgent.exe"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass
class Release:
    version: str
    exe_url: str
    page_url: str


def parse_version(tag: str) -> tuple[int, int, int]:
    m = _VERSION_RE.match(tag.strip())
    if not m:
        raise ValueError(f"Not a version: {tag!r}")
    return int(m[1]), int(m[2]), int(m[3])


def is_newer(remote: str, local: str) -> bool:
    try:
        return parse_version(remote) > parse_version(local)
    except ValueError:
        return False


def check_latest(local: str = __version__, http: httpx.Client | None = None) -> Release | None:
    """Return the latest release if it is newer than `local` and has our exe; else None."""
    try:
        http = http or httpx.Client(timeout=15, follow_redirects=True)
        r = http.get(RELEASES_URL, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
        tag = data.get("tag_name", "")
        if not is_newer(tag, local):
            return None
        for asset in data.get("assets") or []:
            url = asset.get("browser_download_url", "")
            if asset.get("name") == ASSET_NAME and url.startswith(DOWNLOAD_PREFIX):
                return Release(".".join(map(str, parse_version(tag))), url, data.get("html_url", ""))
        return None
    except Exception as e:  # never let update checks break the app
        log.warning("Update check failed: %s", e)
        return None


def download(url: str, dest: Path, http: httpx.Client | None = None) -> Path:
    if not url.startswith(DOWNLOAD_PREFIX):
        raise ValueError("Refusing to download from outside the project's GitHub releases")
    http = http or httpx.Client(timeout=120, follow_redirects=True)
    tmp = dest.with_suffix(".part")
    with http.stream("GET", url) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    os.replace(tmp, dest)
    return dest


def write_swap_script(pid: int, new_exe: Path, target_exe: Path, script_path: Path) -> Path:
    script = (
        "@echo off\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        f'move /Y "{new_exe}" "{target_exe}" >nul\r\n'
        f'start "" "{target_exe}"\r\n'
        'del "%~f0"\r\n'
    )
    script_path.write_text(script, encoding="utf-8")
    return script_path


def apply_update(release: Release) -> bool:
    """Start replacing the running exe. Returns True if the caller should quit now."""
    if not getattr(sys, "frozen", False):
        webbrowser.open(release.page_url)
        return False
    tmp = Path(tempfile.gettempdir())
    new_exe = download(release.exe_url, tmp / "BoxAgent-new.exe")
    script = write_swap_script(os.getpid(), new_exe, Path(sys.executable), tmp / "BoxAgent-update.cmd")
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
    return True
