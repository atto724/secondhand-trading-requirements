"""Conversation-first message center with avatar rows and inline threads."""

import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont, ttk

from community import inbox
from domain import PRODUCT_STATUS_LABELS
from operations import mark_all_messages_read, mark_read, messages
from seller_ui import ChatPage, local_time
from ui_common import ACCENT, BG, INK, MUTED, PAPER, avatar_photo, guarded, empty_state, navigate_to


def notification_group(event):
    """Group real system events without pretending they are personal messages."""
    if event in {
        "reservation",
        "confirmed",
        "cancel",
        "expired",
        "rejected",
        "delivered",
        "complete",
        "completed",
        "delivery_reminder",
        "correction",
        "dispute",
        "reminder",
    }:
        return "预约与交易"
    if event in {"review", "review_approved", "review_rejected"}:
        return "商品审核"
    if event in {
        "account_status",
        "account_disabled",
        "grant_admin",
        "revoke_admin",
        "moderation",
        "release",
    }:
        return "账号与服务"
    return "系统通知"


def notification_text(content):
    """Translate legacy machine-state prefixes for presentation only."""
    for state, label in PRODUCT_STATUS_LABELS.items():
        prefix = f"商品审核：{state.value}"
        if content.startswith(prefix):
            return "商品审核：" + label + content[len(prefix) :]
    return content


def fit_preview(text, width, font):
    """Fit a single-line excerpt to the actual font and available width."""
    text = " ".join(text.split())
    if font.measure(text) <= width:
        return text
    lower, upper = 0, len(text)
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if font.measure(text[:middle] + "…") <= width:
            lower = middle
        else:
            upper = middle - 1
    return text[:lower] + "…"


