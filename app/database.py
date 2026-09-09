from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import get_settings

DATABASE_PATH = get_settings().database_path


def database_path() -> Path:
    return DATABASE_PATH


def connection() -> sqlite3.Connection:
    database_path().parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(database_path())
    conn.row_factory = sqlite3.Row
    return conn
