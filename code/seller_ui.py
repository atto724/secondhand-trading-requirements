"""In-page seller storefront, voluntary profiles and private-message views."""

import tkinter as tk
import sqlite3
from datetime import datetime, timedelta, timezone
from tkinter import filedialog, ttk

from catalog import search_products
from community import (
    conversation,
    inbox,
    latest_read_message,
    seller_profile,
    send_direct_message,
    update_avatar,
    update_profile,
)
from core import price
from operations import mark_all_messages_read
from ui_common import (
    ACCENT,
    BG,
    INK,
    PAPER,
    DataTable,
    avatar_photo,
    guarded,
    enable_unread_dots,
    set_unread_dot,
)


def local_time(value):
    """Render recorded UTC events in the same UTC+8 used by reports."""
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(timezone(timedelta(hours=8)))
        .strftime("%Y-%m-%d %H:%M")
    )


class BubbleHistory(ttk.Frame):
    """Scrollable, correctly parented message rows with left/right speech bubbles."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(
            self, background="#ededed", highlightthickness=0, width=260, height=120
        )
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg="#ededed")
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.messages = []
        self.bubbles = {}
        self.receipt = None
        self.content.bind("<Configure>", self.update_region)
        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<MouseWheel>", self.wheel)

    def update_region(self, _event=None):
        """Keep scrolling bounds synchronized with wrapped message heights."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def resize(self, event):
        """Wrap long messages within the visible pane instead of overflowing it."""
        self.canvas.itemconfigure(self.window, width=event.width)
        for bubble in self.bubbles.values():
            bubble.configure(wraplength=max(80, int(event.width * 0.62) - 24))

    def wheel(self, event):
        """Scroll only this conversation, without global bindings."""
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def show_receipt(self, message_id):
        """Show 'read' only beneath the latest outgoing bubble; otherwise stay blank."""
        if self.receipt is not None and self.receipt.winfo_exists():
            self.receipt.destroy()
        self.receipt = None
        if message_id in self.bubbles:
            self.receipt = tk.Label(
                self.bubbles[message_id].master,
                text="已读",
                bg="#ededed",
                fg="#888888",
                font=("Microsoft YaHei", 8),
            )
            self.receipt.pack(anchor="e", pady=(3, 0))

    def render(self, rows, actor, peer_name, avatars, older=False):
        """Show actual persisted messages and keep the reading position on older loads."""
        old_height = max(1, self.content.winfo_height())
        old_top = self.canvas.yview()[0] * old_height
        if older:
            combined = {row["id"]: row for row in self.messages + rows}
            self.messages = sorted(combined.values(), key=lambda row: row["id"])
        else:
            self.messages = rows
        for widget in self.content.winfo_children():
            widget.destroy()
        self.bubbles.clear()
        self.receipt = None
        if not self.messages:
            tk.Label(
                self.content, text="暂无消息，向卖家打个招呼吧", bg="#ededed", fg="#888888"
            ).pack(pady=25)
        for row in self.messages:
            mine = row["sender_id"] == actor
            tk.Label(
                self.content,
                text=local_time(row["created_at"]),
                bg="#ededed",
                fg="#999999",
                font=("Microsoft YaHei", 8),
            ).pack(pady=(12, 4))
            line = tk.Frame(self.content, bg="#ededed")
            line.pack(fill="x", padx=8, pady=(0, 6))
            avatar = tk.Label(line, bg="#ededed")
            avatar.photo = avatar_photo(
                self, row["sender_id"], avatars.get(row["sender_id"], ""), (32, 32)
            )
            avatar.configure(image=avatar.photo)
            avatar.pack(side="right" if mine else "left", anchor="n", padx=4)
            group = tk.Frame(line, bg="#ededed")
            group.pack(side="right" if mine else "left", anchor="n")
            tk.Label(
                group,
                text="我" if mine else peer_name,
                bg="#ededed",
                fg="#888888",
                font=("Microsoft YaHei", 8),
            ).pack(anchor="e" if mine else "w")
            bubble = tk.Label(
                group,
                text=row["content"],
                bg="#95ec69" if mine else PAPER,
                fg="#222222",
                justify="left",
                anchor="w",
                wraplength=max(80, int(self.canvas.winfo_width() * 0.62) - 24),
                padx=10,
                pady=8,
                font=("Microsoft YaHei", 10),
            )
            bubble.pack(anchor="e" if mine else "w")
            self.bubbles[row["id"]] = bubble
            for widget in (avatar, group, line, bubble):
                widget.bind("<MouseWheel>", self.wheel)
        self.update_idletasks()
        self.update_region()
        if older:
            height = max(1, self.content.winfo_height())
            self.canvas.yview_moveto((old_top + height - old_height) / height)
        else:
            self.canvas.yview_moveto(1)


