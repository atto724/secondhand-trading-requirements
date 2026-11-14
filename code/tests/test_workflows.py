"""Integration tests for state consistency, authorization and fault recovery."""

import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

import catalog
import database
import governance
import operations
import trades
from accounts import authenticate
from core import money
from security import hash_password


class WorkflowTests(unittest.TestCase):
    """Use isolated real SQLite databases rather than mocked state transitions."""

    @classmethod
    def setUpClass(cls):
        cls.password_hash = hash_password("DemoPassword123!")

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.old_path = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.old_path)
        self.root = Path(self.folder.name)
        database.DATABASE_PATH = self.root / "data" / "trading.db"
        database.initialize_database()
        with closing(database.connect_database()) as connection:
            with connection:
                for number, name in enumerate(("seller", "buyer", "other", "administrator"), 1):
                    connection.execute(
                        "INSERT INTO accounts(id,username,phone,password_hash) VALUES(?,?,?,?)",
                        (number, name, f"1380000{number:04d}", self.password_hash),
                    )
                    connection.execute(
                        "INSERT INTO account_roles SELECT ?,id FROM roles WHERE name IN ('buyer','seller')",
                        (number,),
                    )
                connection.execute(
                    "INSERT INTO account_roles SELECT 4,id FROM roles WHERE name='admin'"
                )
        self.category = self.query("SELECT id FROM categories LIMIT 1")[0][0]
        self.source = self.root / "image.png"
        with Image.new("RGB", (100, 80), "orange") as image:
            image.save(self.source)

    def query(self, sql, args=()):
        with closing(database.connect_database()) as connection:
            return connection.execute(sql, args).fetchall()

    def execute(self, sql, args=()):
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute(sql, args)

    def draft(self, **kwargs):
        fields = dict(
            title="测试图书", description="完整描述", category_id=self.category, cents=1990
        )
        fields.update(kwargs)
        return catalog.save_product(1, **fields)

    def published(self):
        key = self.draft()
        catalog.submit_review(1, key, 1)
        catalog.review_product(4, key, 1, True)
        return key

    def delivered(self):
        key = self.published()
        reservation = trades.reserve(2, key)
        trades.confirm_reservation(1, reservation)
        trades.register_delivery(1, reservation)
        return key, reservation

    def test_schema_upgrade_preserves_old_rows(self):
        key = self.draft()
        database.initialize_database()
        self.assertEqual(
            self.query("SELECT title FROM products WHERE id=?", (key,))[0][0], "测试图书"
        )

    def test_image_success_and_source_independence(self):
        key = self.draft(image_paths=[str(self.source)])
        relative = self.query("SELECT file_path FROM product_images WHERE product_id=?", (key,))[0][
            0
        ]
        self.source.unlink()
        self.assertTrue((database.DATABASE_PATH.parent / relative).is_file())

    def test_second_image_failure_rolls_back_everything(self):
        missing = self.root / "missing.png"
        with self.assertRaises(ValueError):
            self.draft(image_paths=[str(self.source), str(missing)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM products")[0][0], 0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM product_images")[0][0], 0)
        self.assertEqual(list((database.DATABASE_PATH.parent / "images").glob("*")), [])

    def test_database_image_failure_rolls_back_and_cleans(self):
        self.execute(
            "CREATE TRIGGER fail_image BEFORE INSERT ON product_images BEGIN SELECT RAISE(ABORT,'fault'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.draft(image_paths=[str(self.source)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM products")[0][0], 0)
        self.assertEqual(list((database.DATABASE_PATH.parent / "images").glob("*")), [])

    def test_required_fields_and_price(self):
        for fields in (
            {"title": " "},
            {"description": ""},
            {"category_id": None},
            {"cents": 0},
            {"cents": True},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.draft(**fields)
        self.assertEqual(money("19.90"), 1990)
        for value in ("NaN", "Infinity", "1.234", "-1", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)

    def test_legacy_empty_draft_requires_repair_or_delete(self):
        self.execute("INSERT INTO products(seller_id) VALUES(1)")
        key = self.query("SELECT id FROM products")[0][0]
        with self.assertRaises(ValueError):
            catalog.submit_review(1, key, 1)
        catalog.save_product(
            1, "补全", "补全描述", self.category, 100, product_id=key, expected_version=1
        )
        catalog.submit_review(1, key, 2)
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "pending_review")

    def test_owner_isolation(self):
        key = self.draft()
        with self.assertRaises(ValueError):
            catalog.product_detail(2, key)
        rows, count = catalog.search_products(2, scope="mine")
        self.assertEqual((rows, count), ([], 0))
        with self.assertRaises(ValueError):
            catalog.delete_draft(2, key)

    def test_soft_delete_draft(self):
        key = self.draft()
        catalog.delete_draft(1, key)
        self.assertEqual(catalog.search_products(1, scope="mine")[1], 0)
        self.assertEqual(self.query("SELECT deleted FROM products WHERE id=?", (key,))[0][0], 1)

    def test_review_rejection_and_stale_version(self):
        key = self.draft()
        catalog.submit_review(1, key, 1)
        catalog.save_product(
            1, "新版", "描述", self.category, 200, product_id=key, expected_version=1
        )
        with self.assertRaises(ValueError):
            catalog.review_product(4, key, 1, True)
        catalog.submit_review(1, key, 2)
        with self.assertRaises(ValueError):
            catalog.review_product(4, key, 2, False, "")
        catalog.review_product(4, key, 2, False, "请补充信息")
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "draft")

    def test_edit_published_requires_new_review_and_preserves_history(self):
        key = self.published()
        catalog.save_product(
            1, "新标题", "新描述", self.category, 2500, product_id=key, expected_version=1
        )
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "pending_review")
        self.assertEqual(self.query("SELECT COUNT(*) FROM product_history")[0][0], 1)
        self.assertEqual(catalog.search_products(2)[1], 0)

    def test_combined_search_and_pagination(self):
        for index in range(10):
            key = self.draft(title=f"图书{index}", cents=100 + index)
            catalog.submit_review(1, key, 1)
            catalog.review_product(4, key, 1, True)
        rows, count = catalog.search_products(
            2, "图书", self.category, 103, 108, "price_asc", page_size=3
        )
        self.assertEqual(count, 6)
        self.assertEqual([row["price_cents"] for row in rows], [103, 104, 105])
        self.assertEqual(len(catalog.search_products(2, page=2)[0]), 2)

    def test_self_reservation_forbidden_and_retry_idempotent(self):
        key = self.published()
        with self.assertRaises(ValueError):
            trades.reserve(1, key)
        first = trades.reserve(2, key)
        self.assertEqual(trades.reserve(2, key), first)
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "published")

    def test_waiting_blocks_edit_and_delist(self):
        key = self.published()
        trades.reserve(2, key)
        with self.assertRaises(ValueError):
            catalog.delist_product(1, key)
        with self.assertRaises(ValueError):
            catalog.save_product(
                1, "标题", "描述", self.category, 100, product_id=key, expected_version=1
            )

    def test_twenty_concurrent_confirmations_only_one_succeeds(self):
        key = self.published()
        first = trades.reserve(2, key)
        second = trades.reserve(3, key)

        def attempt(index):
            try:
                trades.confirm_reservation(1, first if index % 2 else second)
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(attempt, range(20)))
        self.assertEqual(sum(results), 1)
        states = [row[0] for row in self.query("SELECT status FROM reservations")]
        self.assertEqual(sorted(states), ["confirmed", "expired"])
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "reserved")

    def test_confirmation_fault_rolls_back_both_states(self):
        key = self.published()
        reservation = trades.reserve(2, key)
        self.execute(
            "CREATE TRIGGER fail_confirm BEFORE UPDATE OF status ON products "
            "WHEN NEW.status='reserved' BEGIN SELECT RAISE(ABORT,'fault'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            trades.confirm_reservation(1, reservation)
        self.assertEqual(self.query("SELECT status FROM reservations")[0][0], "waiting")
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "published")

    def test_notification_failure_does_not_undo_confirmation(self):
        key = self.published()
        reservation = trades.reserve(2, key)
        self.execute(
            "CREATE TRIGGER fail_notice BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT,'notice'); END"
        )
        with self.assertLogs("core", level="ERROR"):
            trades.confirm_reservation(1, reservation)
        self.assertEqual(self.query("SELECT status FROM reservations")[0][0], "confirmed")

    def test_timeout_boundary_and_fresh_request(self):
        key = self.published()
        reservation = trades.reserve(2, key)
        instant = datetime(2026, 11, 14, tzinfo=timezone.utc)
        stamp = (
            (instant - timedelta(hours=48))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        self.execute("UPDATE reservations SET created_at=? WHERE id=?", (stamp, reservation))
        from core import transaction

        with transaction() as connection:
            trades.expire_waiting(connection, instant)
        self.assertEqual(self.query("SELECT status FROM reservations")[0][0], "expired")
        self.assertNotEqual(trades.reserve(2, key), reservation)

    def test_bilateral_cancel_restores_publication(self):
        key = self.published()
        reservation = trades.reserve(2, key)
        trades.confirm_reservation(1, reservation)
        trades.cancel_reservation(2, reservation, "计划变化")
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "reserved")
        with self.assertRaises(ValueError):
            trades.respond_cancel(2, reservation, True)
        trades.respond_cancel(1, reservation, True)
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "published")

    def test_contacts_hidden_before_confirm_and_after_completion(self):
        key = self.published()
        reservation = trades.reserve(2, key)
        self.assertIsNone(trades.transaction_detail(2, reservation)["contact"])
        trades.confirm_reservation(1, reservation)
        self.assertIsNotNone(trades.transaction_detail(2, reservation)["contact"])
        with self.assertRaises(ValueError):
            trades.transaction_detail(3, reservation)
        trades.register_delivery(1, reservation)
        trades.complete_trade(2, reservation)
        self.assertIsNone(trades.transaction_detail(2, reservation)["contact"])

    def test_completion_idempotent_and_snapshot_immutable(self):
        key, reservation = self.delivered()
        trades.complete_trade(2, reservation)
        trades.complete_trade(2, reservation)
        governance.correct_sale(4, reservation, "核实未成交")
        catalog.save_product(
            1, "新标题", "新描述", self.category, 9999, product_id=key, expected_version=1
        )
        snapshot = trades.transaction_detail(2, reservation)["snapshot"]
        self.assertEqual(snapshot["price_cents"], 1990)
        self.assertEqual(self.query("SELECT COUNT(*) FROM corrections")[0][0], 1)

    def test_overdue_delivery_remains_reserved(self):
        key, reservation = self.delivered()
        stamp = (
            (datetime.now(timezone.utc) - timedelta(days=8))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        self.execute("UPDATE reservations SET delivered_at=? WHERE id=?", (stamp, reservation))
        trades.run_timeouts()
        trades.run_timeouts()
        self.assertEqual(
            self.query("SELECT status FROM products WHERE id=?", (key,))[0][0], "reserved"
        )
        self.assertEqual(self.query("SELECT reminder_sent FROM reservations")[0][0], 1)

    def test_violation_cancellation_never_republishes(self):
        key = self.published()
        reservation = trades.reserve(2, key)
        trades.confirm_reservation(1, reservation)
        governance.block_product(4, key, "违规")
        self.assertEqual(self.query("SELECT status FROM reservations")[0][0], "manual")
        governance.resolve_dispute(4, reservation, True, "核实取消")
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "violation")
        governance.release_product(4, key, "整改完成")
        self.assertEqual(self.query("SELECT status FROM products")[0][0], "draft")

    def test_disabled_seller_restore_does_not_republish(self):
        key = self.published()
        trades.reserve(2, key)
        governance.set_account_enabled(4, 1, False, "核实违规")
        governance.set_account_enabled(4, 1, True, "恢复")
        self.assertEqual(
            self.query("SELECT status FROM products WHERE id=?", (key,))[0][0], "violation"
        )
        self.assertEqual(self.query("SELECT status FROM reservations")[0][0], "expired")

    def test_admin_permissions_rechecked(self):
        with self.assertRaises(ValueError):
            governance.set_admin(2, 3, True, "越权")
        governance.set_admin(4, 3, True, "授权")
        governance.set_admin(4, 3, False, "撤销")
        with self.assertRaises(ValueError):
            operations.query_audit(3)
        with self.assertRaises(ValueError):
            governance.set_admin(4, 4, False, "撤销最后管理员")

    def test_zero_cohort_statistics_and_backup_restore(self):
        self.draft(image_paths=[str(self.source)])
        stats = operations.seller_statistics(1, "2000-01-01", "2099-12-31")
        self.assertEqual(stats["区间首次发布商品截至当前成交率"], "无可计算数据")
        backup = operations.create_backup(4)
        result = operations.verify_backup(backup)
        self.assertEqual(result["图片数量"], 1)

    def test_audit_failure_and_export_are_recorded(self):
        with self.assertRaises(ValueError):
            catalog.submit_review(2, self.draft(), 1)
        destination = self.root / "audit.csv"
        operations.export_audit(4, destination)
        self.assertTrue(destination.is_file())
        self.assertTrue(self.query("SELECT id FROM audit_logs WHERE result='failure'"))
        self.assertTrue(self.query("SELECT id FROM audit_logs WHERE action='export_audit'"))

    def test_restore_into_new_directory_and_refuse_overwrite(self):
        self.draft(image_paths=[str(self.source)])
        archive = operations.create_backup(4)
        target = self.root / "restored"
        operations.restore_backup(archive, target)
        self.assertTrue((target / "trading.db").is_file())
        self.assertTrue(list((target / "images").glob("*")))
        with self.assertRaises(ValueError):
            operations.restore_backup(archive, target)

    def test_more_than_five_images_rejected_atomically(self):
        with self.assertRaises(ValueError):
            self.draft(image_paths=[str(self.source)] * 6)
        self.assertEqual(self.query("SELECT COUNT(*) FROM products")[0][0], 0)

    def test_completion_failure_does_not_sell_product(self):
        key, reservation = self.delivered()
        self.execute(
            "CREATE TRIGGER fail_sold BEFORE UPDATE OF status ON products "
            "WHEN NEW.status='sold' BEGIN SELECT RAISE(ABORT,'fault'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            trades.complete_trade(2, reservation)
        self.assertEqual(
            self.query("SELECT status FROM products WHERE id=?", (key,))[0][0], "reserved"
        )
        self.assertEqual(
            self.query("SELECT status FROM reservations WHERE id=?", (reservation,))[0][0],
            "delivered",
        )


if __name__ == "__main__":
    unittest.main()
