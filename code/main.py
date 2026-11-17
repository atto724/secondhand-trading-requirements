"""Desktop startup, authentication and component navigation."""

import argparse
import logging
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import messagebox, ttk

import database
from accounts import authenticate
from admin_ui import AccountsPage, MaintenancePage, ReportsPage, ReviewPage
from governance import account_profile
from market_ui import CatalogPage, MyProductsPage, ProductDetail
from operations import backup_status, create_backup
from message_ui import MessageCenter
from registration_ui import RegistrationWindow
from seller_ui import SellerPage
from trades import run_timeouts
from trades_ui import ReservationsPage
from ui_common import ACCENT, INK, PAPER, avatar_photo, configure_style, guarded, resume_view
from community import seller_profile


class TradingApp:
    """Keep UI login state separate from business authorization checks."""

    def __init__(self, root):
        self.root = root
        self.root.chat_drafts = {}
        self.active_tab = None
        self.account_id = None
        self.profile = None
        self.notebook = None
        self.pages = {}
        self.nav_items = {}
        self.avatar_button = None
        self.account_menu = None
        self.login_hint = None
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
        self.login_hint = ttk.Label(
            frame, text="先填写账号，Enter 跳到密码；密码框 Enter 登录。", style="Sub.TLabel"
        )
        self.login_hint.grid(row=6, column=0, columnspan=2, pady=14)
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
        header = tk.Frame(self.container, bg=PAPER, padx=26, pady=16)
        header.pack(fill="x")
        ttk.Label(header, text="二手交易", font=("Microsoft YaHei", 21), background=PAPER).pack(
            side="left"
        )
        identity = seller_profile(self.account_id, self.account_id)
        self.avatar_button = tk.Button(
            header,
            command=self.show_account_menu,
            bg=PAPER,
            activebackground=PAPER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            takefocus=True,
        )
        self.avatar_button.photo = avatar_photo(
            self.avatar_button, self.account_id, identity["avatar_path"], (44, 44), circular=True
        )
        self.avatar_button.configure(image=self.avatar_button.photo)
        self.avatar_button.pack(side="right", padx=4)
        self.avatar_button.bind("<Return>", lambda event: self.show_account_menu())
        self.account_menu = tk.Menu(
            self.avatar_button,
            tearoff=False,
            bg=PAPER,
            fg=INK,
            activebackground="#fff0e4",
            activeforeground=ACCENT,
            relief="solid",
            bd=1,
            font=("Microsoft YaHei", 11),
        )
        self.account_menu.add_command(
            label=identity["nickname"] or identity["username"], state="disabled"
        )
        self.account_menu.add_separator()
        self.account_menu.add_command(label="退出登录", command=self.logout)
        self.account_menu.add_command(label="切换账号", command=self.switch_account)
        self.account_menu.add_command(label="退出应用", command=self.exit_application)
        navigation = tk.Frame(self.container, bg=PAPER, padx=18)
        navigation.pack(fill="x")
        self.nav_items = {}
        style = ttk.Style(self.root)
        style.layout("Main.TNotebook.Tab", [])
        style.configure(
            "Main.TNotebook",
            borderwidth=0,
            background=PAPER,
            bordercolor=PAPER,
            lightcolor=PAPER,
            darkcolor=PAPER,
        )
        self.notebook = ttk.Notebook(self.container, style="Main.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.pages = {}
        self.active_tab = None
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
            item = tk.Frame(navigation, bg=PAPER)
            item.pack(side="left", padx=7)
            button = tk.Button(
                item,
                text=label,
                bg=PAPER,
                fg=INK,
                activebackground=PAPER,
                activeforeground=ACCENT,
                relief="flat",
                bd=0,
                font=("Microsoft YaHei", 13),
                padx=8,
                pady=12,
                cursor="hand2",
                command=lambda page=holder: self.notebook.select(page),
            )
            button.pack()
            underline = tk.Frame(item, height=3, bg=PAPER)
            underline.pack(fill="x")
            self.nav_items[str(holder)] = (button, underline)
        self.notebook.bind("<<NotebookTabChanged>>", self.open_tab)
        self.open_tab()

    def open_tab(self, _event=None):
        """Reuse session-owned pages while rechecking the current account."""
        if self.notebook is None:
            return
        try:
            self.profile = account_profile(self.account_id)
        except ValueError:
            self.logout()
            messagebox.showwarning("请重新登录", "账号已不可用，已清除当前页面。", parent=self.root)
            return
        for key, (holder, _) in list(self.pages.items()):
            if (
                self.notebook.tab(key, "text") == "管理后台"
                and "admin" not in self.profile["roles"]
            ):
                self.notebook.forget(holder)
                holder.destroy()
                self.nav_items.pop(key)[0].master.destroy()
                del self.pages[key]
        selected = self.notebook.select()
        if not selected:
            return
        for key, (button, underline) in self.nav_items.items():
            button.configure(fg=ACCENT if key == selected else INK)
            underline.configure(bg=ACCENT if key == selected else PAPER)
        if selected == self.active_tab:
            return
        self.active_tab = selected
        holder, factory = self.pages[selected]

        def build():
            children = holder.winfo_children()
            if children:
                resume_view(children[0])
            else:
                try:
                    page = factory(holder)
                    page.pack(fill="both", expand=True)
                except Exception:
                    for child in holder.winfo_children():
                        child.destroy()
                    self.active_tab = None
                    raise

        guarded(self.root, build)

    def message_center(self, parent):
        """Show avatar-based conversation rows that open directly into threads."""
        return MessageCenter(parent, self.account_id)

    def admin_workspace(self, parent):
        """Keep privileged component pages in a dedicated secondary tab set."""
        if "admin" not in account_profile(self.account_id)["roles"]:
            raise ValueError("管理员权限已被撤销。")
        workspace = ttk.Frame(parent)
        navigation = tk.Frame(workspace, bg=PAPER, padx=12, pady=4)
        navigation.pack(fill="x")
        notebook = ttk.Notebook(workspace, style="Main.TNotebook")
        notebook.pack(fill="both", expand=True)
        tabs = {}
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
            item = tk.Frame(navigation, bg=PAPER)
            item.pack(side="left", padx=8)
            button = tk.Button(
                item,
                text=label,
                command=lambda target=frame: notebook.select(target),
                bg=PAPER,
                fg=INK,
                relief="flat",
                bd=0,
                font=("Microsoft YaHei", 12),
                padx=12,
                pady=8,
                cursor="hand2",
            )
            button.pack()
            line = tk.Frame(item, bg=PAPER, height=2)
            line.pack(fill="x")
            tabs[str(frame)] = (button, line)

        workspace.active_key = None

        def changed(_event=None):
            if "admin" not in account_profile(self.account_id)["roles"]:
                for child in workspace.winfo_children():
                    child.destroy()
                raise ValueError("管理员权限已被撤销，请切换到普通页面。")
            key = notebook.select()
            if not key:
                return
            for identity, (button, line) in tabs.items():
                button.configure(fg=ACCENT if identity == key else INK)
                line.configure(bg=ACCENT if identity == key else PAPER)
            if key == workspace.active_key:
                return
            workspace.active_key = key
            frame, factory = slots[key]
            if frame.winfo_children():
                guarded(self.root, lambda: resume_view(frame.winfo_children()[0]))
            else:
                guarded(self.root, lambda: factory(frame).pack(fill="both", expand=True))

        notebook.bind("<<NotebookTabChanged>>", lambda event: guarded(self.root, changed))
        workspace.notebook = notebook
        workspace.nav_items = tabs
        workspace.on_resume = lambda: resume_view(slots[notebook.select()][0].winfo_children()[0])
        changed()
        return workspace

    def show_account_menu(self):
        """Anchor a dismissible menu beneath the circular account avatar."""
        self.account_menu.update_idletasks()
        left = (
            self.avatar_button.winfo_rootx()
            + self.avatar_button.winfo_width()
            - self.account_menu.winfo_reqwidth()
        )
        top = self.avatar_button.winfo_rooty() + self.avatar_button.winfo_height() + 6
        try:
            self.account_menu.tk_popup(left, top)
        finally:
            if self.account_menu is not None:
                self.account_menu.grab_release()

    def switch_account(self):
        """Forget the current session before requesting another account's password."""
        self.logout()
        self.login_hint.configure(text="请输入另一个账号，登录后即可切换。")
        self.entries[0].focus_set()

    def exit_application(self):
        """Close the app without changing any stored accounts or transactions."""
        self.account_id = None
        self.profile = None
        self.username.set("")
        self.password.set("")
        self.root.chat_drafts.clear()
        self.root.destroy()

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
        self.root.chat_drafts.clear()
        self.active_tab = None
        self.pages = {}
        self.nav_items = {}
        self.notebook = None
        self.account_menu = None
        self.avatar_button = None

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
