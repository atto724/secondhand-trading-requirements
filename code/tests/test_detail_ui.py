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
from seller_ui import ChatPage, ChatPanel, SellerPage, InboxPage
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

    def test_seller_box_opens_profile_without_reading_private_messages(self):
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
        self.assertEqual(inbox(self.actor)[0]["unread"], 1)
        self.assertFalse(any(isinstance(w, ChatPanel) for w in store.winfo_children()))
        self.assertFalse(hasattr(store, "chat"))
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
        self.assertTrue(
            any("请问想了解" in bubble.cget("text") for bubble in panel.history.bubbles.values())
        )

    def test_owner_profile_can_be_saved_without_a_product(self):
        owner = SellerPage(self.page, self.actor, self.actor)
        owner.fields[0].insert(0, "买家的昵称")
        owner.save_profile()
        self.assertEqual(seller_profile(self.actor, self.actor)["nickname"], "买家的昵称")

    def test_private_composer_visible_at_minimum_window_size(self):
        seller = demo_accounts()["demo_seller"]
        store = ChatPage(self.page, self.actor, seller)
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

    def test_sent_and_received_bubbles_are_visible_and_align_by_sender(self):
        seller = demo_accounts()["demo_seller"]
        outgoing = send_direct_message(self.actor, seller, "我发出的内容\n换行也保留")
        incoming = send_direct_message(seller, self.actor, "卖家的回复")
        panel = ChatPanel(self.page, self.actor, seller)
        panel.pack(fill="both", expand=True)
        self.root.deiconify()
        self.root.update()
        mine = panel.history.bubbles[outgoing]
        theirs = panel.history.bubbles[incoming]
        self.assertTrue(mine.winfo_viewable())
        self.assertTrue(theirs.winfo_viewable())
        self.assertEqual(mine.cget("text"), "我发出的内容\n换行也保留")
        self.assertEqual(mine.cget("background"), "#95ec69")
        self.assertEqual(mine.master.pack_info()["side"], "right")
        self.assertEqual(theirs.master.pack_info()["side"], "left")
        self.assertEqual(mine.winfo_parent(), str(mine.master))
        self.assertNotEqual(panel.status.cget("text"), "已发送")
        self.root.withdraw()

    def test_chat_long_text_wraps_and_refresh_keeps_one_bubble_per_message(self):
        seller = demo_accounts()["demo_seller"]
        panel = ChatPanel(self.page, self.actor, seller)
        panel.pack(fill="both", expand=True)
        self.root.deiconify()
        panel.editor.insert("1.0", "长消息" * 300)
        panel.send_message()
        self.root.update()
        self.assertEqual(len(panel.history.bubbles), 1)
        bubble = next(iter(panel.history.bubbles.values()))
        self.assertLessEqual(bubble.winfo_width(), panel.history.canvas.winfo_width())
        panel.refresh()
        self.root.update()
        self.assertEqual(len(panel.history.bubbles), 1)
        self.assertGreater(panel.history.canvas.yview()[1], 0.99)
        self.root.withdraw()

    def test_private_message_button_opens_only_conversation_and_returns_to_detail(self):
        detail = ProductDetail(self.page, self.actor, self.product)

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        button = next(
            w
            for w in descendants(detail)
            if isinstance(w, ttk.Button) and w.cget("text") == "私信卖家 / 咨询商品"
        )
        button.invoke()
        chat = next(w for w in detail.winfo_children() if isinstance(w, ChatPage))
        self.assertTrue(any(isinstance(w, ChatPanel) for w in chat.winfo_children()))
        self.assertFalse(any(isinstance(w, SellerPage) for w in descendants(chat)))
        self.assertEqual(chat.winfo_toplevel(), self.root)
        chat.chat.editor.insert("1.0", "独立聊天页咨询")
        chat.chat.send_message()
        self.assertTrue(chat.chat.history.bubbles)
        chat.destroy()
        self.assertTrue(detail.winfo_exists())


if __name__ == "__main__":
    unittest.main()
