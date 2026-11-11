import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "PANTRY_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pantry.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'Pantry',
    quantity REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT 'pcs',
    min_quantity REAL NOT NULL DEFAULT 0,
    package_size REAL NOT NULL DEFAULT 1,
    barcode TEXT,
    uncertain INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY,
    store TEXT NOT NULL,
    date TEXT NOT NULL,
    total REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'processing',
    source_file TEXT,
    message_hash TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS receipt_items (
    id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    raw_name TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    suggestion TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'pasted',
    base_portions REAL NOT NULL DEFAULT 4,
    steps_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS ingredients (
    id TEXT PRIMARY KEY,
    recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    raw TEXT NOT NULL,
    amount REAL,
    item_id TEXT REFERENCES items(id),
    tracked INTEGER NOT NULL DEFAULT 1,
    suggestion TEXT
);

CREATE TABLE IF NOT EXISTS shopping_list (
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    amount REAL NOT NULL,
    unit TEXT NOT NULL
);
"""


@contextmanager
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)
