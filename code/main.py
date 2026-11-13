"""Desktop entry point for the secondhand trading application."""

import tkinter as tk
from tkinter import messagebox, ttk

from accounts import authenticate
from database import initialize_database
from registration_ui import RegistrationWindow


class TradingApp:
    """Manage the application window and login form."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.account_id = None
        self.username = tk.StringVar()
        self.password = tk.StringVar()

        root.title("二手交易系统")
        root.geometry("900x600")
        root.minsize(720, 480)

        self.container = ttk.Frame(root, padding=24)
        self.container.pack(fill=tk.BOTH, expand=True)
        self.show_login()

    def show_login(self) -> None:
        """Display the login form."""
        ttk.Label(
            self.container,
            text="二手交易系统",
            font=("Microsoft YaHei", 22),
        ).pack(pady=(40, 24))

        form = ttk.Frame(self.container)
        form.pack()

        ttk.Label(form, text="登录名").grid(
            row=0, column=0, padx=8, pady=10
        )
        username_entry = ttk.Entry(
            form, textvariable=self.username, width=30
        )
        username_entry.grid(row=0, column=1, padx=8, pady=10)

        ttk.Label(form, text="密码").grid(
            row=1, column=0, padx=8, pady=10
        )
        ttk.Entry(
            form, textvariable=self.password, show="*", width=30
        ).grid(row=1, column=1, padx=8, pady=10)

        ttk.Button(
            self.container, text="登录", command=self.login
        ).pack(pady=20)

        ttk.Button(
            self.container,
            text="注册账号",
            command=lambda: RegistrationWindow(self.root),
        ).pack(pady=(0, 12))

        ttk.Button(
            self.container, text="退出程序", command=self.root.destroy
        ).pack()

        username_entry.focus_set()

    def login(self) -> None:
        """Authenticate the submitted credentials."""
        try:
            account_id = authenticate(
                self.username.get(), self.password.get()
            )
        except ValueError as error:
            messagebox.showerror("登录失败", str(error), parent=self.root)
        else:
            self.account_id = account_id
            messagebox.showinfo(
                "登录成功",
                f"当前账号编号：{account_id}",
                parent=self.root,
            )
        finally:
            self.password.set("")


def main() -> None:
    """Initialize storage and start the desktop application."""
    initialize_database()
    root = tk.Tk()
    TradingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