class ChatPanel(ttk.Frame):
    """Read and send one participant-scoped conversation, with explicit refresh."""

    def __init__(self, parent, actor, peer, on_read=None):
        super().__init__(parent, padding=12)
        self.on_read = on_read
        self.actor, self.peer, self.before = actor, peer, None
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="刷新最新消息", command=lambda: guarded(self, self.refresh)).pack(
            side="left"
        )
        self.older = ttk.Button(
            toolbar, text="加载更早消息", command=lambda: guarded(self, lambda: self.refresh(True))
        )
        self.older.pack(side="left", padx=8)
        self.status = ttk.Label(toolbar, style="Sub.TLabel")
        self.status.pack(side="left")
        composer = ttk.Frame(self)
        composer.pack(side="bottom", fill="x")
        self.history = BubbleHistory(self)
        ttk.Label(
            composer,
            text="私信（最多1000字）：Enter换行，Ctrl+Enter发送。",
            style="Sub.TLabel",
            wraplength=320,
        ).pack(anchor="w", pady=8)
        self.editor = tk.Text(composer, height=3, wrap="word", font=("Microsoft YaHei", 10))
        self.editor.pack(fill="x")
        self.editor.bind("<Control-Return>", self.keyboard_send)
        self.send_button = ttk.Button(
            composer,
            text="发送私信",
            style="Accent.TButton",
            command=lambda: guarded(self, self.send_message),
        )
        self.send_button.pack(anchor="e", pady=8)
        self.history.pack(fill="both", expand=True)
        self.refresh()
        self.receipt_timer = self.after(2000, self.poll_receipt)
        self.bind("<Destroy>", self.stop_poll)

    def stop_poll(self, event):
        """Release the page-local timer when navigating away."""
        if event.widget == self and self.receipt_timer is not None:
            self.after_cancel(self.receipt_timer)
            self.receipt_timer = None

    def poll_receipt(self):
        """Observe read receipts without marking unopened messages read."""
        try:
            self.history.show_receipt(latest_read_message(self.actor, self.peer))
        except (ValueError, sqlite3.Error):
            return
        self.receipt_timer = self.after(2000, self.poll_receipt)

    def refresh(self, older=False):
        """Load the newest or preceding 100 rows without discarding an unsent draft."""
        data = conversation(self.actor, self.peer, self.before if older else None)
        rows = data["rows"]
        self.history.render(rows, self.actor, data["peer_name"], data["avatars"], older)
        self.history.show_receipt(latest_read_message(self.actor, self.peer))
        if rows:
            self.before = rows[0]["id"]
        self.older.configure(state="normal" if len(rows) == 100 else "disabled")
        self.send_button.configure(state="normal" if data["can_send"] else "disabled")
        self.status.configure(text="" if data["can_send"] else "对方账号不可用，历史消息仍可查看。")
        if self.on_read:
            self.on_read()

    def send_message(self):
        """Clear the draft only after successful persistence."""
        send_direct_message(self.actor, self.peer, self.editor.get("1.0", "end-1c"))
        self.editor.delete("1.0", "end")
        self.refresh()

    def keyboard_send(self, _event):
        """Prevent Ctrl+Enter from inserting an extra newline after sending."""
        guarded(self, self.send_message)
        return "break"


class ChatPage(ttk.Frame):
    """A dedicated in-page conversation, independent of the seller storefront."""

    def __init__(
        self, parent, actor, peer, product_title="", back_label="← 返回商品详情", on_back=None
    ):
        # Validate before mounting the overlay; ChatPanel rechecks participant access.
        data = conversation(actor, peer)
        super().__init__(parent, padding=16)
        self.on_back = on_back
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        ttk.Button(self, text=back_label, command=self.go_back).pack(anchor="w", pady=(0, 10))
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        avatar = ttk.Label(header)
        avatar.photo = avatar_photo(self, peer, data["avatars"].get(peer, ""), (48, 48))
        avatar.configure(image=avatar.photo)
        avatar.pack(side="left", padx=(0, 12))
        ttk.Label(header, text=f"与 {data['peer_name']} 的对话", style="Title.TLabel").pack(
            anchor="w"
        )
        if product_title:
            ttk.Label(
                header, text=f"正在咨询：{product_title}", style="Sub.TLabel", wraplength=850
            ).pack(anchor="w")
        self.chat = ChatPanel(self, actor, peer)
        self.chat.pack(fill="both", expand=True)
        self.chat.editor.focus_set()
        self.bind("<Escape>", lambda event: self.go_back())

    def go_back(self):
        """Return to the caller and refresh its unread indicators."""
        callback = self.on_back
        self.destroy()
        if callback:
            callback()


