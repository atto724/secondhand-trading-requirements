"""Admin cards, inline confirmation and permission-sensitive account lists."""

import gc
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import database
from admin_ui import AccountsPage, ReviewPage
from catalog import product_detail
from demo import demo_accounts, seed_demo
from governance import set_account_enabled, set_admin
from main import TradingApp
from governance import account_profile
from ui_common import configure_style


class AdminPresentationTests(unittest.TestCase):
    """Exercise isolated real services behind the redesigned controls."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.original = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.original)
        seed_demo(Path(self.folder.name))
        self.accounts = demo_accounts()
        self.admin = self.accounts["demo_admin"]
        self.root = tk.Tk()
        self.root.withdraw()
        configure_style(self.root)
        self.page = None
        self.addCleanup(self.cleanup_widgets)

    def cleanup_widgets(self):
        self.root.destroy()
        self.page = None
        self.root = None
        gc.collect()

    def test_review_groups_and_inline_rejection_require_reason(self):
        self.page = ReviewPage(self.root, self.admin)
        self.assertEqual(self.page.group, "pending_review")
        self.assertEqual(len(self.page.table.cards), 1)
        key = int(next(iter(self.page.table.cards)))
        labels = [button.cget("text") for button in self.page.table.cards[str(key)]["buttons"]]
        self.assertEqual(labels, ["查看详情", "审核通过", "驳回审核"])
        self.page.table.select(key)
        self.page.review(False)
        self.page.panel.submit()
        self.assertIn("原因", self.page.panel.error.cget("text"))
        self.assertEqual(product_detail(self.admin, key)["status"], "pending_review")
        self.page.panel.reason.insert("1.0", "请补充实际使用情况")
        self.page.panel.submit()
        self.assertEqual(product_detail(self.admin, key)["status"], "draft")
        self.assertEqual(self.page.table.keys(), ())
        self.assertFalse(
            any(isinstance(widget, tk.Toplevel) for widget in self.root.winfo_children())
        )

    def test_review_confirmation_keeps_target_and_rejects_stale_version(self):
        self.page = ReviewPage(self.root, self.admin)
        key = int(next(iter(self.page.table.cards)))
        self.page.table.select(key)
        self.page.review(True)
        with closing(database.connect_database()) as connection:
            with connection:
                connection.execute("UPDATE products SET version=version+1 WHERE id=?", (key,))
        self.page.panel.submit()
        self.assertTrue(self.page.panel.error.cget("text"))
        self.assertEqual(product_detail(self.admin, key)["status"], "pending_review")
        self.page.panel.close()
        self.page.refresh()
        self.page.table.select(key)
        self.page.review(True)
        self.page.panel.submit()
        self.assertEqual(product_detail(self.admin, key)["status"], "published")
        self.page.choose_group("published")
        self.assertEqual(len(self.page.table.cards), 16)

    def test_account_search_filters_and_frozen_target_for_inline_change(self):
        self.page = AccountsPage(self.root, self.admin)
        buyer = self.accounts["demo_buyer"]
        other = self.accounts["demo_other"]
        self.assertEqual(len(self.page.cards), 4)
        self.page.keyword.set("demo_buyer")
        self.page.render()
        self.assertEqual(set(self.page.cards), {buyer})
        self.page.open_change(buyer, "enabled", False)
        self.page.panel.submit()
        self.assertTrue(self.page.panel.error.cget("text"))
        self.page.keyword.set("demo_other")
        self.page.render()
        self.page.panel.reason.insert("1.0", "测试核实后暂停账号")
        self.page.panel.submit()
        with closing(database.connect_database()) as connection:
            states = dict(connection.execute("SELECT id,status FROM accounts"))
        self.assertEqual(states[buyer], "disabled")
        self.assertEqual(states[other], "active")
        self.page.keyword.set("")
        self.page.choose_group("disabled")
        self.assertEqual(set(self.page.cards), {buyer})
        self.assertEqual(
            [button.cget("text") for button in self.page.cards[buyer]["buttons"]], ["恢复账号"]
        )

    def test_last_admin_protection_and_restore_does_not_grant_roles(self):
        self.page = AccountsPage(self.root, self.admin)
        self.assertEqual(self.page.cards[self.admin]["buttons"], [])
        buyer = self.accounts["demo_buyer"]
        set_account_enabled(self.admin, buyer, False, "测试暂停")
        self.page.refresh()
        self.page.open_change(buyer, "enabled", True)
        self.page.panel.reason.insert("1.0", "核实后恢复")
        self.page.panel.submit()
        self.assertNotIn("admin", self.page.rows[buyer]["roles"])
        self.page.open_change(buyer, "admin", True)
        self.page.panel.reason.insert("1.0", "管理员明确授权")
        self.page.panel.submit()
        self.assertIn("admin", self.page.rows[buyer]["roles"])
        self.page.choose_group("admin")
        self.assertEqual(len(self.page.cards), 2)

    def test_plain_admin_navigation_and_reason_panel_visible_at_minimum_size(self):
        app = TradingApp(self.root)
        app.account_id = self.admin
        app.profile = account_profile(self.admin)
        app.show_home()
        target = next(
            key for key in app.notebook.tabs() if app.notebook.tab(key, "text") == "管理后台"
        )
        app.notebook.select(target)
        self.root.geometry("1080x740")
        self.root.deiconify()
        self.root.update()
        workspace = app.pages[target][0].winfo_children()[0]
        self.assertEqual(
            [workspace.notebook.tab(key, "text") for key in workspace.notebook.tabs()],
            ["审核与治理", "交易处理", "账号授权", "平台统计", "审计与备份"],
        )
        self.assertTrue(
            all(button.cget("relief") == "flat" for button, _ in workspace.nav_items.values())
        )
        holder = workspace.notebook.nametowidget(workspace.notebook.select())
        page = next(widget for widget in holder.winfo_children() if isinstance(widget, ReviewPage))
        key = int(next(iter(page.table.cards)))
        page.table.select(key)
        page.review(False)
        self.root.update()
        self.assertTrue(page.panel.reason.winfo_viewable())
        self.assertLessEqual(
            page.panel.winfo_rooty() + page.panel.winfo_height(),
            self.root.winfo_rooty() + self.root.winfo_height(),
        )
        self.root.withdraw()


if __name__ == "__main__":
    unittest.main()
