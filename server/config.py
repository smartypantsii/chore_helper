from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "catalog"
WEB_DIR = ROOT / "web"
DATA_DIR = Path(os.environ.get("CHORE_HELPER_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "chore_helper.db"
SECRET_PATH = DATA_DIR / "session_secret"
PARENT_USERNAME = os.environ.get("CHORE_HELPER_PARENT_USER", "parent")
PARENT_PASSWORD = os.environ.get("CHORE_HELPER_PARENT_PASSWORD", "change-me")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def session_secret() -> str:
    ensure_data_dir()
    if SECRET_PATH.exists():
        return SECRET_PATH.read_text(encoding="utf-8").strip()
    value = secrets.token_hex(32)
    SECRET_PATH.write_text(value + "\n", encoding="utf-8")
    SECRET_PATH.chmod(0o600)
    return value
