import sqlite3
from contextlib import contextmanager
from pathlib import Path

from astrofinance import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_connection(db_path: Path | None = None):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> Path:
    path = db_path or config.DB_PATH
    with get_connection(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    return path
