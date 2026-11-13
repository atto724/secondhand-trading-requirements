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
