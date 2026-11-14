"""Desktop entry point for the secondhand trading application."""

import tkinter as tk
from tkinter import messagebox, ttk

from accounts import authenticate
from database import initialize_database
from registration_ui import RegistrationWindow
from products_ui import MyProductsWindow


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
        self.clear_page()
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
        password_entry = ttk.Entry(
            form,
            textvariable=self.password,
            show="*",
            width=30,
        )
        password_entry.grid(
            row=1, column=1, padx=8, pady=10
        )
        self.username_entry = username_entry
        self.password_entry = password_entry

        username_entry.bind("<Return>", self.focus_password)
        password_entry.bind("<Return>", self.login_from_keyboard)
       
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
        if not self.username.get().strip():
            messagebox.showwarning(
                "输入不完整", "请先填写登录名。", parent=self.root
            )
            self.username_entry.focus_set()
            return

        if not self.password.get():
            messagebox.showwarning(
                "输入不完整", "请填写密码。", parent=self.root
            )
            self.password_entry.focus_set()
            return
        try:
            account_id = authenticate(
                self.username.get(), self.password.get()
            )
        except ValueError as error:
            messagebox.showerror("登录失败", str(error), parent=self.root)
        else:
            self.account_id = account_id
            self.show_home()
        finally:
            self.password.set("")

    def clear_page(self) -> None:
        """Remove widgets from the current page."""
        for widget in self.container.winfo_children():
            widget.destroy()

    def show_home(self) -> None:
        """Display the home page for the signed-in account."""
        self.clear_page()

        ttk.Label(
            self.container,
            text="二手交易系统",
            font=("Microsoft YaHei", 22),
        ).pack(pady=(40, 24))

        ttk.Label(
            self.container,
            text=f"已登录，账号编号：{self.account_id}",
        ).pack(pady=12)

        ttk.Button(
            self.container,
            text="我的商品",
            command=lambda: MyProductsWindow(
                self.root, self.account_id
            ),
        ).pack(pady=12)
        ttk.Button(
            self.container,
            text="退出登录",
            command=self.logout,
        ).pack(pady=24)

    def logout(self) -> None:
        """Clear the current login state and return to the login page."""
        self.account_id = None
        self.username.set("")
        self.password.set("")
        self.show_login()
    def focus_password(self, event):
        """Move from the username field to the password field."""
        if not self.username.get().strip():
            messagebox.showwarning(
                "输入不完整", "请先填写登录名。", parent=self.root
            )
            self.username_entry.focus_set()
        else:
            self.password_entry.focus_set()
        return "break"

    def login_from_keyboard(self, event):
        """Submit login from the password field."""
        self.login()
        return "break"


def main() -> None:
    """Initialize storage and start the desktop application."""
    initialize_database()
    root = tk.Tk()
    TradingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
