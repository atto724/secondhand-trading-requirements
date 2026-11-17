"""Backup reference coverage and complete stable audit export regressions."""

import csv
import gc
import json
import re
import sqlite3
import tkinter as tk
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
import database
import operations
from admin_ui import MaintenancePage
from catalog import save_product, product_detail
from community import update_avatar
from core import now
from images import copy_image
from security import hash_password
from ui_common import configure_style


class BackupAuditTests(unittest.TestCase):
    """Use real SQLite/ZIP/CSV files isolated from the user's databases."""

    @classmethod
    def setUpClass(cls):
        cls.digest = hash_password("DemoPass123!")

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.old = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.old)
        database.DATABASE_PATH = self.root / "data" / "trading.db"
        database.initialize_database()
        with closing(database.connect_database()) as con:
            with con:
                for key in (1, 2, 3):
                    con.execute(
                        "INSERT INTO accounts(id,username,phone,password_hash) VALUES(?,?,?,?)",
                        (key, f"user{key}", f"1380000000{key}", self.digest),
                    )
                    con.execute(
                        "INSERT INTO account_roles SELECT ?,id FROM roles WHERE name IN ('buyer','seller')",
                        (key,),
                    )
                con.execute("INSERT INTO account_roles SELECT 2,id FROM roles WHERE name='admin'")
                category = con.execute("SELECT id FROM categories LIMIT 1").fetchone()[0]
        image = self.root / "source.png"
        Image.new("RGB", (20, 20), "red").save(image)
        self.product = save_product(1, "sample", "description", category, 1250, [image])
        self.refs = {"商品图片": product_detail(1, self.product)["images"][0]["file_path"]}
        self.refs["用户头像"] = update_avatar(1, image)
        for group in ("预约快照图片", "商品历史图片", "商品消息图片"):
            self.refs[group] = copy_image(image)
        with closing(database.connect_database()) as con:
            with con:
                con.execute(
                    "INSERT INTO reservations(product_id,buyer_id,status,snapshot,created_at) VALUES(?,3,'cancelled',?,?)",
                    (self.product, json.dumps({"images": [self.refs["预约快照图片"]]}), now()),
                )
                con.execute(
                    "INSERT INTO product_history(product_id,version,content,actor_id,created_at) VALUES(?,1,?,1,?)",
                    (
                        self.product,
                        json.dumps({"images": [{"file_path": self.refs["商品历史图片"]}]}),
                        now(),
                    ),
                )
                con.execute(
                    "INSERT INTO direct_messages(sender_id,receiver_id,content,created_at,product_snapshot) VALUES(3,1,'[商品] sample',?,?)",
                    (now(), json.dumps({"image": self.refs["商品消息图片"]})),
                )

    def archive(self):
        return operations.create_backup(2)

    def modified_zip(self, original, name, omitted=None, replacement=None):
        target = self.root / name
        with zipfile.ZipFile(original) as src, zipfile.ZipFile(target, "w") as dest:
            for item in src.namelist():
                if item != omitted:
                    dest.writestr(
                        item,
                        (
                            replacement[item]
                            if replacement and item in replacement
                            else src.read(item)
                        ),
                    )
        return target

    def changed_database(self, archive, name, statement, args=()):
        folder = self.root / name
        folder.mkdir()
        with zipfile.ZipFile(archive) as src:
            src.extractall(folder)
        with closing(sqlite3.connect(folder / "trading.db")) as con:
            with con:
                con.execute(statement, args)
        target = self.root / (name + ".zip")
        with zipfile.ZipFile(target, "w") as dest:
            for path in folder.rglob("*"):
                if path.is_file():
                    dest.write(path, path.relative_to(folder).as_posix())
        return target

    def logs(self, count=2505):
        with closing(database.connect_database()) as con:
            with con:
                for index in range(count):
                    reason = (
                        ("=1+1", " \t@SUM(1)", "+1", "-1")[index] if index < 4 else f"entry {index}"
                    )
                    con.execute(
                        "INSERT INTO audit_logs(actor_id,action,object_type,object_id,before_value,after_value,result,reason,created_at) VALUES(2,'bulk_fixture','audit',?,'{}','{}','success',?,'2026-01-02T00:00:00.000Z')",
                        (index, reason),
                    )
        return operations.audit_page(2, "bulk_fixture", "2026-01-02", "2026-01-02")

    def test_all_five_attachment_groups_and_restore_are_complete(self):
        archive = self.archive()
        result = operations.verify_backup(archive)
        self.assertEqual(result["图片数量"], 5)
        self.assertEqual(result["图片分类数量"], {group: 1 for group in self.refs})
        target = self.root / "restored"
        operations.restore_backup(archive, target)
        for relative in self.refs.values():
            self.assertTrue((target / relative).is_file())
        with self.assertRaises(ValueError):
            operations.restore_backup(archive, target)
        self.assertTrue(database.DATABASE_PATH.is_file())

    def test_missing_each_attachment_and_corrupt_avatar_are_rejected(self):
        archive = self.archive()
        for index, (group, path) in enumerate(self.refs.items()):
            with self.subTest(group=group):
                incomplete = self.modified_zip(archive, f"missing{index}.zip", omitted=path)
                with self.assertRaisesRegex(ValueError, re.escape(path)) as error:
                    operations.verify_backup(incomplete)
                self.assertIn(group, str(error.exception))
        corrupt = self.modified_zip(
            archive, "corrupt.zip", replacement={self.refs["用户头像"]: b"not an image"}
        )
        with self.assertRaisesRegex(ValueError, "文件损坏"):
            operations.verify_backup(corrupt)

    def test_invalid_historical_json_paths_and_missing_database_are_rejected(self):
        archive = self.archive()
        invalid = self.changed_database(
            archive,
            "traversal",
            "UPDATE reservations SET snapshot=?",
            (json.dumps({"images": ["../outside.png"]}),),
        )
        with self.assertRaisesRegex(ValueError, "路径越界"):
            operations.verify_backup(invalid)
        invalid = self.changed_database(
            archive, "json", "UPDATE product_history SET content='broken'"
        )
        with self.assertRaisesRegex(ValueError, "商品历史图片"):
            operations.verify_backup(invalid)
        missing = self.modified_zip(archive, "no-db.zip", omitted="trading.db")
        with self.assertRaisesRegex(ValueError, "缺少 trading.db"):
            operations.verify_backup(missing)

    def test_backup_creation_refuses_missing_historical_file(self):
        original = self.archive()
        (database.DATABASE_PATH.parent / self.refs["商品历史图片"]).unlink()
        with self.assertRaisesRegex(ValueError, "商品历史图片"):
            self.archive()
        self.assertTrue(original.is_file())
        with closing(database.connect_database()) as con:
            self.assertEqual(
                con.execute("SELECT result FROM backup_runs ORDER BY id DESC LIMIT 1").fetchone()[
                    0
                ],
                "failure",
            )
        self.assertEqual(len(list(original.parent.glob("*.zip"))), 1)

    def test_older_backup_without_optional_avatar_or_message_columns(self):
        archive = self.archive()
        old = self.changed_database(
            archive, "old", "ALTER TABLE public_profiles DROP COLUMN avatar_path"
        )
        old = self.changed_database(old, "older", "DROP TABLE direct_messages")
        result = operations.verify_backup(old)
        self.assertEqual(result["图片分类数量"]["用户头像"], 0)
        self.assertEqual(result["图片分类数量"]["商品消息图片"], 0)
        self.assertEqual(result["图片数量"], 3)

    def test_export_over_2000_rows_filters_snapshot_and_formula_protection(self):
        page = self.logs()
        path = self.root / "complete.csv"
        count = operations.export_audit(
            2, path, "bulk_fixture", "2026-01-02", "2026-01-02", upper_id=page["upper_id"]
        )
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(count, 2505)
        self.assertEqual(len(rows), 2505)
        latest = self.root / "latest.csv"
        self.assertEqual(
            operations.export_audit(2, latest, "bulk_fixture", "2026-01-02", "2026-01-02"), 2505
        )
        self.assertEqual(len({row["id"] for row in rows}), 2505)
        self.assertEqual(
            [int(row["id"]) for row in rows], sorted((int(row["id"]) for row in rows), reverse=True)
        )
        by_object = {row["object_id"]: row for row in rows}
        for key in ("0", "1", "2", "3"):
            self.assertTrue(by_object[key]["reason"].startswith("'"))
        self.assertEqual(by_object["10"]["reason"], "entry 10")
        empty = self.root / "empty.csv"
        self.assertEqual(
            operations.export_audit(2, empty, "bulk_fixture", "2025-01-01", "2025-01-01"), 0
        )
        with closing(database.connect_database()) as con:
            self.assertTrue(
                con.execute(
                    "SELECT id FROM audit_logs WHERE action='export_audit' AND reason LIKE '导出 2505 条%'"
                ).fetchone()
            )

    def test_pages_do_not_shift_when_queries_generate_new_matching_audit_rows(self):
        first = self.logs()
        ids = [row["id"] for row in first["rows"]]
        self.logs(3)  # New matching rows with the same date must stay outside the frozen view.
        for page in range(2, 27):
            result = operations.audit_page(
                2, "bulk_fixture", "2026-01-02", "2026-01-02", page=page, upper_id=first["upper_id"]
            )
            self.assertEqual(result["total"], 2505)
            ids.extend(row["id"] for row in result["rows"])
        self.assertEqual(len(ids), 2505)
        self.assertEqual(len(set(ids)), 2505)
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(operations.query_audit(2, "bulk_fixture")), 2000)
        for args in ({"page": True}, {"page": 0}, {"page_size": 2001}, {"upper_id": -1}):
            with self.assertRaises(ValueError):
                operations.audit_page(2, **args)

    def test_export_failure_and_permission_checks_preserve_existing_destination(self):
        page = self.logs(4)
        path = self.root / "keep.csv"
        path.write_text("ORIGINAL", encoding="utf-8")
        for actor in (1, 3):
            with self.assertRaises(ValueError):
                operations.export_audit(actor, path)
        with patch("operations.csv.DictWriter.writerow", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                operations.export_audit(2, path)
        with patch("operations.audit", side_effect=sqlite3.OperationalError("audit failed")):
            with self.assertRaises(sqlite3.Error):
                operations.export_audit(2, path)
        self.assertEqual(path.read_text(encoding="utf-8"), "ORIGINAL")
        self.assertFalse(list(path.parent.glob("audit_*.tmp")))
        actual = csv.DictWriter.writerow
        revoked = []

        def write(writer, row):
            result = actual(writer, row)
            if row.get("action") == "bulk_fixture" and not revoked:
                with closing(database.connect_database()) as con:
                    with con:
                        con.execute(
                            "DELETE FROM account_roles WHERE account_id=2 AND role_id=(SELECT id FROM roles WHERE name='admin')"
                        )
                revoked.append(True)
            return result

        with patch("operations.csv.DictWriter.writerow", new=write):
            with self.assertRaises(ValueError):
                operations.export_audit(2, path, "bulk_fixture", upper_id=page["upper_id"])
        self.assertTrue(revoked)
        self.assertEqual(path.read_text(encoding="utf-8"), "ORIGINAL")

    def test_ui_pages_and_exports_all_applied_results(self):
        self.logs()
        root = tk.Tk()
        root.withdraw()
        configure_style(root)
        page = MaintenancePage(root, 2)
        try:
            page.keyword.set("bulk_fixture")
            page.refresh()
            total, upper = page.audit_total, page.audit_snapshot
            self.assertGreaterEqual(total, 2505)
            self.assertEqual(len(page.table.tree.get_children()), 100)
            page.keyword.set("unsubmitted keyword")
            page.turn_audit(1)
            self.assertEqual(page.audit_number, 2)
            self.assertEqual(page.audit_snapshot, upper)
            self.assertEqual(page.audit_keyword, "bulk_fixture")
            destination = self.root / "ui.csv"
            with patch("admin_ui.filedialog.asksaveasfilename", return_value=str(destination)):
                page.export()
            with destination.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), total)
            self.assertEqual(page.audit_number, 2)
            self.assertIn(str(total), page.export_status.cget("text"))
        finally:
            root.destroy()
            page = root = None
            gc.collect()