class InboxPage(ttk.Frame):
    """Expose private replies through the persistent message-center navigation."""

    def __init__(self, parent, actor):
        super().__init__(parent, padding=12)
        self.actor = actor
        ttk.Button(self, text="刷新会话", command=lambda: guarded(self, self.refresh)).pack(
            anchor="w", pady=6
        )
        ttk.Button(self, text="全部已读", command=lambda: guarded(self, self.read_all)).pack(
            anchor="w", pady=6
        )
        self.table = DataTable(
            self,
            [
                ("name", "联系人", 160),
                ("content", "最近消息", 400),
                ("time", "时间", 150),
            ],
        )
        enable_unread_dots(self.table)
        self.table.pack(fill="x")
        self.table.tree.configure(height=4)
        self.table.tree.bind("<<TreeviewSelect>>", lambda event: guarded(self, self.open_chat))
        self.slot = ttk.Frame(self)
        self.slot.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        """Refresh only the list; opening a conversation marks its incoming rows read."""
        rows = inbox(self.actor)
        self.table.fill(
            [
                (
                    row["peer_id"],
                    (
                        row["username"],
                        row["content"][:60],
                        local_time(row["created_at"]),
                    ),
                )
                for row in rows
            ]
        )

        for row in rows:
            set_unread_dot(self.table, row["peer_id"], row["unread"] > 0)

    def read_all(self):
        """Explicitly clear all incoming dots, without pretending to open each chat."""
        mark_all_messages_read(self.actor)
        self.refresh()

    def update_dots(self):
        """Keep older unloaded unread messages represented until read or cleared."""
        for row in inbox(self.actor):
            if self.table.tree.exists(str(row["peer_id"])):
                set_unread_dot(self.table, row["peer_id"], row["unread"] > 0)

    def open_chat(self):
        """Never supply an unrelated sender/recipient pair from UI state."""
        if not self.table.tree.selection():
            return
        peer = self.table.selected()
        panel = ChatPanel(self.slot, self.actor, peer, on_read=self.update_dots)
        for widget in self.slot.winfo_children():
            if widget != panel:
                widget.destroy()
        panel.pack(fill="both", expand=True)
        self.update_dots()