class NotificationThread(tk.Frame):
    """Read-only system history in the same navigation surface as conversations."""

    def __init__(self, parent, actor, group, on_back):
        super().__init__(parent, bg=BG)
        self.actor, self.group, self.on_back = actor, group, on_back
        self.limit = 50
        self.items = []
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        header = ttk.Frame(self, padding=18)
        header.pack(fill="x")
        ttk.Button(header, text="← 返回消息中心", command=self.go_back).pack(side="left")
        ttk.Label(header, text=group, style="Title.TLabel").pack(side="left", padx=18)
        ttk.Button(header, text="刷新通知", command=lambda: guarded(self, self.refresh)).pack(
            side="right"
        )
        self.older = ttk.Button(
            header, text="加载更早通知", command=lambda: guarded(self, self.load_older)
        )
        self.older.pack(side="right", padx=10)
        ttk.Label(self, text="系统通知仅用于记录提醒，不支持回复。", style="Sub.TLabel").pack(
            side="bottom", fill="x", padx=22, pady=14
        )
        self.canvas = tk.Canvas(self, bg="#f4f1ed", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.body = tk.Frame(self.canvas, bg="#f4f1ed")
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self.resize)
        self.body.bind(
            "<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.refresh()

    def resize(self, event):
        """Keep notification bodies inside the viewport."""
        self.canvas.itemconfigure(self.window, width=event.width)
        for widget in self.items:
            widget.configure(wraplength=max(180, event.width - 120))

    def wheel(self, event):
        """Scroll over the displayed notification cards."""
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def refresh(self):
        """Only mark this account's actually loaded group records read."""
        rows = [
            row
            for row in messages(self.actor)
            if notification_group(row["event_type"]) == self.group
        ]
        visible = rows[: self.limit]
        for widget in self.body.winfo_children():
            widget.destroy()
        self.items = []
        for row in reversed(visible):
            if not row["is_read"]:
                mark_read(self.actor, row["id"])
            tk.Label(self.body, text=local_time(row["created_at"]), bg="#f4f1ed", fg=MUTED).pack(
                pady=(18, 6)
            )
            card = tk.Frame(self.body, bg=PAPER, padx=18, pady=14)
            card.pack(fill="x", padx=30, pady=(0, 8))
            tk.Label(
                card, text=self.group, bg=PAPER, fg=INK, font=("Microsoft YaHei", 12, "bold")
            ).pack(anchor="w")
            content = tk.Label(
                card,
                text=notification_text(row["content"]),
                bg=PAPER,
                fg=INK,
                wraplength=700,
                justify="left",
                anchor="w",
                font=("Microsoft YaHei", 11),
            )
            content.pack(fill="x", pady=(8, 0))
            self.items.append(content)
            for widget in (card, content):
                widget.bind("<MouseWheel>", self.wheel)
        if not visible:
            tk.Label(self.body, text="暂无通知", bg="#f4f1ed", fg=MUTED).pack(pady=50)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.older.configure(state="normal" if len(rows) > self.limit else "disabled")
        self.update_idletasks()
        self.canvas.yview_moveto(1)

    def load_older(self):
        """Load another bounded page of system history."""
        self.limit += 50
        self.refresh()
        self.canvas.yview_moveto(0)

    def go_back(self):
        """Refresh the parent list's dots when returning."""
        callback = self.on_back
        self.destroy()
        callback()


class MessageCenter(ttk.Frame):
    """Avatar, name, latest excerpt and time rows instead of data tables."""

    def __init__(self, parent, actor):
        super().__init__(parent, padding=20)
        self.actor = actor
        self.entries = {}
        self.rows = {}
        self.preview_font = tkfont.Font(family="Microsoft YaHei", size=11)
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="消息中心", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="全部已读", command=lambda: guarded(self, self.read_all)).pack(
            side="right"
        )
        ttk.Button(header, text="刷新", command=lambda: guarded(self, self.refresh)).pack(
            side="right", padx=12
        )
        self.canvas = tk.Canvas(self, bg=PAPER, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.body = tk.Frame(self.canvas, bg=PAPER)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self.resize)
        self.body.bind(
            "<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.refresh()

    def resize(self, event):
        """Use one-line excerpts with ellipsis at narrow widths."""
        self.canvas.itemconfigure(self.window, width=event.width)
        for key, row in self.rows.items():
            row["preview"].configure(
                text=fit_preview(
                    self.entries[key]["preview"], max(120, event.width - 220), self.preview_font
                )
            )

    def wheel(self, event):
        """Scroll the conversation list without affecting other pages."""
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def refresh(self):
        """Merge caller-owned direct conversations with grouped system notifications."""
        position = self.canvas.yview()[0]
        entries = []
        for row in inbox(self.actor):
            entries.append(
                {
                    "key": f"peer:{row['peer_id']}",
                    "kind": "private",
                    "peer": row["peer_id"],
                    "name": row["nickname"] or row["username"],
                    "avatar": row["avatar_path"],
                    "preview": row["content"],
                    "time": row["created_at"],
                    "unread": row["unread"] > 0,
                }
            )
        grouped = {}
        for row in messages(self.actor):
            grouped.setdefault(notification_group(row["event_type"]), []).append(row)
        for group, rows in grouped.items():
            newest = rows[0]
            entries.append(
                {
                    "key": f"notice:{group}",
                    "kind": "system",
                    "name": group,
                    "preview": notification_text(newest["content"]),
                    "time": newest["created_at"],
                    "unread": any(not row["is_read"] for row in rows),
                }
            )
        entries.sort(
            key=lambda row: datetime.fromisoformat(row["time"].replace("Z", "+00:00")), reverse=True
        )
        self.entries = {row["key"]: row for row in entries}
        for widget in self.body.winfo_children():
            widget.destroy()
        self.rows = {}
        for entry in entries:
            self.draw_entry(entry)
        if not entries:
            empty_state(
                self.body,
                "还没有消息",
                "遇到喜欢的商品，可以在详情页私信卖家；交易进度通知也会显示在这里。",
                lambda: navigate_to(self, "浏览商品"),
                "去浏览商品",
                PAPER,
            ).pack(fill="x", pady=30)
        self.update_idletasks()
        self.canvas.yview_moveto(position)

    def draw_entry(self, entry):
        """Make the entire row clickable and keyboard-accessible."""
        key = entry["key"]
        row = tk.Frame(self.body, bg=PAPER, padx=18, pady=16, takefocus=True)
        row.pack(fill="x")
        avatar = tk.Label(
            row,
            bg="#fbe7d4",
            fg=ACCENT,
            text="通知",
            font=("Microsoft YaHei", 15),
            width=4,
            height=2,
        )
        if entry["kind"] == "private":
            avatar.photo = avatar_photo(self, entry["peer"], entry["avatar"], (56, 56))
            avatar.configure(image=avatar.photo, text="", width=56, height=56)
        avatar.pack(side="left", padx=(0, 18))
        right = tk.Frame(row, bg=PAPER)
        right.pack(side="right", anchor="n", padx=(12, 0))
        tk.Label(
            right,
            text=local_time(entry["time"]),
            bg=PAPER,
            fg="#999999",
            font=("Microsoft YaHei", 9),
        ).pack(anchor="e")
        dot = tk.Canvas(right, width=12, height=12, bg=PAPER, highlightthickness=0)
        dot.pack(anchor="e", pady=(12, 0))
        if entry["unread"]:
            dot.create_oval(2, 2, 10, 10, fill="#ed4141", outline="")
        info = tk.Frame(row, bg=PAPER)
        info.pack(side="left", fill="both", expand=True)
        tk.Label(
            info,
            text=entry["name"],
            bg=PAPER,
            fg=INK,
            font=("Microsoft YaHei", 15, "bold"),
            anchor="w",
        ).pack(fill="x")
        preview = tk.Label(
            info,
            text=fit_preview(
                entry["preview"], max(120, self.canvas.winfo_width() - 220), self.preview_font
            ),
            bg=PAPER,
            fg=MUTED,
            font=self.preview_font,
            anchor="w",
        )
        preview.pack(fill="x", pady=(8, 0))
        self.rows[key] = {"frame": row, "preview": preview, "dot": dot}
        for widget in (
            row,
            avatar,
            right,
            dot,
            info,
            *right.winfo_children(),
            *info.winfo_children(),
        ):
            widget.configure(cursor="hand2")
            widget.bind(
                "<Button-1>",
                lambda event, identity=key: guarded(self, lambda: self.open_entry(identity)),
            )
            widget.bind("<MouseWheel>", self.wheel)
        row.bind("<Return>", lambda event: guarded(self, lambda: self.open_entry(key)))
        tk.Frame(self.body, height=1, bg="#f0ece8").pack(fill="x", padx=18)

    def open_entry(self, key):
        """Route one click directly to the selected conversation or system thread."""
        entry = self.entries[key]
        if entry["kind"] == "private":
            ChatPage(
                self, self.actor, entry["peer"], back_label="← 返回消息中心", on_back=self.refresh
            )
        else:
            NotificationThread(self, self.actor, entry["name"], self.refresh)

    def read_all(self):
        """Keep the existing receiver-scoped bulk-read behavior."""
        mark_all_messages_read(self.actor)
        self.refresh()
