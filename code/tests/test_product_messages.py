"""Product-message persistence and actionable empty-state regressions."""

import gc
import json
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import database
from catalog import product_detail, search_products
from community import conversation, inbox, send_direct_message, send_product_message
from demo import demo_accounts, seed_demo
from governance import account_profile
from main import TradingApp
from market_ui import CatalogPage, MyProductsPage, ProductDetail
from message_ui import MessageCenter
from seller_ui import ChatPage, ProductMessageCard
from trades_ui import ReservationsPage
from ui_common import configure_style


class ProductMessageTests(unittest.TestCase):
    """Use isolated migrated data and actual message/visibility services."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.original = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.original)
        seed_demo(Path(self.folder.name))
        self.accounts = demo_accounts()
        self.buyer = self.accounts["demo_buyer"]
        self.seller = self.accounts["demo_seller"]
        self.other = self.accounts["demo_other"]
        self.product = search_products(self.buyer)[0][0]

    def root(self):
        root = tk.Tk()
        root.withdraw()
        configure_style(root)

        def cleanup():
            root.destroy()
            gc.collect()

        self.addCleanup(cleanup)
        return root

    def test_snapshot_survives_product_change_and_is_participant_scoped(self):
        mid = send_product_message(self.buyer, self.seller, self.product["id"])
        original = conversation(self.seller, self.buyer)["rows"][-1]
        snapshot = json.loads(original["product_snapshot"])
        self.assertEqual(snapshot["title"], self.product["title"])
        self.assertEqual(snapshot["price_cents"], self.product["price_cents"])
        self.assertEqual(set(snapshot), {"id", "title", "price_cents", "image"})
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute(
                    "UPDATE products SET title='changed',status='delisted' WHERE id=?",
                    (self.product["id"],),
                )
        self.assertEqual(
            conversation(self.buyer, self.seller)["rows"][-1]["product_snapshot"],
            original["product_snapshot"],
        )
        self.assertFalse(conversation(self.other, self.seller)["rows"])
        self.assertTrue(inbox(self.seller)[0]["content"].startswith("[商品]"))
        self.assertEqual(mid, original["id"])
        with self.assertRaises(ValueError):
            product_detail(self.buyer, self.product["id"])

    def test_reject_wrong_seller_private_product_and_disabled_sender(self):
        with self.assertRaises(ValueError):
            send_product_message(self.buyer, self.other, self.product["id"])
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute(
                    "UPDATE products SET status='draft' WHERE id=?", (self.product["id"],)
                )
        with self.assertRaises(ValueError):
            send_product_message(self.buyer, self.seller, self.product["id"])
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute(
                    "UPDATE accounts SET status='disabled' WHERE id=?", (self.buyer,)
                )
        with self.assertRaises(ValueError):
            send_product_message(self.buyer, self.seller, self.product["id"])
        self.assertFalse(conversation(self.seller, self.buyer)["rows"])

    def test_migration_preserves_plain_text_and_is_repeatable(self):
        send_direct_message(self.buyer, self.seller, "ordinary message")
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute("ALTER TABLE direct_messages DROP COLUMN product_snapshot")
        database.initialize_database()
        database.initialize_database()
        row = conversation(self.seller, self.buyer)["rows"][-1]
        self.assertEqual(row["content"], "ordinary message")
        self.assertIsNone(row["product_snapshot"])

    def test_explicit_send_card_render_click_and_text_draft(self):
        root = self.root()
        page = ChatPage(root, self.buyer, self.seller, product_id=self.product["id"])
        self.assertFalse(conversation(self.seller, self.buyer)["rows"])
        page.chat.editor.insert("1.0", "unsent draft")
        page.product_button.invoke()
        self.assertEqual(page.chat.editor.get("1.0", "end-1c"), "unsent draft")
        bubble = list(page.chat.history.bubbles.values())[-1]
        self.assertIsInstance(bubble, ProductMessageCard)
        root.update()
        bubble.configure(wraplength=180)
        page.open_product_card(self.product["id"])
        details = [child for child in page.winfo_children() if isinstance(child, ProductDetail)]
        self.assertEqual(len(details), 1)
        details[0].destroy()
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute(
                    "UPDATE products SET status='delisted' WHERE id=?", (self.product["id"],)
                )
        with patch("ui_common.messagebox.showerror") as error:
            page.open_product_card(self.product["id"])
            error.assert_called_once()
        self.assertTrue(page.winfo_exists())
        page.destroy()
        gc.collect()

    def test_empty_state_actions_restore_filters_and_offer_navigation(self):
        root = self.root()
        catalog = CatalogPage(root, self.buyer)
        catalog.keyword.set("no-such-product-xyz")
        catalog.query()
        self.assertEqual(catalog.total, 0)
        catalog.reset_filters()
        self.assertGreater(catalog.total, 0)
        catalog.destroy()
        # Buyer has no products, reservations or messages in this fixture.
        pages = [
            MyProductsPage(root, self.other),
            ReservationsPage(root, self.other),
            MessageCenter(root, self.other),
        ]

        def labels(widget):
            result = []
            for child in widget.winfo_children():
                try:
                    result.append(str(child.cget("text")))
                except tk.TclError:
                    pass
                result.extend(labels(child))
            return result

        self.assertIn("新建第一件商品", labels(pages[0]))
        self.assertIn("去浏览商品", labels(pages[1]))
        self.assertIn("去浏览商品", labels(pages[2]))
        for page in pages:
            page.destroy()
        app = TradingApp(root)
        app.account_id = self.other
        app.profile = account_profile(self.other)
        app.show_home()
        from ui_common import navigate_to

        navigate_to(app.pages[app.notebook.tabs()[1]][0], "消息中心")
        self.assertEqual(app.notebook.tab(app.notebook.select(), "text"), "消息中心")
        pages.clear()
        gc.collect()
