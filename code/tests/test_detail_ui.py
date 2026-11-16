"""Native Tk regression checks for in-place navigation and multi-image details."""

import gc
import tkinter as tk
from tkinter import ttk
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import database
from demo import demo_accounts, seed_demo
from market_ui import CatalogPage, ProductDetail
from seller_ui import ChatPanel, SellerPage, InboxPage
from community import send_direct_message, inbox, seller_profile
from unittest.mock import patch
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
        self.addCleanup(self.cleanup_widgets)
        configure_style(self.root)
        self.root.geometry("1080x740")
        self.page = CatalogPage(self.root, self.actor)
        self.page.pack(fill="both", expand=True)
        with closing(database.connect_database()) as connection:
            self.product = connection.execute(
                "SELECT product_id FROM demo_items WHERE sample_key='handbag'"
            ).fetchone()[0]

    def cleanup_widgets(self):
        """Release Tcl images and variables on the UI thread before threaded tests."""
        self.root.destroy()
        self.page = None
        self.root = None
        gc.collect()

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

    def test_seller_box_opens_inline_store_with_visible_chat(self):
        seller = demo_accounts()["demo_seller"]
        send_direct_message(seller, self.actor, "询问商品")
        detail = ProductDetail(self.page, self.actor, self.product)

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        button = next(
            widget
            for widget in descendants(detail)
            if isinstance(widget, ttk.Button) and widget.cget("text") == "进入卖家主页 →"
        )
        button.invoke()
        store = next(widget for widget in detail.winfo_children() if isinstance(widget, SellerPage))
        self.root.update()
        self.assertEqual(store.winfo_toplevel(), self.root)
        self.assertEqual(inbox(self.actor)[0]["unread"], 0)
        self.assertEqual(len(store.table.tree.get_children()), 8)
        store.table.tree.selection_set(store.table.tree.get_children()[0])
        store.open_product()
        child = next(
            widget for widget in store.winfo_children() if isinstance(widget, ProductDetail)
        )
        child.destroy()
        store.destroy()
        self.assertTrue(detail.winfo_exists())

    def test_chat_send_failure_keeps_draft_and_reply_is_available_in_inbox(self):
        seller = demo_accounts()["demo_seller"]
        panel = ChatPanel(self.page, self.actor, seller)
        panel.editor.insert("1.0", "想了解这件商品")
        with patch("seller_ui.send_direct_message", side_effect=ValueError("保存失败")):
            with self.assertRaises(ValueError):
                panel.send_message()
        self.assertEqual(panel.editor.get("1.0", "end-1c"), "想了解这件商品")
        panel.send_message()
        self.assertEqual(panel.editor.get("1.0", "end-1c"), "")
        messages = InboxPage(self.page, seller)
        messages.table.tree.selection_set(str(self.actor))
        messages.open_chat()
        reply = next(
            widget for widget in messages.slot.winfo_children() if isinstance(widget, ChatPanel)
        )
        reply.editor.insert("1.0", "可以的，请问想了解什么？")
        reply.send_message()
        panel.refresh()
        self.assertIn("请问想了解", panel.history.get("1.0", "end"))

    def test_owner_profile_can_be_saved_without_a_product(self):
        owner = SellerPage(self.page, self.actor, self.actor)
        owner.fields[0].insert(0, "买家的昵称")
        owner.save_profile()
        self.assertEqual(seller_profile(self.actor, self.actor)["nickname"], "买家的昵称")

    def test_private_composer_visible_at_minimum_window_size(self):
        seller = demo_accounts()["demo_seller"]
        store = SellerPage(self.page, self.actor, seller)
        self.root.deiconify()
        self.root.update()
        for widget in (store.chat.editor, store.chat.send_button):
            self.assertTrue(widget.winfo_viewable())
            self.assertGreater(widget.winfo_height(), 15)
            self.assertLessEqual(
                widget.winfo_rooty() + widget.winfo_height(),
                self.root.winfo_rooty() + self.root.winfo_height(),
            )
        self.root.withdraw()

    def test_all_accounts_have_default_avatar_and_owner_can_replace(self):
        owner = SellerPage(self.page, self.actor, self.actor)
        self.assertTrue(owner.avatar.cget("image"))
        assets = Path(__file__).resolve().parent.parent / "demo_assets"
        with patch(
            "seller_ui.filedialog.askopenfilename", return_value=str(assets / "avatar_1.jpg")
        ):
            owner.choose_avatar()
        self.assertTrue(seller_profile(self.actor, self.actor)["avatar_path"])


if __name__ == "__main__":
    unittest.main()
