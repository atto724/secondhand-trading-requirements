"""Registration form for the desktop application."""

import tkinter as tk
from tkinter import messagebox, ttk

from accounts import create_account


class RegistrationWindow(tk.Toplevel):
    """Display account registration fields in a separate window."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("注册账号")
        self.geometry("460x420")
        self.resizable(False, False)
        self.transient(parent)

        self.username = tk.StringVar(master=self)
        self.phone = tk.StringVar(master=self)
        self.password = tk.StringVar(master=self)
        self.confirm_password = tk.StringVar(master=self)

        form = ttk.Frame(self, padding=24)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        fields = [
            ("登录名", self.username, False),
            ("手机号", self.phone, False),
            ("密码", self.password, True),
            ("确认密码", self.confirm_password, True),
        ]

        for row, (label, variable, hidden) in enumerate(fields):
            ttk.Label(form, text=label).grid(
                row=row, column=0, padx=(0, 12), pady=10, sticky=tk.W
            )
            entry = ttk.Entry(
                form,
                textvariable=variable,
                show="*" if hidden else "",
            )
            entry.grid(row=row, column=1, pady=10, sticky=tk.EW)
            if row == 0:
                entry.focus_set()

        ttk.Label(
            form, text="注册提交功能将在下一步接入。"
        ).grid(row=4, column=0, columnspan=2, pady=12)

        ttk.Label(
            form, text="教学版：未接入短信验证"
        ).grid(row=4, column=0, columnspan=2, pady=12)

        ttk.Button(
            form, text="注册账号", command=self.register
        ).grid(row=5, column=0, columnspan=2, pady=8)

        ttk.Button(
            form, text="返回登录", command=self.destroy
        ).grid(row=6, column=0, columnspan=2, pady=8)

        self.grab_set()

        self.grab_set()

    def register(self) -> None:
        """Validate the form and create an ordinary account."""
        if self.password.get() != self.confirm_password.get():
            messagebox.showerror(
                "注册失败", "两次输入的密码不一致。", parent=self
            )
            return

        try:
            create_account(
                self.username.get(),
                self.phone.get(),
                self.password.get(),
            )
        except ValueError as error:
            messagebox.showerror("注册失败", str(error), parent=self)
        else:
            messagebox.showinfo(
                "注册成功",
                "账号已创建，请返回登录。",
                parent=self,
            )
            self.destroy()
        finally:
            self.password.set("")
            self.confirm_password.set("")