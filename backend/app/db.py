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
    uncertain INTEGER NOT NULL DEFAULT 0,
    tracking_mode TEXT NOT NULL DEFAULT 'binary'
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
    steps_json TEXT NOT NULL DEFAULT '[]',
    prep_minutes REAL,
    cook_minutes REAL,
    total_minutes REAL,
    cuisine TEXT,
    category TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    image_url TEXT,
    step_ingredients_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ingredients (
    id TEXT PRIMARY KEY,
    recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    raw TEXT NOT NULL,
    amount REAL,
    unit TEXT,
    item_id TEXT REFERENCES items(id),
    tracked INTEGER NOT NULL DEFAULT 1,
    suggestion TEXT,
    alt_group TEXT,
    selected INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS shopping_list (
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    amount REAL NOT NULL,
    unit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS barcode_cache (
    barcode TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'found',
    name TEXT,
    brand TEXT,
    quantity TEXT,
    image_url TEXT,
    categories_json TEXT NOT NULL DEFAULT '[]',
    source TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS item_barcodes (
    barcode TEXT PRIMARY KEY,
    -- one generic inventory item backs many product barcodes: eggs bought
    -- at Aldi, REWE or Edeka all deduct from the same "Eier" stock
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS plan_persons (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_meals (
    id TEXT PRIMARY KEY,
    week_start TEXT NOT NULL,
    day INTEGER NOT NULL,
    meal TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_meal_persons (
    meal_id TEXT NOT NULL REFERENCES plan_meals(id) ON DELETE CASCADE,
    person_id TEXT NOT NULL REFERENCES plan_persons(id) ON DELETE CASCADE,
    PRIMARY KEY (meal_id, person_id)
);

CREATE TABLE IF NOT EXISTS plan_fills (
    id TEXT PRIMARY KEY,
    meal_id TEXT NOT NULL REFERENCES plan_meals(id) ON DELETE CASCADE,
    recipe_id TEXT REFERENCES recipes(id) ON DELETE CASCADE,
    prepared_id TEXT REFERENCES plan_prepared(id) ON DELETE CASCADE,
    person_id TEXT REFERENCES plan_persons(id) ON DELETE SET NULL,
    portions REAL NOT NULL DEFAULT 1,
    prep_multiplier REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS plan_prepared (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    recipe_id TEXT REFERENCES recipes(id) ON DELETE SET NULL,
    portions REAL NOT NULL DEFAULT 1,
    manual INTEGER NOT NULL DEFAULT 0
);
"""


@contextmanager
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)
        # migrate legacy single-barcode values into the multi-barcode table
        db.execute(
            "INSERT OR IGNORE INTO item_barcodes (item_id, barcode)"
            " SELECT id, barcode FROM items WHERE barcode IS NOT NULL"
        )
        item_columns = {row["name"] for row in db.execute("PRAGMA table_info(items)")}
        if "tracking_mode" not in item_columns:
            db.execute("ALTER TABLE items ADD COLUMN tracking_mode TEXT NOT NULL DEFAULT 'binary'")
            # data-entry heuristic: a single entered unit is binary,
            # several units on record mean the stock is being counted
            db.execute(
                "UPDATE items SET tracking_mode = CASE WHEN quantity > 1 THEN 'qty' ELSE 'binary' END"
            )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(ingredients)")}
        if "unit" not in columns:
            db.execute("ALTER TABLE ingredients ADD COLUMN unit TEXT")
        # and/or alternative groups: members share alt_group; the picked
        # option is marked selected=1 (exactly one per group)
        if "alt_group" not in columns:
            db.execute("ALTER TABLE ingredients ADD COLUMN alt_group TEXT")
        if "selected" not in columns:
            db.execute("ALTER TABLE ingredients ADD COLUMN selected INTEGER NOT NULL DEFAULT 0")
        recipe_columns = {row["name"] for row in db.execute("PRAGMA table_info(recipes)")}
        additions = {
            "prep_minutes": "REAL",
            "cook_minutes": "REAL",
            "total_minutes": "REAL",
            "cuisine": "TEXT",
            "category": "TEXT",
            "tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "image_url": "TEXT",
            # SQLite forbids non-constant DEFAULT expressions in ALTER TABLE
            # ADD COLUMN, so backfill existing rows below instead
            "created_at": "TEXT",
        }
        for column, kind in additions.items():
            if column not in recipe_columns:
                db.execute(f"ALTER TABLE recipes ADD COLUMN {column} {kind}")
        db.execute("UPDATE recipes SET created_at = datetime('now') WHERE created_at IS NULL")
        # live step quantities: spans of ingredient mentions per step, the
        # (qty) shown behind them is computed from the portions at render
        if "step_ingredients_json" not in recipe_columns:
            db.execute("ALTER TABLE recipes ADD COLUMN step_ingredients_json TEXT")
        # per-person fills: dropping onto a divided meal field records
        # which person the portion is for
        fill_columns = {row["name"] for row in db.execute("PRAGMA table_info(plan_fills)")}
        if "person_id" not in fill_columns:
            db.execute("ALTER TABLE plan_fills ADD COLUMN person_id TEXT")
            db.execute("UPDATE plan_fills SET person_id = NULL")