class SellerPage(tk.Frame):
    """Public information and public inventory, with self-only editing controls."""

    def __init__(self, parent, actor, seller_id, overlay=True, detail_factory=None):
        data = seller_profile(actor, seller_id)
        super().__init__(parent, bg=BG)
        self.actor, self.seller_id, self.page = actor, seller_id, 1
        self.detail_factory = detail_factory
        if overlay:
            self.place(x=0, y=0, relwidth=1, relheight=1)
            self.lift()
            ttk.Button(self, text="← 返回商品详情", command=self.destroy).pack(
                anchor="w", padx=20, pady=10
            )
        header = tk.Frame(self, bg=PAPER, highlightbackground="#edcdb7", highlightthickness=1)
        header.pack(fill="x", padx=20, pady=10)
        self.avatar = tk.Label(header, bg=PAPER)
        self.avatar.photo = avatar_photo(self, seller_id, data["avatar_path"], (72, 72))
        self.avatar.configure(image=self.avatar.photo)
        self.avatar.pack(side="left", anchor="n", padx=16, pady=16)
        info = tk.Frame(header, bg=PAPER)
        info.pack(side="left", fill="both", expand=True)
        header = info
        title = data["nickname"] or data["username"]
        tk.Label(
            header, text=f"{title} 的主页", font=("Microsoft YaHei", 22), bg=PAPER, fg=INK
        ).pack(anchor="w", padx=18, pady=(12, 6))
        ttk.Label(
            header,
            text=(
                f"账号：{data['username']}    加入时间：{local_time(data['joined_at']).split()[0]}    "
                f"所在地（用户填写）：{data['region'] or '未填写'}"
            ),
            background=PAPER,
        ).pack(anchor="w", padx=18, pady=5)
        ttk.Label(
            header,
            text="IP属地：未获取（本地离线版未接入可信来源）",
            style="Sub.TLabel",
            background=PAPER,
        ).pack(anchor="w", padx=18, pady=5)
        ttk.Label(
            header,
            text=data["bio"] or "这个人还没有填写个人简介。",
            wraplength=900,
            background=PAPER,
        ).pack(anchor="w", padx=18, pady=5)
        rate = f"{data['conversion']:.1%}" if data["conversion"] is not None else "暂无数据"
        ttk.Label(
            header,
            text=f"在售 {data['selling']} 件    累计发布 {data['published']} 件    已成交 {data['sold']} 件    成交率 {rate}",
            foreground=ACCENT,
            background=PAPER,
        ).pack(anchor="w", padx=18, pady=8)
        ttk.Label(
            header,
            text="成交率口径：当前已成交商品数 ÷ 累计首次发布商品数；重复发布不重复计数，更正成交后重算。",
            background=PAPER,
            style="Sub.TLabel",
        ).pack(anchor="w", padx=18, pady=(0, 12))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        tabs = ttk.Notebook(body)
        tabs.pack(side="left", fill="both", expand=True)
        products = ttk.Frame(tabs, padding=12)
        tabs.add(products, text="在售商品")
        self.table = DataTable(
            products,
            [("title", "商品", 350), ("category", "分类", 120), ("price", "价格（元）", 100)],
        )
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", lambda event: guarded(self, self.open_product))
        footer = ttk.Frame(products)
        footer.pack(fill="x", pady=8)
        ttk.Button(
            footer, text="查看商品详情", command=lambda: guarded(self, self.open_product)
        ).pack(side="left")
        self.previous = ttk.Button(footer, text="上一页", command=lambda: self.turn(-1))
        self.previous.pack(side="left", padx=8)
        self.next_button = ttk.Button(footer, text="下一页", command=lambda: self.turn(1))
        self.next_button.pack(side="left")
        self.count = ttk.Label(footer)
        self.count.pack(side="left", padx=12)
        if actor == seller_id:
            ttk.Label(
                header,
                text="收到的私信可在「消息中心 → 私信会话」查看。",
                background=PAPER,
                style="Sub.TLabel",
            ).pack(anchor="w", padx=18, pady=6)
            edit = ttk.Frame(tabs, padding=18)
            tabs.add(edit, text="编辑我的公开资料")
            self.fields = []
            for row, (label, value) in enumerate(
                (
                    ("昵称（30字）", data["nickname"]),
                    ("个人简介（300字）", data["bio"]),
                    ("所在地（自愿填写，30字）", data["region"]),
                )
            ):
                ttk.Label(edit, text=label).grid(row=row, column=0, sticky="w", pady=8)
                field = ttk.Entry(edit, width=60)
                field.insert(0, value)
                field.grid(row=row, column=1, sticky="ew", pady=8)
                self.fields.append(field)
            ttk.Button(
                edit, text="更换头像", command=lambda: guarded(self, self.choose_avatar)
            ).grid(row=3, column=0, sticky="w", pady=10)
            self.saved = ttk.Label(edit, style="Sub.TLabel")
            self.saved.grid(row=4, column=0, columnspan=2, sticky="w")
            ttk.Button(
                edit, text="保存公开资料", command=lambda: guarded(self, self.save_profile)
            ).grid(row=3, column=1, sticky="e", pady=10)
        self.refresh()

    def choose_avatar(self):
        """Store a validated local copy, leaving the old avatar intact on failure."""
        source = filedialog.askopenfilename(
            parent=self, title="选择头像", filetypes=[("图片", "*.jpg *.jpeg *.png")]
        )
        if not source:
            return
        relative = update_avatar(self.actor, source)
        self.avatar.photo = avatar_photo(self, self.actor, relative, (72, 72))
        self.avatar.configure(image=self.avatar.photo)
        self.saved.configure(text="头像已保存。")

    def save_profile(self):
        """Persist only this account; refreshed header appears when reopening the page."""
        update_profile(self.actor, *(entry.get() for entry in self.fields))
        self.saved.configure(text="已保存，重新进入主页可查看最新公开资料。")

    def refresh(self):
        """Never include private drafts, blocked items or another seller's products."""
        rows, total = search_products(self.actor, seller_id=self.seller_id, page=self.page)
        self.table.fill(
            [
                (row["id"], (row["title"], row["category_name"], price(row["price_cents"])))
                for row in rows
            ]
        )
        self.count.configure(text=f"第{self.page}页 · 共{total}件" if total else "暂无在售商品")
        self.previous.configure(state="normal" if self.page > 1 else "disabled")
        self.next_button.configure(state="normal" if self.page * 8 < total else "disabled")

    def turn(self, step):
        """Keep pagination scoped to this storefront."""
        self.page += step
        guarded(self, self.refresh)

    def open_product(self):
        """Reuse the current-window detail view without a circular import at startup."""
        if self.detail_factory is None:
            raise ValueError("商品详情入口未配置。")
        self.detail_factory(self, self.actor, self.table.selected())
