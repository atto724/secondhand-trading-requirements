"""Desktop entry point for the secondhand trading application."""

import tkinter as tk
from tkinter import ttk


def main() -> None:
    """Create the application window and start the event loop."""
    root = tk.Tk()
    root.title("二手交易系统")
    root.geometry("900x600")
    root.minsize(720, 480)

    container = ttk.Frame(root, padding=24)
    container.pack(fill=tk.BOTH, expand=True)

    title = ttk.Label(
        container,
        text="二手交易系统",
        font=("Microsoft YaHei", 22),
    )
    title.pack(pady=(40, 16))

    description = ttk.Label(
        container,
        text="开发阶段：工程初始化\n下一阶段：账号注册与登录",
        justify=tk.CENTER,
    )
    description.pack(pady=12)

    close_button = ttk.Button(
        container,
        text="退出程序",
        command=root.destroy,
    )
    close_button.pack(pady=24)

    root.mainloop()


if __name__ == "__main__":
    main()
