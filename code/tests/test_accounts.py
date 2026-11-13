"""Automated tests for account registration and login."""

import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import database
from accounts import authenticate, create_account


class AccountTests(unittest.TestCase):
    """Check account rules against an isolated database."""

    def setUp(self):
        """Create a fresh database before each test."""
        self.original_path = database.DATABASE_PATH
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.restore_database_path)
        database.DATABASE_PATH = Path(self.folder.name) / "test.db"
        database.initialize_database()

    def restore_database_path(self):
        """Restore the application database setting."""
        database.DATABASE_PATH = self.original_path

    def create_demo_account(self):
        """Create an ordinary account for a test."""
        return create_account(
            "demo_user", "13800000000", "DemoPassword123!"
        )

    def test_registration_assigns_ordinary_roles(self):
        """New accounts receive buyer and seller roles only."""
        account_id = self.create_demo_account()
        with closing(database.connect_database()) as connection:
            rows = connection.execute(
                "SELECT r.name FROM roles AS r "
                "JOIN account_roles AS ar ON ar.role_id = r.id "
                "WHERE ar.account_id = ? ORDER BY r.name",
                (account_id,),
            ).fetchall()

        self.assertEqual(
            [row["name"] for row in rows], ["buyer", "seller"]
        )

    def test_duplicate_registration_is_rejected(self):
        """Duplicate names and phones do not create extra accounts."""
        self.create_demo_account()
        for username, phone in [
            ("demo_user", "13900000000"),
            ("another_user", "13800000000"),
        ]:
            with self.subTest(username=username, phone=phone):
                with self.assertRaises(ValueError):
                    create_account(username, phone, "DemoPassword123!")

        with closing(database.connect_database()) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM accounts"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_valid_login(self):
        """Correct credentials return the account ID."""
        account_id = self.create_demo_account()
        self.assertEqual(
            authenticate("demo_user", "DemoPassword123!"),
            account_id,
        )

    def test_invalid_login(self):
        """Wrong passwords and unknown accounts are rejected."""
        self.create_demo_account()
        for username, password in [
            ("demo_user", "WrongPassword"),
            ("unknown_user", "DemoPassword123!"),
        ]:
            with self.subTest(username=username):
                with self.assertRaises(ValueError):
                    authenticate(username, password)

    def test_disabled_account_cannot_login(self):
        """Disabled accounts cannot log in with a correct password."""
        account_id = self.create_demo_account()
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute(
                    "UPDATE accounts SET status = 'disabled' WHERE id = ?",
                    (account_id,),
                )

        with self.assertRaisesRegex(ValueError, "禁用"):
            authenticate("demo_user", "DemoPassword123!")


if __name__ == "__main__":
    unittest.main()
