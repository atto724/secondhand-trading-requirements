"""Desktop startup, authentication and component navigation."""

import argparse
import logging
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import messagebox, ttk

import database
from accounts import authenticate
from admin_ui import AccountsPage, MaintenancePage, MessagesPage, ReportsPage, ReviewPage
from governance import account_profile
from market_ui import CatalogPage, MyProductsPage, ProductDetail
from operations import backup_status, create_backup
from registration_ui import RegistrationWindow
from seller_ui import InboxPage, SellerPage
from trades import run_timeouts
from trades_ui import ReservationsPage
from ui_common import configure_style, guarded


class TradingApp:
    """Keep UI login state separate from business authorization checks."""

    def __init__(self, root):
        self.root = root
        self.account_id = None
        self.profile = None
        self.notebook = None
        self.pages = {}
        self.entries = []
        self.username = tk.StringVar(master=root)
        self.password = tk.StringVar(master=root)
        root.title("二手交易系统 · 实验三")
        root.geometry("1240x840")
        root.minsize(1080, 740)
        configure_style(root)
        self.container = ttk.Frame(root)
        self.container.pack(fill="both", expand=True)
        self.show_login()
        root.after(1000, self.maintenance_tick)

    def clear_page(self):
        """Dispose of old controls and their widget-specific key bindings."""
        for child in self.container.winfo_children():
            child.destroy()

    def show_login(self):
        """Build an input-validated, keyboard-accessible login form."""
        self.clear_page()
        frame = ttk.Frame(self.container, padding=32)
        frame.place(relx=0.5, rely=0.42, anchor="center")
        ttk.Label(frame, text="二手交易", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, pady=(0, 12)
        )
        ttk.Label(frame, text="让闲置物品找到下一位主人", style="Sub.TLabel").grid(
            row=1, column=0, columnspan=2, pady=(0, 26)
        )
        self.entries = []
        for row, (label, variable, hidden) in enumerate(
            [("登录名", self.username, False), ("密码", self.password, True)], 2
        ):
            ttk.Label(frame, text=label).grid(row=row, column=0, padx=12, pady=12, sticky="w")
            entry = ttk.Entry(frame, textvariable=variable, show="*" if hidden else "", width=32)
            entry.grid(row=row, column=1, padx=12, pady=12)
            self.entries.append(entry)
        self.entries[0].bind("<Return>", self.focus_password)
        self.entries[1].bind("<Return>", self.keyboard_login)
        ttk.Button(
            frame,
            text="登录",
            style="Accent.TButton",
            command=lambda: guarded(self.root, self.login),
        ).grid(row=4, column=0, columnspan=2, pady=14, sticky="ew")
        ttk.Button(frame, text="注册普通账号", command=lambda: RegistrationWindow(self.root)).grid(
            row=5, column=0, columnspan=2, pady=6, sticky="ew"
        )
        ttk.Label(
            frame, text="先填写账号，Enter 跳到密码；密码框 Enter 登录。", style="Sub.TLabel"
        ).grid(row=6, column=0, columnspan=2, pady=14)
        self.entries[0].focus_set()

    def focus_password(self, _event):
        """Do not advance from an empty username."""
        if not self.username.get().strip():
            messagebox.showwarning("输入不完整", "请先填写登录名。", parent=self.root)
            self.entries[0].focus_set()
        else:
            self.entries[1].focus_set()
        return "break"

    def keyboard_login(self, _event):
        """Submit from the password field without propagating Return."""
        guarded(self.root, self.login)
        return "break"

    def login(self):
        """Check missing fields before authenticating credentials."""
        if not self.username.get().strip():
            self.entries[0].focus_set()
            raise ValueError("请先填写登录名。")
        if not self.password.get():
            self.entries[1].focus_set()
            raise ValueError("请填写密码。")
        try:
            actor = authenticate(self.username.get(), self.password.get())
            self.profile = account_profile(actor)
            self.account_id = actor
            self.show_home()
        finally:
            self.password.set("")

    def show_home(self):
        """Expose ordinary navigation and a separate administrator workspace."""
        self.clear_page()
        header = ttk.Frame(self.container, padding=(22, 14))
        header.pack(fill="x")
        ttk.Label(header, text="二手交易", font=("Microsoft YaHei", 19)).pack(side="left")
        ttk.Button(header, text="退出登录", command=self.logout).pack(side="right")
        ttk.Label(header, text=f"{self.profile['username']} · 账号 {self.account_id}").pack(
            side="right", padx=18
        )
        self.notebook = ttk.Notebook(self.container)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.pages = {}
        definitions = [
            ("浏览商品", lambda parent: CatalogPage(parent, self.account_id)),
            ("我的商品", lambda parent: MyProductsPage(parent, self.account_id)),
            ("我的预约", lambda parent: ReservationsPage(parent, self.account_id)),
            ("卖家预约", lambda parent: ReservationsPage(parent, self.account_id, "seller")),
            ("消息中心", self.message_center),
            (
                "个人主页",
                lambda parent: SellerPage(
                    parent,
                    self.account_id,
                    self.account_id,
                    overlay=False,
                    detail_factory=ProductDetail,
                ),
            ),
            ("我的统计", lambda parent: ReportsPage(parent, self.account_id)),
        ]
        if "admin" in self.profile["roles"]:
            definitions.append(("管理后台", self.admin_workspace))
        for label, factory in definitions:
            holder = ttk.Frame(self.notebook)
            self.notebook.add(holder, text=label)
            self.pages[str(holder)] = (holder, factory)
        self.notebook.bind("<<NotebookTabChanged>>", self.open_tab)
        self.open_tab()

    def open_tab(self, _event=None):
        """Refresh the selected view so transitions do not leave stale progress."""
        selected = self.notebook.select()
        if not selected:
            return
        holder, factory = self.pages[selected]
        for child in holder.winfo_children():
            child.destroy()

        def build():
            page = factory(holder)
            page.pack(fill="both", expand=True)

        guarded(self.root, build)

    def message_center(self, parent):
        """Keep system notifications and private conversations distinctly labeled."""
        notebook = ttk.Notebook(parent)
        for label, factory in (("系统通知", MessagesPage), ("私信会话", InboxPage)):
            page = factory(notebook, self.account_id)
            notebook.add(page, text=label)

        def refresh_section(_event=None):
            selected = notebook.select()
            if selected:
                page = notebook.nametowidget(selected)
                guarded(page, page.refresh)

        notebook.bind("<<NotebookTabChanged>>", refresh_section)
        return notebook

    def admin_workspace(self, parent):
        """Keep privileged component pages in a dedicated secondary tab set."""
        if "admin" not in account_profile(self.account_id)["roles"]:
            raise ValueError("管理员权限已被撤销。")
        notebook = ttk.Notebook(parent)
        factories = [
            ("审核与治理", lambda p: ReviewPage(p, self.account_id)),
            ("交易处理", lambda p: ReservationsPage(p, self.account_id, "admin")),
            ("账号授权", lambda p: AccountsPage(p, self.account_id)),
            ("平台统计", lambda p: ReportsPage(p, self.account_id, True)),
            ("审计与备份", lambda p: MaintenancePage(p, self.account_id)),
        ]
        slots = {}
        for label, factory in factories:
            frame = ttk.Frame(notebook)
            notebook.add(frame, text=label)
            slots[str(frame)] = (frame, factory)

        def changed(_event=None):
            key = notebook.select()
            if not key:
                return
            frame, factory = slots[key]
            for child in frame.winfo_children():
                child.destroy()
            guarded(self.root, lambda: factory(frame).pack(fill="both", expand=True))

        notebook.bind("<<NotebookTabChanged>>", changed)
        return notebook

    def logout(self):
        """Close account-specific windows and forget in-memory authentication state."""
        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Toplevel):
                widget.destroy()
        self.account_id = None
        self.profile = None
        self.username.set("")
        self.password.set("")
        self.show_login()

    def maintenance_tick(self):
        """Check expiry and daily backup only while this desktop process is running."""
        try:
            run_timeouts()
            if self.account_id and "admin" in account_profile(self.account_id)["roles"]:
                runs = backup_status(self.account_id)
                today = datetime.now(timezone(timedelta(hours=8))).date()
                successful = [row for row in runs if row["result"] == "success"]
                last = (
                    (
                        datetime.fromisoformat(successful[0]["created_at"].replace("Z", "+00:00"))
                        .astimezone(timezone(timedelta(hours=8)))
                        .date()
                    )
                    if successful
                    else None
                )
                if last != today:
                    create_backup(self.account_id)
        except Exception:
            logging.exception("Background maintenance failed")
        self.root.after(60_000, self.maintenance_tick)


def main():
    """Initialize additive migrations and launch the desktop app."""
    parser = argparse.ArgumentParser(description="二手交易系统")
    parser.add_argument("--data-dir", type=Path, help="独立数据目录（用于演示或测试）")
    args = parser.parse_args()
    if args.data_dir:
        database.DATABASE_PATH = args.data_dir.resolve() / "trading.db"
    database.initialize_database()
    logging.basicConfig(
        filename=database.DATABASE_PATH.parent / "app.log",
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    root = tk.Tk()
    TradingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
