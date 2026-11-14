"""Registration form with ordered keyboard navigation and explicit SMS limitation."""

import tkinter as tk
from tkinter import messagebox, ttk

from accounts import create_account
from ui_common import Window, guarded


class RegistrationWindow(Window):
    """Create ordinary buyer/seller accounts without exposing administrator roles."""

    def __init__(self, parent):
        super().__init__(parent, "注册账号", "720x510")
        self.variables = {}
        self.entries = []
        form = ttk.Frame(self, padding=28)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="创建普通账号", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=16
        )
        definitions = [
            ("username", "登录名 *", False),
            ("phone", "手机号 *", False),
            ("password", "密码 *", True),
            ("confirmation", "确认密码 *", True),
        ]
        for row, (key, label, hidden) in enumerate(definitions, 1):
            variable = tk.StringVar(master=self)
            self.variables[key] = variable
            ttk.Label(form, text=label).grid(row=row, column=0, pady=10, padx=(0, 16), sticky="w")
            entry = ttk.Entry(form, textvariable=variable, show="*" if hidden else "")
            entry.grid(row=row, column=1, pady=10, sticky="ew")
            self.entries.append(entry)
        for index, entry in enumerate(self.entries):
            entry.bind("<Return>", lambda event, current=index: self.advance(current))
        ttk.Label(
            form,
            text="登录名 3～30 字符；密码 8～128 字符。\n教学桌面版：手机号仅校验格式，未验证归属，未接入短信服务。",
            wraplength=600,
            style="Sub.TLabel",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=14)
        ttk.Button(
            form, text="注册", style="Accent.TButton", command=lambda: guarded(self, self.register)
        ).grid(row=6, column=1, sticky="e", pady=12)
        self.entries[0].focus_set()

    def advance(self, index):
        """Advance through inputs or submit at the final field."""
        if index == len(self.entries) - 1:
            guarded(self, self.register)
        elif not self.entries[index].get().strip():
            messagebox.showwarning("输入不完整", "请先填写当前项。", parent=self)
            self.entries[index].focus_set()
        else:
            self.entries[index + 1].focus_set()
        return "break"

    def register(self):
        """Validate every input even when the user skips fields with the mouse."""
        for index, key in enumerate(("username", "phone", "password", "confirmation")):
            if not self.variables[key].get().strip():
                self.entries[index].focus_set()
                raise ValueError("请完整填写注册信息。")
        password = self.variables["password"].get()
        if password != self.variables["confirmation"].get():
            self.entries[3].focus_set()
            raise ValueError("两次输入的密码不一致。")
        create_account(self.variables["username"].get(), self.variables["phone"].get(), password)
        messagebox.showinfo("注册成功", "账号已创建，请返回登录。", parent=self)
        self.destroy()
