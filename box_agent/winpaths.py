"""Absolute paths to Windows system programs.

Never launch system tools by bare name: Windows searches the app's own folder (e.g. Downloads)
and the current directory before System32, so a planted powershell.exe/cmd.exe would run instead.
"""
from __future__ import annotations

import os
from pathlib import Path


def system32(*parts: str) -> Path:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return Path(root, "System32", *parts)


def powershell() -> Path:
    return system32("WindowsPowerShell", "v1.0", "powershell.exe")


def cmd() -> Path:
    return system32("cmd.exe")
