"""Session navigation, draft isolation and refresh-state regressions."""

import gc
import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import database
from catalog import search_products, delist_product
from demo import demo_accounts, seed_demo
from governance import account_profile, set_account_enabled, set_admin
from main import TradingApp
from market_ui import ProductDetail
from seller_ui import ChatPage


class PageStateTests(unittest.TestCase):
    """Exercise real navigation with isolated accounts and database state."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.original = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.original)
        seed_demo(Path(self.folder.name))
        self.ids = demo_accounts()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = TradingApp(self.root)
        self.actor = self.ids["demo_buyer"]
        self.login(self.actor)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.root.destroy()
        self.app = None
        self.root = None
        gc.collect()

    def login(self, actor):
        self.app.account_id = actor
        self.app.profile = account_profile(actor)
        self.app.show_home()
        self.root.update()

    def select(self, label):
        tab = next(t for t in self.app.notebook.tabs() if self.app.notebook.tab(t, "text") == label)
        self.app.notebook.select(tab)
        self.root.update()
        return self.app.pages[tab][0].winfo_children()[0]

    def test_search_pagination_overlay_and_scroll_survive_navigation(self):
        catalog = self.select("浏览商品")
        catalog.page = 2
        catalog.refresh()
        catalog.keyword.set("尚未提交的搜索词")
        catalog.minimum.set("尚未输入完")
        item = search_products(self.actor)[0][0]
        detail = ProductDetail(catalog, self.actor, item["id"])
        self.select("我的预约")
        restored = self.select("浏览商品")
        self.assertIs(restored, catalog)
        self.assertEqual(restored.page, 2)
        self.assertEqual(restored.keyword.get(), "尚未提交的搜索词")
        self.assertEqual(restored.minimum.get(), "尚未输入完")
        self.assertTrue(detail.winfo_exists())
        detail.destroy()
        self.root.deiconify()
        mine = self.select("我的商品")
        self.root.update()
        mine.table.canvas.configure(scrollregion=(0, 0, 100, 4000))
        mine.table.canvas.yview_moveto(0.5)
        # Avoid synthetic content being replaced; verify the lifecycle restores position.
        with patch.object(mine, "on_resume"):
            before = mine.table.canvas.yview()[0]
            self.select("我的统计")
            self.assertIs(self.select("我的商品"), mine)
            self.assertAlmostEqual(mine.table.canvas.yview()[0], before, places=2)
        self.root.withdraw()

    def test_chat_draft_survives_tabs_back_and_isolated_peers(self):
        messages = self.select("消息中心")
        chat = ChatPage(messages, self.actor, self.ids["demo_seller"])
        chat.chat.editor.insert("1.0", "未发送的文字\n第二行")
        self.root.update()
        self.select("我的商品")
        self.select("消息中心")
        self.assertTrue(chat.winfo_exists())
        self.assertEqual(chat.chat.editor.get("1.0", "end-1c"), "未发送的文字\n第二行")
        chat.go_back()
        other = ChatPage(messages, self.actor, self.ids["demo_other"])
        self.assertEqual(other.chat.editor.get("1.0", "end-1c"), "")
        other.go_back()
        restored = ChatPage(messages, self.actor, self.ids["demo_seller"])
        self.assertEqual(restored.chat.editor.get("1.0", "end-1c"), "未发送的文字\n第二行")
        restored.chat.send_message()
        self.root.update()
        restored.go_back()
        again = ChatPage(messages, self.actor, self.ids["demo_seller"])
        self.assertEqual(again.chat.editor.get("1.0", "end-1c"), "")
        second_page = self.select("我的商品")
        duplicate = ChatPage(second_page, self.actor, self.ids["demo_seller"])
        duplicate.chat.editor.insert("1.0", "从另一入口继续编辑")
        self.root.update()
        self.select("消息中心")
        self.assertEqual(again.chat.editor.get("1.0", "end-1c"), "从另一入口继续编辑")
        self.select("我的商品")
        duplicate.chat.send_message()
        self.root.update()
        self.select("消息中心")
        self.assertEqual(again.chat.editor.get("1.0", "end-1c"), "")
        again.destroy()

    def test_lists_refresh_live_data_without_resetting_filter(self):
        self.app.logout()
        self.login(self.ids["demo_seller"])
        mine = self.select("我的商品")
        mine.set_filter("published")
        item = next(row for row in mine.rows.values() if row["status"] == "published")
        self.select("消息中心")
        delist_product(self.ids["demo_seller"], item["id"])
        self.assertIs(self.select("我的商品"), mine)
        self.assertEqual(mine.filter_key, "published")
        self.assertEqual(mine.rows[item["id"]]["status"], "delisted")
        self.assertNotIn(str(item["id"]), mine.table.cards)

    def test_admin_subpages_preserve_inputs_and_revoke_clears_cache(self):
        self.app.logout()
        self.login(self.ids["demo_admin"])
        workspace = self.select("管理后台")
        tabs = workspace.notebook

        def sub(label):
            tab = next(t for t in tabs.tabs() if tabs.tab(t, "text") == label)
            tabs.select(tab)
            self.root.update()
            return tabs.nametowidget(tab).winfo_children()[0]

        accounts = sub("账号授权")
        accounts.keyword.set("buyer")
        accounts.render()
        sub("平台统计")
        self.assertIs(sub("账号授权"), accounts)
        self.assertEqual(accounts.keyword.get(), "buyer")
        self.select("我的商品")
        self.assertIs(self.select("管理后台"), workspace)
        set_admin(self.ids["demo_admin"], self.ids["demo_other"], True, "测试授权")
        set_admin(self.ids["demo_other"], self.ids["demo_admin"], False, "测试撤销")
        self.select("浏览商品")
        self.assertFalse(workspace.winfo_exists())
        self.assertFalse(
            any(self.app.notebook.tab(t, "text") == "管理后台" for t in self.app.notebook.tabs())
        )

    def test_logout_switch_and_disabled_account_clear_drafts_and_pages(self):
        page = self.select("消息中心")
        chat = ChatPage(page, self.actor, self.ids["demo_seller"])
        chat.chat.editor.insert("1.0", "秘密草稿")
        self.root.update()
        self.app.switch_account()
        self.assertEqual(self.root.chat_drafts, {})
        self.assertFalse(chat.winfo_exists())
        self.login(self.ids["demo_other"])
        page = self.select("消息中心")
        chat = ChatPage(page, self.ids["demo_other"], self.ids["demo_seller"])
        self.assertEqual(chat.chat.editor.get("1.0", "end-1c"), "")
        set_account_enabled(self.ids["demo_admin"], self.ids["demo_other"], False, "测试禁用")
        with patch("main.messagebox.showwarning"):
            self.app.open_tab()
        self.assertIsNone(self.app.account_id)
        self.assertEqual(self.root.chat_drafts, {})
        self.assertFalse(chat.winfo_exists())
