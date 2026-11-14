"""Database connections and initial account schema."""

import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "data" / "trading.db"


def connect_database() -> sqlite3.Connection:
    """Open a connection with foreign key enforcement enabled."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    """Create account tables and built-in roles if they do not exist."""
    with closing(connect_database()) as connection:
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    phone TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'disabled')),
                    created_at TEXT NOT NULL DEFAULT
                        (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                        CHECK (name IN ('buyer', 'seller', 'admin'))
                );

                CREATE TABLE IF NOT EXISTS account_roles (
                    account_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    PRIMARY KEY (account_id, role_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(id),
                    FOREIGN KEY (role_id) REFERENCES roles(id)
                );
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY,
                    seller_id INTEGER NOT NULL,
                    category_id INTEGER,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    price_cents INTEGER NOT NULL DEFAULT 0
                        CHECK (
                            typeof(price_cents) = 'integer'
                            AND price_cents >= 0
                        ),
                    status TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN (
                            'draft', 'pending_review', 'published',
                            'reserved', 'sold', 'delisted', 'violation'
                        )),
                    version INTEGER NOT NULL DEFAULT 1
                        CHECK (version >= 1),
                    created_at TEXT NOT NULL DEFAULT
                        (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT
                        (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    first_published_at TEXT,
                    sold_at TEXT,
                    FOREIGN KEY (seller_id) REFERENCES accounts(id),
                    FOREIGN KEY (category_id) REFERENCES categories(id)
                );

                CREATE TABLE IF NOT EXISTS product_images (
                    id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    display_order INTEGER NOT NULL
                        CHECK (display_order >= 0),
                    created_at TEXT NOT NULL DEFAULT
                        (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                        ON DELETE CASCADE,
                    UNIQUE (product_id, display_order)
                );
                CREATE INDEX IF NOT EXISTS idx_products_seller
                    ON products(seller_id);

                CREATE INDEX IF NOT EXISTS idx_products_status_category
                    ON products(status, category_id);

                INSERT OR IGNORE INTO categories (name) VALUES ('数码');
                INSERT OR IGNORE INTO categories (name) VALUES ('图书');
                INSERT OR IGNORE INTO categories (name) VALUES ('生活用品');
                INSERT OR IGNORE INTO categories (name) VALUES ('其他');

                INSERT OR IGNORE INTO roles (name) VALUES ('buyer');
                INSERT OR IGNORE INTO roles (name) VALUES ('seller');
                INSERT OR IGNORE INTO roles (name) VALUES ('admin');
                """
            )


def main() -> None:
    """Initialize the database and display its tables."""
    initialize_database()
    with closing(connect_database()) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' ORDER BY name"
        ).fetchall()
        print(f"Database: {DATABASE_PATH}")
        print("Tables:", ", ".join(row["name"] for row in tables))


if __name__ == "__main__":
    main()
