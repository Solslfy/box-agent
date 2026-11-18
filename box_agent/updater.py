"""Self-update from GitHub Releases."""
from __future__ import annotations

import hashlib
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

from . import winpaths
from .version import __version__

log = logging.getLogger(__name__)

REPO = "Solslfy/box-agent"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ASSET_NAME = "BoxAgent.exe"
SHA_NAME = ASSET_NAME + ".sha256"
# Hosts a GitHub release download may legitimately redirect to.
ALLOWED_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA_RE = re.compile(r"^([0-9a-fA-F]{64})\b")


@dataclass
class Release:
    version: str
    exe_url: str
    page_url: str
    sha_url: str = ""


def parse_sha_file(text: str) -> str:
    m = _SHA_RE.match(text.strip())
    if not m:
        raise ValueError("Checksum file is not a SHA-256 hash")
    return m[1].lower()


def verify_sha256(path: Path, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == expected.lower()


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
        urls = {
            a.get("name"): a.get("browser_download_url", "")
            for a in data.get("assets") or []
            if str(a.get("browser_download_url", "")).startswith(DOWNLOAD_PREFIX)
        }
        if ASSET_NAME not in urls or SHA_NAME not in urls:
            return None
        version = ".".join(map(str, parse_version(tag)))
        page = f"https://github.com/{REPO}/releases/tag/v{version}"
        return Release(version, urls[ASSET_NAME], page, urls[SHA_NAME])
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
        hops = [resp.url for resp in r.history] + [r.url]
        if any(u.scheme != "https" or u.host not in ALLOWED_HOSTS for u in hops):
            raise ValueError(f"Download was redirected to an untrusted host: {r.url.host}")
        with open(tmp, "xb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    os.replace(tmp, dest)
    return dest


def write_swap_script(pids: list[int], new_exe: Path, target_exe: Path, script_path: Path) -> Path:
    """Wait for every pid (PyInstaller onefile = bootloader parent + child) to exit, then swap.

    The move is retried for ~30 s because the exe can stay locked briefly after exit.
    The new exe is started only after a successful move; otherwise the old one restarts
    and the failure is written next to the script.
    """
    lines = ["@echo off"]
    for i, pid in enumerate(pids):
        # each wait is capped (~30 s) so an unrelated long-lived parent can't hang the update
        lines += [
            f"set w{i}=0",
            f":wait{i}",
            f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul',
            f"if errorlevel 1 goto waited{i}",
            f"set /a w{i}+=1",
            f"if %w{i}% GEQ 30 goto waited{i}",
            "timeout /t 1 /nobreak >nul",
            f"goto wait{i}",
            f":waited{i}",
        ]
    lines += [
        "set tries=0",
        ":retry",
        f'move /Y "{new_exe}" "{target_exe}" >nul 2>&1',
        "if not errorlevel 1 goto moved",
        "set /a tries+=1",
        "if %tries% GEQ 30 goto failed",
        "timeout /t 1 /nobreak >nul",
        "goto retry",
        ":failed",
        f'echo Box Agent update failed: could not replace "{target_exe}" > "%~dp0update-error.txt"',
        f'start "" "{target_exe}"',
        "exit /b 1",
        ":moved",
        f'start "" "{target_exe}"',
        '(goto) 2>nul & del "%~f0"',
    ]
    script_path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    return script_path


def apply_update(release: Release) -> bool:
    """Start replacing the running exe. Returns True if the caller should quit now."""
    if not getattr(sys, "frozen", False):
        webbrowser.open(release.page_url)
        return False
    stage = Path(tempfile.mkdtemp(prefix="BoxAgent-update-"))  # fresh, user-private
    sha = parse_sha_file(download(release.sha_url, stage / SHA_NAME).read_text(encoding="utf-8"))
    new_exe = download(release.exe_url, stage / "BoxAgent-new.exe")
    if not verify_sha256(new_exe, sha):
        new_exe.unlink(missing_ok=True)
        raise ValueError("Downloaded update failed its SHA-256 check")
    script = write_swap_script([os.getpid(), os.getppid()], new_exe, Path(sys.executable), stage / "swap.cmd")
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    shell = winpaths.cmd()
    subprocess.Popen([str(shell), "/c", str(script)], cwd=str(stage), creationflags=flags, close_fds=True)
    return True
