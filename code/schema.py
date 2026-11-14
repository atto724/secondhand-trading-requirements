"""Additive schema migrations for reservations, governance and audit."""

SQL = """
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    buyer_id INTEGER NOT NULL REFERENCES accounts(id),
    status TEXT NOT NULL CHECK(status IN (
        'waiting','confirmed','delivered','cancel_requested','manual',
        'completed','cancelled','rejected','expired','corrected')),
    snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    delivered_at TEXT,
    completed_at TEXT,
    cancel_by INTEGER REFERENCES accounts(id),
    cancel_previous TEXT,
    reason TEXT NOT NULL DEFAULT '',
    reminder_sent INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS reservation_buyer_active
ON reservations(product_id,buyer_id)
WHERE status IN ('waiting','confirmed','delivered','cancel_requested','manual');
CREATE UNIQUE INDEX IF NOT EXISTS reservation_product_confirmed
ON reservations(product_id)
WHERE status IN ('confirmed','delivered','cancel_requested','manual');
CREATE INDEX IF NOT EXISTS reservations_buyer ON reservations(buyer_id,status);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    version INTEGER NOT NULL,
    admin_id INTEGER NOT NULL REFERENCES accounts(id),
    approved INTEGER NOT NULL CHECK(approved IN (0,1)),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS product_history (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    actor_id INTEGER NOT NULL REFERENCES accounts(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    receiver_id INTEGER NOT NULL REFERENCES accounts(id),
    product_id INTEGER REFERENCES products(id),
    reservation_id INTEGER REFERENCES reservations(id),
    event_type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1))
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER REFERENCES accounts(id),
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id INTEGER,
    before_value TEXT NOT NULL,
    after_value TEXT NOT NULL,
    result TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id),
    admin_id INTEGER NOT NULL REFERENCES accounts(id),
    before_value TEXT NOT NULL,
    after_value TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backup_runs (
    id INTEGER PRIMARY KEY,
    file_name TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def migrate(connection):
    """Extend existing databases without dropping user data."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(products)")}
    additions = {
        "condition_label": "TEXT NOT NULL DEFAULT '未注明'",
        "shipping": "TEXT NOT NULL DEFAULT '线下自提'",
        "negotiable": "INTEGER NOT NULL DEFAULT 0",
        "blocked": "INTEGER NOT NULL DEFAULT 0",
        "deleted": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE products ADD COLUMN {name} {declaration}")
    connection.commit()
    connection.executescript(SQL)
