"""SQLite setup and connection helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import PROJECT_ROOT

SCHEMA_FILE = PROJECT_ROOT / "data" / "schema.sql"
SEED_FILE = PROJECT_ROOT / "data" / "seed.sql"


def init_db(db_path: Path) -> Path:
    """(Re)create the database from schema.sql + seed.sql. Safe to run repeatedly."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_FILE.read_text())
        conn.executescript(SEED_FILE.read_text())
    return db_path


def connect(db_path: Path, read_only: bool = True) -> sqlite3.Connection:
    """Open the database. Tools use read-only mode so they cannot modify data."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run: python -m scagent init-db"
        )
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
