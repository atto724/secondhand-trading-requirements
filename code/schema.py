"""Additive schema migrations for reservations, governance and audit."""

SQL = """
CREATE TABLE IF NOT EXISTS public_profiles (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
    nickname TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS direct_messages (
    id INTEGER PRIMARY KEY,
    sender_id INTEGER NOT NULL REFERENCES accounts(id),
    receiver_id INTEGER NOT NULL REFERENCES accounts(id),
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 1000),
    created_at TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
    CHECK(sender_id != receiver_id)
);
CREATE INDEX IF NOT EXISTS dm_sender_receiver ON direct_messages(sender_id,receiver_id,id);
CREATE INDEX IF NOT EXISTS dm_receiver_sender ON direct_messages(receiver_id,sender_id,id);
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
    profile_columns = {row[1] for row in connection.execute("PRAGMA table_info(public_profiles)")}
    if "avatar_path" not in profile_columns:
        connection.execute(
            "ALTER TABLE public_profiles ADD COLUMN avatar_path TEXT NOT NULL DEFAULT ''"
        )
        connection.commit()
    migrate_categories(connection)


CATEGORY_NAMES = (
    "数码电器",
    "家居生活",
    "服饰鞋包",
    "图书文教",
    "运动户外",
    "兴趣娱乐",
    "母婴用品",
    "宠物用品",
    "交通出行",
    "其他闲置",
)
LEGACY_CATEGORIES = {
    "数码": "数码电器",
    "图书": "图书文教",
    "生活用品": "家居生活",
    "其他": "其他闲置",
}


def migrate_categories(connection):
    """Keep original IDs where possible and hide merged legacy rows from selectors."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(categories)")}
    for name, declaration in {
        "is_active": "INTEGER NOT NULL DEFAULT 1",
        "sort_order": "INTEGER NOT NULL DEFAULT 99",
    }.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE categories ADD COLUMN {name} {declaration}")
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    with connection:
        for old_name, new_name in LEGACY_CATEGORIES.items():
            old = connection.execute(
                "SELECT id FROM categories WHERE name=?", (old_name,)
            ).fetchone()
            target = connection.execute(
                "SELECT id FROM categories WHERE name=?", (new_name,)
            ).fetchone()
            if old and not target:
                connection.execute("UPDATE categories SET name=? WHERE id=?", (new_name, old[0]))
            elif old and target:
                connection.execute(
                    "UPDATE products SET category_id=? WHERE category_id=?", (target[0], old[0])
                )
                connection.execute("UPDATE categories SET is_active=0 WHERE id=?", (old[0],))
        for order, name in enumerate(CATEGORY_NAMES):
            connection.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
            connection.execute(
                "UPDATE categories SET is_active=1,sort_order=? WHERE name=?", (order, name)
            )
        placeholders = ",".join("?" for _ in CATEGORY_NAMES)
        connection.execute(
            f"UPDATE categories SET is_active=0 WHERE name NOT IN ({placeholders})", CATEGORY_NAMES
        )
