"""SQLite access layer: connection handling and schema (created automatically)."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    event_type TEXT NOT NULL CHECK (length(trim(event_type)) > 0),
    event_date TEXT NOT NULL,
    expected_guests INTEGER NOT NULL CHECK (expected_guests BETWEEN 1 AND 100000),
    registration_count INTEGER NOT NULL DEFAULT 0 CHECK (registration_count BETWEEN 0 AND 100000),
    confidence_pct REAL NOT NULL DEFAULT 80 CHECK (confidence_pct BETWEEN 0 AND 100),
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast','lunch','dinner','snacks')),
    veg_percent REAL NOT NULL DEFAULT 40 CHECK (veg_percent BETWEEN 0 AND 100),
    dietary_tags TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);

CREATE TABLE IF NOT EXISTS dishes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) > 0),
    food_category TEXT NOT NULL,
    dietary_category TEXT NOT NULL CHECK (dietary_category IN ('vegetarian','vegan','non_vegetarian')),
    default_portion_g REAL NOT NULL CHECK (default_portion_g > 0 AND default_portion_g <= 2000),
    default_rate_pct REAL NOT NULL CHECK (default_rate_pct BETWEEN 0 AND 100),
    default_cost_per_kg REAL CHECK (default_cost_per_kg IS NULL OR default_cost_per_kg >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_dishes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    dish_id INTEGER NOT NULL REFERENCES dishes(id) ON DELETE RESTRICT,
    portion_g REAL NOT NULL CHECK (portion_g > 0 AND portion_g <= 2000),
    rate_pct REAL NOT NULL CHECK (rate_pct BETWEEN 0 AND 100),
    cost_per_kg REAL CHECK (cost_per_kg IS NULL OR cost_per_kg >= 0),
    UNIQUE (event_id, dish_id)
);
CREATE INDEX IF NOT EXISTS idx_event_dishes_event ON event_dishes(event_id);

CREATE TABLE IF NOT EXISTS planning_assumptions (
    event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
    no_show_rate_pct REAL NOT NULL DEFAULT 10 CHECK (no_show_rate_pct BETWEEN 0 AND 90),
    shortage_risk_pct REAL NOT NULL DEFAULT 10 CHECK (shortage_risk_pct BETWEEN 1 AND 40),
    safety_buffer_pct REAL NOT NULL DEFAULT 0 CHECK (safety_buffer_pct BETWEEN 0 AND 50),
    portion_adjust_pct REAL NOT NULL DEFAULT 0 CHECK (portion_adjust_pct BETWEEN -30 AND 50),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS food_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    event_dish_id INTEGER NOT NULL UNIQUE REFERENCES event_dishes(id) ON DELETE CASCADE,
    estimated_attendance REAL NOT NULL,
    expected_servings REAL NOT NULL,
    recommended_servings INTEGER NOT NULL,
    recommended_kg REAL NOT NULL,
    expected_leftover_kg REAL NOT NULL,
    food_cost REAL,
    surplus_cost REAL,
    calculated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_estimates_event ON food_estimates(event_id);

CREATE TABLE IF NOT EXISTS ngos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    city TEXT NOT NULL DEFAULT '',
    service_areas TEXT NOT NULL DEFAULT '',
    food_types TEXT NOT NULL DEFAULT '',
    contact_person TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    is_sample INTEGER NOT NULL DEFAULT 0 CHECK (is_sample IN (0,1)),
    source_label TEXT NOT NULL DEFAULT 'Added by user',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ngos_city ON ngos(city);

CREATE TABLE IF NOT EXISTS donations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    ngo_id INTEGER REFERENCES ngos(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','ready_for_contact','contacted','accepted','completed','cancelled')),
    prepared_at TEXT NOT NULL,
    handoff_deadline TEXT NOT NULL,
    safety_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK (safety_acknowledged IN (0,1)),
    pickup_notes TEXT NOT NULL DEFAULT '',
    summary_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_donations_event ON donations(event_id);
CREATE INDEX IF NOT EXISTS idx_donations_status ON donations(status);

CREATE TABLE IF NOT EXISTS donation_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    donation_id INTEGER NOT NULL REFERENCES donations(id) ON DELETE CASCADE,
    event_dish_id INTEGER REFERENCES event_dishes(id) ON DELETE SET NULL,
    dish_name TEXT NOT NULL,
    food_category TEXT NOT NULL,
    quantity_kg REAL NOT NULL CHECK (quantity_kg > 0),
    estimated_leftover_kg REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS donation_status_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    donation_id INTEGER NOT NULL REFERENCES donations(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL
);
"""


def connect(path):
    """Open a SQLite connection with foreign keys enforced."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_schema(conn):
    """Create tables if missing. Never drops or erases existing data."""
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()


def init_db_file(path):
    conn = connect(path)
    try:
        init_schema(conn)
    finally:
        conn.close()
