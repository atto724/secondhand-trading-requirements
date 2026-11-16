"""Native Tk regression checks for in-place navigation and multi-image details."""

import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import database
from demo import demo_accounts, seed_demo
from market_ui import CatalogPage, ProductDetail
from ui_common import configure_style


class DetailPageTests(unittest.TestCase):
    """Exercise actual widgets without authenticating through a UI dialog."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.original = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.original)
        seed_demo(Path(self.folder.name))
        self.actor = demo_accounts()["demo_buyer"]
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        configure_style(self.root)
        self.root.geometry("1080x740")
        self.page = CatalogPage(self.root, self.actor)
        self.page.pack(fill="both", expand=True)
        with closing(database.connect_database()) as connection:
            self.product = connection.execute(
                "SELECT product_id FROM demo_items WHERE sample_key='handbag'"
            ).fetchone()[0]

    def test_return_preserves_list_state_without_secondary_window(self):
        self.page.keyword.set("手提包")
        self.page.refresh()
        self.root.update_idletasks()
        previous_cards = tuple(self.page.cards.winfo_children())
        view = ProductDetail(self.page, self.actor, self.product)
        self.root.update_idletasks()
        self.assertEqual(view.winfo_toplevel(), self.root)
        self.assertEqual(view.winfo_manager(), "place")
        view.destroy()
        self.assertEqual(self.page.keyword.get(), "手提包")
        self.assertEqual(tuple(self.page.cards.winfo_children()), previous_cards)
        self.assertFalse(
            any(isinstance(widget, tk.Toplevel) for widget in self.root.winfo_children())
        )

    def test_gallery_boundaries_and_real_thumbnail_switching(self):
        view = ProductDetail(self.page, self.actor, self.product)
        self.assertEqual(len(view.buttons), 3)
        first = str(view.large.cget("image"))
        view.buttons[1].invoke()
        self.assertEqual(view.index, 1)
        self.assertNotEqual(str(view.large.cget("image")), first)
        view.select_image(99)
        self.assertEqual(view.index, 2)
        self.assertTrue(view.next_button.instate(["disabled"]))
        view.select_image(-1)
        self.assertEqual(view.index, 0)
        self.assertTrue(view.previous.instate(["disabled"]))


if __name__ == "__main__":
    unittest.main()
