"""Inline create/edit form navigation, persistence and keyboard regressions."""

import gc
import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import database
from catalog import product_detail
from demo import demo_accounts, seed_demo
from editor_ui import ProductEditor
from governance import account_profile
from main import TradingApp


class InlineEditorTests(unittest.TestCase):
    """Check the real My Products entry points with an isolated gallery."""

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
        self.app.account_id = self.ids["demo_seller"]
        self.app.profile = account_profile(self.app.account_id)
        self.app.show_home()
        self.root.update()
        self.page = self.select("我的商品")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.root.destroy()
        self.page = self.app = self.root = None
        gc.collect()

    def select(self, label):
        tab = next(t for t in self.app.notebook.tabs() if self.app.notebook.tab(t, "text") == label)
        self.app.notebook.select(tab)
        self.root.update()
        return self.app.pages[tab][0].winfo_children()[0]

    def editor(self):
        return next(
            child for child in self.page.winfo_children() if isinstance(child, ProductEditor)
        )

    def fill(self, editor, title):
        editor.variables["title"].set(title)
        editor.variables["category"].set(next(iter(editor.categories)))
        editor.variables["price"].set("12.50")
        editor.description.insert("1.0", "商品描述，实际状态以沟通为准。")

    def test_create_and_edit_open_inline_and_survive_navigation(self):
        self.page.set_filter("draft")
        self.page.create()
        editor = self.editor()
        self.assertFalse(isinstance(editor, tk.Toplevel))
        self.assertTrue(editor.place_info())
        editor.variables["title"].set("尚未保存的商品")
        self.select("浏览商品")
        self.assertIs(self.select("我的商品"), self.page)
        self.assertTrue(editor.winfo_exists())
        self.assertEqual(editor.variables["title"].get(), "尚未保存的商品")
        editor.close()
        self.assertEqual(self.page.filter_key, "draft")
        key = next(row["id"] for row in self.page.rows.values() if row["status"] == "draft")
        self.page.table.select(key)
        self.page.edit()
        editing = self.editor()
        self.assertEqual(editing.product_id, key)
        self.assertFalse(
            any(isinstance(child, tk.Toplevel) for child in self.root.winfo_children())
        )
        editing.close()

    def test_required_fields_images_and_save_keep_list_state(self):
        self.page.set_filter("draft")
        count = len(self.page.rows)
        self.page.create()
        editor = self.editor()
        with patch("editor_ui.messagebox.showwarning") as warning:
            editor.save(False)
            warning.assert_called_once()
        self.assertTrue(editor.winfo_exists())
        self.assertEqual(len(self.page.rows), count)
        self.fill(editor, "页内创建验收")
        assets = Path(__file__).resolve().parents[1] / "demo_assets"
        editor.sources = [assets / "laptop.jpg", assets / "textbook.jpg"]
        editor.refresh_images()
        editor.save(False)
        self.assertFalse(editor.winfo_exists())
        self.assertEqual(self.page.filter_key, "draft")
        row = next(row for row in self.page.rows.values() if row["title"] == "页内创建验收")
        data = product_detail(self.app.account_id, row["id"])
        self.assertEqual(data["price_cents"], 1250)
        self.assertEqual(len(data["images"]), 2)
        self.page.table.select(row["id"])
        self.page.edit()
        editing = self.editor()
        editing.description.insert("end", " 修改后的说明。")
        editing.save(True)
        self.assertFalse(editing.winfo_exists())
        self.assertEqual(product_detail(self.app.account_id, row["id"])["status"], "pending_review")
        self.assertEqual(self.page.filter_key, "draft")

    def test_local_keyboard_shortcuts_and_minimum_window_footer(self):
        self.page.create()
        editor = self.editor()
        self.fill(editor, "键盘保存")
        self.root.geometry("1080x740")
        self.root.deiconify()
        self.root.update()
        save_buttons = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.ttk.Button) and child.cget("text") in (
                    "保存草稿",
                    "提交审核",
                    "取消",
                ):
                    save_buttons.append(child)
                walk(child)

        walk(editor)
        self.assertEqual(len(save_buttons), 3)
        for button in save_buttons:
            self.assertTrue(button.winfo_viewable())
            self.assertLessEqual(
                button.winfo_rooty() + button.winfo_height(),
                self.root.winfo_rooty() + self.root.winfo_height(),
            )
        editor.description.focus_force()
        self.root.update()
        with patch.object(editor, "save") as save:
            editor.description.event_generate("<Control-Return>")
            self.root.update()
            save.assert_called_once_with(False)
        editor.widgets["title"].focus_force()
        self.root.update()
        editor.widgets["title"].event_generate("<Escape>")
        self.root.update()
        self.assertFalse(editor.winfo_exists())
        self.assertEqual(self.root.bind("<Control-Return>"), "")
        self.root.withdraw()
