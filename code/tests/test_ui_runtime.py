"""UI responsiveness, cached rendering and high-resolution wheel regressions."""

import gc
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
import database
from demo import seed_demo, demo_accounts
from main import TradingApp
from market_ui import CatalogPage
from ui_common import configure_style, thumbnail, ProductRows
from ui_runtime import BackgroundJob, cached_photo


class RuntimeTests(unittest.TestCase):
    """Use native Tk events and controlled background work, not timing guesses."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.original = database.DATABASE_PATH
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, database, "DATABASE_PATH", self.original)
        seed_demo(Path(self.folder.name))
        self.ids = demo_accounts()
        self.root = tk.Tk()
        self.root.geometry("1080x740")
        configure_style(self.root)
        self.widgets = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.root is not None:
            self.root.destroy()
        self.widgets.clear()
        self.root = None
        gc.collect()

    def until(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("UI condition did not complete")

    def test_image_cache_reuses_pixels_invalidates_changes_and_is_bounded(self):
        path = Path(self.folder.name) / "test.png"
        Image.new("RGB", (180, 90), "red").save(path)
        with patch("ui_runtime.Image.open", wraps=Image.open) as opened:
            first = thumbnail(self.root, path, (60, 60))
            self.assertIs(first, thumbnail(self.root, path, (60, 60)))
            self.assertEqual(opened.call_count, 1)
        Image.new("RGB", (200, 100), "blue").save(path)
        self.assertIsNot(first, thumbnail(self.root, path, (60, 60)))
        for size in range(10, 145):
            cached_photo(self.root, path, (size, size))
        self.assertLessEqual(len(self.root.photo_cache), 128)
        other = tk.Tk()
        other.withdraw()
        self.assertIsNot(first, thumbnail(other, path, (60, 60)))
        other.destroy()

    def test_touchpad_over_product_image_and_button_scrolls_only_its_canvas(self):
        page = CatalogPage(self.root, self.ids["demo_buyer"])
        page.pack(fill="both", expand=True)
        self.widgets.append(page)
        self.root.update()
        card = page.cards.winfo_children()[0]
        image, button = card.winfo_children()[0], card.winfo_children()[-1]
        before = page.canvas.yview()[0]
        image.event_generate("<MouseWheel>", delta=-15, x=10, y=10)
        self.until(lambda: page.canvas.yview()[0] > before)
        before = page.canvas.yview()[0]
        button.event_generate("<MouseWheel>", delta=-15, x=10, y=10)
        self.until(lambda: page.canvas.yview()[0] > before)
        # A fractional touchpad gesture must not be discarded as int(delta/120)==0.
        before = page.canvas.yview()[0]
        for _ in range(10):
            image.event_generate("<MouseWheel>", delta=-1, x=10, y=10)
        self.until(lambda: page.canvas.yview()[0] > before)

    def test_wheel_uses_hover_when_keyboard_focus_is_in_header(self):
        page = CatalogPage(self.root, self.ids["demo_buyer"])
        page.pack(fill="both", expand=True)
        self.widgets.append(page)
        self.root.update()
        image = page.cards.winfo_children()[0].winfo_children()[0]
        before = page.canvas.yview()[0]
        event = SimpleNamespace(
            widget=self.root,
            delta=-15,
            x_root=image.winfo_rootx() + 10,
            y_root=image.winfo_rooty() + 10,
        )
        self.assertEqual(self.root.scroll_router.route(event), "break")
        self.until(lambda: page.canvas.yview()[0] > before)

    def test_wheel_coalesces_and_preserves_native_editor_scrolling(self):
        canvas = tk.Canvas(
            self.root, yscrollcommand=lambda *args: None, scrollregion=(0, 0, 100, 4000)
        )
        canvas.pack()
        self.root.update()
        router = self.root.scroll_router
        router.enqueue(canvas, 3)
        timer = canvas.wheel_timer
        for _ in range(20):
            router.enqueue(canvas, 3)
        self.assertEqual(timer, canvas.wheel_timer)
        self.until(lambda: canvas.wheel_timer is None)
        self.assertGreater(canvas.yview()[0], 0)
        text = tk.Text(canvas, height=3)
        text.insert("1.0", "line\n" * 100)
        self.assertIsNone(router.route(SimpleNamespace(widget=text, delta=-15)))
        router.enqueue(canvas, 3)
        canvas.destroy()
        self.root.update()

    def test_unchanged_card_refresh_keeps_existing_widgets(self):
        rows = ProductRows(self.root)
        rows.pack(fill="both", expand=True)
        data = [{"id": 1, "title": "product", "subtitle": "same", "status": "草稿", "actions": []}]
        rows.fill(data)
        original = rows.cards["1"]["frame"]
        rows.fill(data)
        self.assertIs(rows.cards["1"]["frame"], original)
        rows.fill([{**data[0], "title": "changed"}])
        self.assertFalse(original.winfo_exists())

    def test_background_work_keeps_ui_alive_and_delivers_on_main_thread(self):
        job = BackgroundJob(self.root)
        released = threading.Event()
        entered = threading.Event()
        delivered = []
        worker_ids = []

        def work():
            worker_ids.append(threading.get_ident())
            entered.set()
            released.wait(5)
            return 42

        self.assertTrue(
            job.run(work, lambda value: delivered.append((value, threading.get_ident())), self.fail)
        )
        self.assertTrue(entered.wait(2))
        self.assertFalse(job.run(work, self.fail, self.fail))
        heartbeat = []
        self.root.after(0, lambda: heartbeat.append(True))
        self.until(lambda: bool(heartbeat))
        self.assertFalse(delivered)
        released.set()
        self.until(lambda: bool(delivered))
        self.assertEqual(delivered, [(42, threading.get_ident())])
        self.assertNotEqual(worker_ids[0], threading.get_ident())
        self.assertFalse(job.busy)
        closed = tk.Tk()
        closed.withdraw()
        second = BackgroundJob(closed)
        release = threading.Event()
        finished = threading.Event()

        def slow():
            release.wait(5)
            finished.set()

        second.run(slow, self.fail, self.fail)
        closed.destroy()
        release.set()
        self.assertTrue(finished.wait(2))
        self.assertTrue(second.closed)

    def test_async_login_ignores_duplicates_and_stale_session_result(self):
        self.root.withdraw()
        app = TradingApp(self.root)
        self.widgets.append(app)
        release = threading.Event()
        started = threading.Event()

        def auth(_username, _password):
            started.set()
            release.wait(5)
            return self.ids["demo_buyer"]

        with patch("main.authenticate", side_effect=auth) as authenticate:
            app.username.set("demo_buyer")
            app.password.set("DemoPass123!")
            app.login()
            self.assertTrue(started.wait(2))
            self.assertEqual(app.password.get(), "")
            app.login()
            self.assertEqual(authenticate.call_count, 1)
            self.assertIsNone(app.account_id)
            app.logout()
            release.set()
            self.until(lambda: not app.login_job.busy)
            self.assertIsNone(app.account_id)
            app.username.set("demo_buyer")
            app.password.set("DemoPass123!")
            app.login()
            self.until(lambda: app.account_id is not None)
            self.assertEqual(app.account_id, self.ids["demo_buyer"])
        app.logout()
        with patch("main.authenticate", side_effect=ValueError("bad password")), patch(
            "main.messagebox.showerror"
        ) as error:
            app.username.set("demo_buyer")
            app.password.set("wrong")
            app.login()
            self.until(lambda: not app.login_job.busy)
            self.assertEqual(str(app.login_button.cget("state")), "normal")
            self.assertIsNone(app.account_id)
            error.assert_called_once()

    def test_maintenance_uses_one_background_job(self):
        self.root.withdraw()
        app = TradingApp(self.root)
        self.widgets.append(app)
        release = threading.Event()
        called = threading.Event()
        threads = []

        def maintenance():
            threads.append(threading.get_ident())
            called.set()
            release.wait(5)

        with patch("main.run_timeouts", side_effect=maintenance):
            app.maintenance_tick()
            self.assertTrue(called.wait(2))
            app.maintenance_tick()
            self.assertEqual(len(threads), 1)
            self.assertNotEqual(threads[0], threading.get_ident())
            release.set()
            self.until(lambda: not app.maintenance_job.busy)
