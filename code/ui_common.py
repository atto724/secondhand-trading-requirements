"""Shared desktop widgets, image rendering and error presentation."""

import json
import logging
import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageOps, ImageTk

import database

BG = "#fbf3e6"
PAPER = "#ffffff"
INK = "#3e2d23"
ACCENT = "#ad4326"
MUTED = "#80634f"


def configure_style(root):
    """Apply the warm palette from the experiment-two UI prototypes."""
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei", 10), foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG)
    style.configure("Title.TLabel", font=("Microsoft YaHei", 22))
    style.configure("Sub.TLabel", foreground=MUTED)
    style.configure("TButton", padding=(12, 7), background="#fffaf4")
    style.map("TButton", background=[("active", "#f3dfca")])
    style.configure("Accent.TButton", background=ACCENT, foreground="white")
    style.map("Accent.TButton", background=[("active", "#91371f")])
    style.configure("Treeview", rowheight=32, background=PAPER, fieldbackground=PAPER)
    style.configure("Treeview.Heading", padding=8, background="#f4e4d2")


def guarded(parent, function):
    """Present expected operational failures without terminating the event loop."""
    try:
        return function()
    except (ValueError, OSError, sqlite3.Error) as error:
        messagebox.showerror("操作未完成", str(error), parent=parent)
        return None
    except Exception:
        logging.exception("Unexpected desktop operation failure")
        messagebox.showerror("操作未完成", "发生未预期错误，请查看 data/app.log。", parent=parent)
        return None


def thumbnail(parent, path, size=(170, 150)):
    """Return a correctly oriented thumbnail while keeping originals unchanged."""
    with Image.open(path) as source:
        picture = ImageOps.exif_transpose(source).convert("RGB")
        picture.thumbnail(size)
        canvas = Image.new("RGB", size, "#f3ece3")
        canvas.paste(picture, ((size[0] - picture.width) // 2, (size[1] - picture.height) // 2))
        return ImageTk.PhotoImage(canvas, master=parent)


def stored_image(relative):
    """Resolve application images inside the configured data directory."""
    root = database.DATABASE_PATH.parent.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("图片路径无效。")
    return path


class Window(tk.Toplevel):
    """A resizable secondary window with Escape-to-close support."""

    def __init__(self, parent, title, size="950x650"):
        super().__init__(parent)
        self.title(title)
        self.geometry(size)
        self.minsize(700, 500)
        self.configure(bg=BG)
        self.transient(parent)
        self.bind("<Escape>", lambda event: self.destroy())


class DataTable(ttk.Frame):
    """Scrollable keyed table with safe single-row selection."""

    def __init__(self, parent, columns):
        super().__init__(parent)
        self.tree = ttk.Treeview(
            self, columns=[item[0] for item in columns], show="headings", selectmode="browse"
        )
        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=50)
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def fill(self, rows):
        """Replace displayed rows while preserving no stale selection."""
        self.tree.delete(*self.tree.get_children())
        for key, values in rows:
            self.tree.insert("", "end", iid=str(key), values=values)

    def selected(self):
        """Return the selected numeric object ID or explain missing selection."""
        selection = self.tree.selection()
        if len(selection) != 1:
            raise ValueError("请先选择一条记录。")
        return int(selection[0])


class TextWindow(Window):
    """Read-only wrapped details with a vertical scrollbar."""

    def __init__(self, parent, title, content):
        super().__init__(parent, title, "850x580")
        text = tk.Text(self, wrap="word", padx=20, pady=20, font=("Microsoft YaHei", 11))
        scrollbar = ttk.Scrollbar(self, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        value = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False, indent=2)
        )
        text.insert("1.0", value)
        text.configure(state="disabled")
