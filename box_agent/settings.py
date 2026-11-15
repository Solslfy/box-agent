"""User settings (JSON in %APPDATA%) and the API key (Windows Credential Manager)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import keyring

DEFAULT_MODEL = "anthropic/claude-haiku-5.5"
KEYRING_SERVICE = "BoxAgent"
KEYRING_USER = "openrouter"


@dataclass
class Settings:
    model: str = DEFAULT_MODEL
    max_steps: int = 25
    settle_delay: float = 0.6
    hotkey_select: str = "ctrl+shift+space"
    hotkey_stop: str = "ctrl+shift+x"
    dry_run: bool = False
    check_updates: bool = True


def default_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "BoxAgent" / "settings.json"


def load(path: Path | None = None) -> Settings:
    path = path or default_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known})


def save(s: Settings, path: Path | None = None) -> None:
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")


def get_api_key() -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.KeyringError:
        return None


def set_api_key(key: str) -> None:
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
