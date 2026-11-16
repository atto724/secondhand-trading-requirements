"""Category migration and user-photo gallery regression checks."""

import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

import database
from demo import SAMPLE_PRODUCTS, demo_accounts, seed_demo
from trades import reserve, cancel_reservation
from products import list_categories
from schema import CATEGORY_NAMES


class GalleryTests(unittest.TestCase):
    """Check repeatable initialization and preservation of existing records."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.original = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.original)
        self.root = Path(self.folder.name)
        database.DATABASE_PATH = self.root / "trading.db"
        database.initialize_database()

    def test_ten_categories_in_confirmed_order(self):
        self.assertEqual([row["name"] for row in list_categories()], list(CATEGORY_NAMES))
        database.initialize_database()
        self.assertEqual(len(list_categories()), 10)

    def test_legacy_rename_preserves_product_id_and_snapshot(self):
        with closing(database.connect_database()) as connection:
            with connection:
                category = connection.execute(
                    "SELECT id FROM categories WHERE name='数码电器'"
                ).fetchone()[0]
                connection.execute("UPDATE categories SET name='数码' WHERE id=?", (category,))
                connection.execute(
                    "INSERT INTO accounts(id,username,phone,password_hash) VALUES(1,'legacy','13800000000','fixture')"
                )
                product = connection.execute(
                    "INSERT INTO products(seller_id,category_id,title) VALUES(1,?,'旧草稿')",
                    (category,),
                ).lastrowid
                snapshot = json.dumps({"title": "旧草稿", "category_id": category})
                connection.execute(
                    "INSERT INTO reservations(product_id,buyer_id,status,snapshot,created_at) VALUES(?,1,'expired',?,'2026-11-01T00:00:00Z')",
                    (product, snapshot),
                )
        database.initialize_database()
        with closing(database.connect_database()) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT category_id FROM products WHERE id=?", (product,)
                ).fetchone()[0],
                category,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT name FROM categories WHERE id=?", (category,)
                ).fetchone()[0],
                "数码电器",
            )
            self.assertEqual(
                connection.execute("SELECT snapshot FROM reservations").fetchone()[0], snapshot
            )

    def test_duplicate_legacy_category_merges_without_losing_products(self):
        with closing(database.connect_database()) as connection:
            with connection:
                target = connection.execute(
                    "SELECT id FROM categories WHERE name='家居生活'"
                ).fetchone()[0]
                old = connection.execute(
                    "INSERT INTO categories(name) VALUES('生活用品')"
                ).lastrowid
                connection.execute(
                    "INSERT INTO accounts(id,username,phone,password_hash) VALUES(1,'legacy','13800000000','fixture')"
                )
                product = connection.execute(
                    "INSERT INTO products(seller_id,category_id) VALUES(1,?)", (old,)
                ).lastrowid
        database.initialize_database()
        with closing(database.connect_database()) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT category_id FROM products WHERE id=?", (product,)
                ).fetchone()[0],
                target,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT is_active FROM categories WHERE id=?", (old,)
                ).fetchone()[0],
                0,
            )
        self.assertEqual(len(list_categories()), 10)

    def test_gallery_images_classification_and_idempotency(self):
        seed_demo(self.root)
        with closing(database.connect_database()) as connection:
            public = connection.execute(
                "SELECT p.id,c.name FROM products p JOIN categories c ON c.id=p.category_id WHERE p.status='published'"
            ).fetchall()
            self.assertEqual(len(public), len(SAMPLE_PRODUCTS))
            self.assertEqual({row["name"] for row in public}, set(CATEGORY_NAMES))
            pictures = connection.execute("SELECT file_path FROM product_images").fetchall()
            self.assertEqual(len(pictures), 29)
            for row in pictures:
                path = database.DATABASE_PATH.parent / row["file_path"]
                self.assertTrue(path.is_file())
                with Image.open(path) as image:
                    image.verify()
            with connection:
                connection.execute(
                    "UPDATE products SET title='审查者修改后的名称' WHERE id=?", (public[0]["id"],)
                )
        seed_demo(self.root)
        with closing(database.connect_database()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 17)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM product_images").fetchone()[0], 29
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM products WHERE title='审查者修改后的名称'"
                ).fetchone()[0],
                1,
            )

    def test_photo_upgrade_defers_live_booking_and_preserves_snapshot(self):
        with patch("demo.supplement_images"):
            seed_demo(self.root)
        accounts = demo_accounts()
        with closing(database.connect_database()) as connection:
            product = connection.execute(
                "SELECT product_id FROM demo_items WHERE sample_key='handbag'"
            ).fetchone()[0]
        booking = reserve(accounts["demo_buyer"], product)
        with closing(database.connect_database()) as connection:
            snapshot = connection.execute(
                "SELECT snapshot FROM reservations WHERE id=?", (booking,)
            ).fetchone()[0]
        seed_demo(self.root)
        with closing(database.connect_database()) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM product_images WHERE product_id=?", (product,)
                ).fetchone()[0],
                1,
            )
        cancel_reservation(accounts["demo_buyer"], booking, "测试解除等待预约")
        seed_demo(self.root)
        with closing(database.connect_database()) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM product_images WHERE product_id=?", (product,)
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT snapshot FROM reservations WHERE id=?", (booking,)
                ).fetchone()[0],
                snapshot,
            )
            self.assertEqual(
                connection.execute("SELECT status FROM products WHERE id=?", (product,)).fetchone()[
                    0
                ],
                "published",
            )

    def test_interrupted_photo_marker_does_not_duplicate_images(self):
        seed_demo(self.root)
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute("DELETE FROM demo_photo_updates")
        seed_demo(self.root)
        with closing(database.connect_database()) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM product_images").fetchone()[0], 29
            )


if __name__ == "__main__":
    unittest.main()
