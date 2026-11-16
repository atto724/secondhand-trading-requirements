"""Public-profile, seller-inventory and private-conversation boundaries."""

import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import database
from accounts import create_account
from catalog import search_products
from community import conversation, inbox, seller_profile, send_direct_message, update_profile


class CommunityTests(unittest.TestCase):
    """Exercise persistence and authorization rather than UI-only validation."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.original = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.original)
        database.DATABASE_PATH = Path(self.folder.name) / "trading.db"
        database.initialize_database()
        self.seller, self.buyer, self.other = [
            create_account(name, f"1380000000{number}", "DemoPass123!")
            for number, name in enumerate(("seller", "buyer", "other"), 1)
        ]

    def test_public_allowlist_zero_cohort_and_self_profile_update(self):
        update_profile(self.seller, "小林", "闲置物品转让", "南京")
        data = seller_profile(self.buyer, self.seller)
        self.assertEqual(data["nickname"], "小林")
        self.assertEqual(data["region"], "南京")
        self.assertIsNone(data["conversion"])
        self.assertTrue({"phone", "password_hash", "ip"}.isdisjoint(data))
        self.assertEqual(seller_profile(self.seller, self.buyer)["nickname"], "")
        with self.assertRaises(ValueError):
            update_profile(self.seller, "x" * 31, "", "")
        database.initialize_database()
        self.assertEqual(seller_profile(self.buyer, self.seller)["nickname"], "小林")

    def test_public_inventory_and_rate_have_distinct_historical_scope(self):
        with closing(database.connect_database()) as connection:
            with connection:
                for owner, status, published, blocked, deleted in (
                    (self.seller, "published", True, 0, 0),
                    (self.seller, "draft", False, 0, 0),
                    (self.seller, "sold", True, 0, 0),
                    (self.seller, "published", True, 1, 0),
                    (self.seller, "draft", True, 0, 1),
                    (self.other, "published", True, 0, 0),
                ):
                    connection.execute(
                        "INSERT INTO products(seller_id,title,status,first_published_at,blocked,deleted) VALUES(?,?,?,?,?,?)",
                        (
                            owner,
                            "fixture",
                            status,
                            "2026-11-01T00:00:00Z" if published else None,
                            blocked,
                            deleted,
                        ),
                    )
        rows, total = search_products(self.buyer, seller_id=self.seller)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["seller_id"], self.seller)
        data = seller_profile(self.buyer, self.seller)
        self.assertEqual((data["published"], data["sold"], data["selling"]), (4, 1, 1))
        self.assertEqual(data["conversion"], 0.25)

    def test_bidirectional_messages_unread_and_third_party_isolation(self):
        first = send_direct_message(self.buyer, self.seller, "请问还在吗？")
        send_direct_message(self.other, self.seller, "另一段私信")
        self.assertEqual(inbox(self.seller)[1]["unread"], 1)
        data = conversation(self.seller, self.buyer)
        self.assertEqual([row["id"] for row in data["rows"]], [first])
        self.assertEqual(inbox(self.seller)[0]["unread"], 1)
        self.assertEqual(inbox(self.seller)[1]["unread"], 0)
        send_direct_message(self.seller, self.buyer, "还在，可以预约。")
        self.assertEqual(len(conversation(self.buyer, self.seller)["rows"]), 2)
        self.assertEqual(conversation(self.other, self.buyer)["rows"], [])
        with closing(database.connect_database()) as connection:
            self.assertNotIn(
                "请问还在吗",
                str(
                    [
                        tuple(row)
                        for row in connection.execute(
                            "SELECT before_value,after_value FROM audit_logs WHERE action='send_private_message'"
                        )
                    ]
                ),
            )

    def test_invalid_or_disabled_sender_and_receiver_cannot_send(self):
        for target, body in (
            (self.buyer, "hello"),
            (self.seller, " "),
            (self.seller, "x" * 1001),
            (9999, "hello"),
        ):
            with self.assertRaises(ValueError):
                send_direct_message(self.buyer, target, body)
        send_direct_message(self.buyer, self.seller, "原有历史")
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute(
                    "UPDATE accounts SET status='disabled' WHERE id=?", (self.seller,)
                )
        self.assertFalse(conversation(self.buyer, self.seller)["can_send"])
        with self.assertRaises(ValueError):
            send_direct_message(self.buyer, self.seller, "不能发送")
        with self.assertRaises(ValueError):
            send_direct_message(self.seller, self.buyer, "不能发送")
        with self.assertRaises(ValueError):
            seller_profile(self.buyer, self.seller)

    def test_cursor_pagination_does_not_mark_unseen_older_messages_read(self):
        with closing(database.connect_database()) as connection:
            with connection:
                connection.executemany(
                    "INSERT INTO direct_messages(sender_id,receiver_id,content,created_at) VALUES(?,?,?,'2026-11-16T00:00:00Z')",
                    [(self.buyer, self.seller, str(index)) for index in range(105)],
                )
        newest = conversation(self.seller, self.buyer)["rows"]
        self.assertEqual(len(newest), 100)
        self.assertEqual(inbox(self.seller)[0]["unread"], 5)
        older = conversation(self.seller, self.buyer, newest[0]["id"])["rows"]
        self.assertEqual(len(older), 5)
        self.assertFalse({row["id"] for row in newest} & {row["id"] for row in older})
        self.assertEqual(inbox(self.seller)[0]["unread"], 0)


if __name__ == "__main__":
    unittest.main()
