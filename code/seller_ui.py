"""In-page seller storefront, voluntary profiles and private-message views."""

import json
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
    send_product_message,
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
    thumbnail,
    stored_image,
)


def local_time(value):
    """Render recorded UTC events in the same UTC+8 used by reports."""
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(timezone(timedelta(hours=8)))
        .strftime("%Y-%m-%d %H:%M")
    )


CHAT_BG = "#f3f6f8"
OUTGOING = "#ffe4d4"


class RoundedBubble(tk.Canvas):
    """Render native wrapped text on a rounded vector bubble, without image assets."""

    def __init__(self, parent, text, mine, wraplength):
        super().__init__(parent, bg=CHAT_BG, highlightthickness=0, bd=0)
        self.value = text
        self.fill_color = OUTGOING if mine else PAPER
        self.text_item = self.create_text(
            12,
            10,
            text=text,
            anchor="nw",
            fill="#24282b",
            font=("Microsoft YaHei", 12),
            width=wraplength,
        )
        self.shape = self.create_polygon(
            0, 0, 1, 0, 1, 1, 0, 1, smooth=True, fill=self.fill_color, outline=""
        )
        self.tag_lower(self.shape)
        self.reflow(wraplength)

    def reflow(self, width):
        """Size the canvas to the actual text instead of stretching short messages."""
        self.itemconfigure(self.text_item, width=width)
        bounds = self.bbox(self.text_item)
        wide = max(36, bounds[2] + 12)
        high = max(40, bounds[3] + 10)
        radius = 10
        self.coords(
            self.shape,
            radius,
            0,
            wide - radius,
            0,
            wide,
            0,
            wide,
            radius,
            wide,
            high - radius,
            wide,
            high,
            wide - radius,
            high,
            radius,
            high,
            0,
            high,
            0,
            high - radius,
            0,
            radius,
            0,
            0,
        )
        super().configure(width=wide, height=high)

    def configure(self, cnf=None, **options):
        """Accept the same wraplength operation used by responsive message rows."""
        wrap = options.pop("wraplength", None)
        result = super().configure(cnf, **options)
        if wrap is not None:
            self.reflow(wrap)
        return result

    def cget(self, key):
        """Expose the displayed text for accessibility and native-widget checks."""
        return self.value if key == "text" else super().cget(key)


class ProductMessageCard(tk.Frame):
    """Keep the sent title/price/image visible even when current content changes."""

    def __init__(self, parent, snapshot, mine, on_open):
        color = OUTGOING if mine else PAPER
        super().__init__(parent, bg=color, padx=12, pady=10, cursor="hand2", takefocus=True)
        self.snapshot = snapshot
        self.title = tk.Label(
            self,
            text=snapshot["title"],
            bg=color,
            fg=INK,
            font=("Microsoft YaHei", 11, "bold"),
            wraplength=260,
            justify="left",
        )
        self.title.pack(anchor="w")
        image = tk.Label(self, text="暂无商品图片", bg=color, fg="#8c969f")
        if snapshot.get("image"):
            try:
                image.photo = thumbnail(self, stored_image(snapshot["image"]), (180, 110))
                image.configure(image=image.photo, text="")
            except (OSError, ValueError):
                image.configure(text="图片暂不可用")
        image.pack(anchor="w", pady=6)
        tk.Label(self, text="¥ " + price(snapshot["price_cents"]), bg=color, fg=ACCENT).pack(
            anchor="w"
        )
        tk.Label(
            self,
            text="发送时的商品信息 · 点击查看当前详情",
            bg=color,
            fg="#8c969f",
            font=("Microsoft YaHei", 8),
            wraplength=260,
        ).pack(anchor="w", pady=(6, 0))
        for widget in [self] + self.winfo_children():
            widget.bind("<Button-1>", lambda event: on_open(snapshot["id"]) if on_open else None)
        self.bind("<Return>", lambda event: on_open(snapshot["id"]) if on_open else None)

    def configure(self, cnf=None, **options):
        """Follow the same responsive sizing interface as text bubbles."""
        width = options.pop("wraplength", None)
        if width is not None:
            for widget in self.winfo_children():
                if isinstance(widget, tk.Label):
                    widget.configure(wraplength=min(260, width))
        return super().configure(cnf, **options)


class BubbleHistory(ttk.Frame):
    """Scrollable, correctly parented message rows with left/right speech bubbles."""

    def __init__(self, parent):
        super().__init__(parent)
        self.on_product = None
        self.canvas = tk.Canvas(
            self, background=CHAT_BG, highlightthickness=0, width=260, height=120
        )
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=CHAT_BG)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.messages = []
        self.render_signature = None
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
        width = min(event.width, 880)
        self.canvas.itemconfigure(self.window, width=width)
        self.canvas.coords(self.window, max(0, (event.width - width) / 2), 0)
        for bubble in self.bubbles.values():
            bubble.configure(wraplength=max(80, int(width * 0.68) - 80))

    def wheel(self, event):
        """Scroll only this conversation, without global bindings."""
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def show_receipt(self, message_id):
        """Show 'read' only beneath the latest outgoing bubble; otherwise stay blank."""
        bubble = self.bubbles.get(message_id)
        if self.receipt is not None and self.receipt.winfo_exists():
            if bubble is not None and self.receipt.master == bubble.master:
                return
            self.receipt.destroy()
        self.receipt = None
        if bubble is not None:
            at_bottom = self.canvas.yview()[1] >= 0.99
            self.receipt = tk.Label(
                bubble.master, text="已读", bg=CHAT_BG, fg="#9ba4ac", font=("Microsoft YaHei", 8)
            )
            self.receipt.pack(anchor="e", pady=(3, 0))
            self.update_idletasks()
            self.update_region()
            if at_bottom:
                self.canvas.yview_moveto(1)

    def render(self, rows, actor, peer_name, avatars, older=False):
        """Show actual persisted messages and keep the reading position on older loads."""
        signature = (rows, actor, peer_name, avatars)
        if not older and signature == getattr(self, "render_signature", None):
            return
        self.render_signature = signature if not older else None
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
                self.content, text="还没有聊天记录，向对方打个招呼吧", bg=CHAT_BG, fg="#888888"
            ).pack(pady=25)
        previous_time = None
        for row in self.messages:
            mine = row["sender_id"] == actor
            stamp = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            if previous_time is None or (stamp - previous_time).total_seconds() >= 300:
                tk.Label(
                    self.content,
                    text=local_time(row["created_at"]),
                    bg=CHAT_BG,
                    fg="#a1aab2",
                    font=("Microsoft YaHei", 8),
                ).pack(pady=(18, 12))
            previous_time = stamp
            line = tk.Frame(self.content, bg=CHAT_BG)
            line.pack(fill="x", padx=18, pady=(0, 16))
            avatar = tk.Label(line, bg=CHAT_BG)
            avatar.photo = avatar_photo(
                self, row["sender_id"], avatars.get(row["sender_id"], ""), (38, 38)
            )
            avatar.configure(image=avatar.photo)
            avatar.pack(side="right" if mine else "left", anchor="n", padx=8)
            group = tk.Frame(line, bg=CHAT_BG)
            group.pack(side="right" if mine else "left", anchor="n")
            if not mine:
                tk.Label(
                    group, text=peer_name, bg=CHAT_BG, fg="#8c969f", font=("Microsoft YaHei", 9)
                ).pack(anchor="w", pady=(0, 5))
            if row.get("product_snapshot"):
                snapshot = json.loads(row["product_snapshot"])
                bubble = ProductMessageCard(group, snapshot, mine, self.on_product)
            else:
                bubble = RoundedBubble(
                    group,
                    row["content"],
                    mine,
                    max(80, int(min(self.canvas.winfo_width(), 880) * 0.68) - 80),
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


class ChatPanel(tk.Frame):
    """Read and send one participant-scoped conversation, with explicit refresh."""

    def __init__(self, parent, actor, peer, on_read=None, tools_parent=None):
        super().__init__(parent, bg=CHAT_BG)
        self.on_read = on_read
        self.actor, self.peer, self.before = actor, peer, None
        if tools_parent is None:
            tools_parent = tk.Frame(self, bg=CHAT_BG, padx=18, pady=8)
            tools_parent.pack(fill="x")
        tk.Button(
            tools_parent,
            text="刷新",
            command=lambda: guarded(self, self.refresh),
            bg=tools_parent.cget("background"),
            fg="#8c969f",
            activebackground=PAPER,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=10,
            pady=5,
        ).pack(side="right")
        self.older = tk.Button(
            tools_parent,
            text="更早记录",
            command=lambda: guarded(self, lambda: self.refresh(True)),
            bg=tools_parent.cget("background"),
            fg="#8c969f",
            activebackground=PAPER,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=10,
            pady=5,
        )
        self.older.pack(side="right")
        composer = tk.Frame(self, bg=PAPER, padx=18, pady=12)
        composer.pack(side="bottom", fill="x")
        input_row = tk.Frame(composer, bg=PAPER)
        input_row.pack(fill="x")
        self.send_button = tk.Button(
            input_row,
            text="发送",
            command=lambda: guarded(self, self.send_message),
            bg="#ff6b27",
            fg=PAPER,
            activebackground="#ed5818",
            activeforeground=PAPER,
            relief="flat",
            bd=0,
            font=("Microsoft YaHei", 11),
            padx=24,
            pady=10,
            cursor="hand2",
        )
        self.send_button.pack(side="right", padx=(12, 0))
        input_border = tk.Frame(
            input_row,
            bg="#f5f7f9",
            padx=12,
            pady=8,
            highlightbackground="#e7ebef",
            highlightthickness=1,
        )
        input_border.pack(side="left", fill="x", expand=True)
        self.editor = tk.Text(
            input_border,
            height=2,
            width=1,
            wrap="word",
            font=("Microsoft YaHei", 11),
            bg="#f5f7f9",
            fg="#24282b",
            insertbackground="#24282b",
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.editor.pack(fill="x", expand=True)
        self.draft_store = self.winfo_toplevel()
        if not hasattr(self.draft_store, "chat_drafts"):
            self.draft_store.chat_drafts = {}
        self.draft_key = (actor, peer)
        self.editor.insert("1.0", self.draft_store.chat_drafts.get(self.draft_key, ""))
        self.editor.edit_modified(False)
        self.editor.bind("<<Modified>>", self.remember_draft)
        self.editor.bind("<Control-Return>", self.keyboard_send)
        footer = tk.Frame(composer, bg=PAPER)
        footer.pack(fill="x", pady=(6, 0))
        tk.Label(
            footer,
            text="Enter 换行 · Ctrl+Enter 发送",
            bg=PAPER,
            fg="#a2abb4",
            font=("Microsoft YaHei", 8),
        ).pack(side="left")
        self.status = tk.Label(footer, bg=PAPER, fg="#a2abb4", font=("Microsoft YaHei", 8))
        self.status.pack(side="right")
        self.history = BubbleHistory(self)
        self.history.pack(fill="both", expand=True)
        self.refresh()
        self.receipt_timer = self.after(2000, self.poll_receipt)
        self.bind("<Destroy>", self.stop_poll)

    def remember_draft(self, _event=None):
        """Keep only unsent text in session memory, scoped to actor and recipient."""
        if self.editor.edit_modified():
            value = self.editor.get("1.0", "end-1c")
            if value:
                self.draft_store.chat_drafts[self.draft_key] = value
            else:
                self.draft_store.chat_drafts.pop(self.draft_key, None)
            self.editor.edit_modified(False)

    def stop_poll(self, event):
        """Release the page-local timer when navigating away."""
        if event.widget == self and self.receipt_timer is not None:
            self.after_cancel(self.receipt_timer)
            self.receipt_timer = None

    def poll_receipt(self):
        """Observe read receipts without marking unopened messages read."""
        if not self.winfo_ismapped():
            self.receipt_timer = self.after(2000, self.poll_receipt)
            return
        try:
            self.history.show_receipt(latest_read_message(self.actor, self.peer))
        except (ValueError, sqlite3.Error):
            return
        self.receipt_timer = self.after(2000, self.poll_receipt)

    def refresh(self, older=False):
        """Load the newest or preceding 100 rows without discarding an unsent draft."""
        data = conversation(self.actor, self.peer, self.before if older else None)
        rows = data["rows"]
        self.history.render(
            rows,
            self.actor,
            data.get("peer_display_name", data["peer_name"]),
            data["avatars"],
            older,
        )
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
        self.draft_store.chat_drafts.pop(self.draft_key, None)
        self.refresh()

    def keyboard_send(self, _event):
        """Prevent Ctrl+Enter from inserting an extra newline after sending."""
        guarded(self, self.send_message)
        return "break"


class ChatPage(tk.Frame):
    """A dedicated in-page conversation, independent of the seller storefront."""

    def __init__(
        self,
        parent,
        actor,
        peer,
        product_title="",
        back_label="← 返回商品详情",
        on_back=None,
        product_id=None,
    ):
        # Validate before mounting the overlay; ChatPanel rechecks participant access.
        data = conversation(actor, peer)
        super().__init__(parent, bg=CHAT_BG)
        self.on_back = on_back
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        header = tk.Frame(self, bg=PAPER, padx=18, pady=12)
        header.pack(fill="x")
        tk.Button(
            header,
            text=back_label,
            command=self.go_back,
            bg=PAPER,
            fg="#49535b",
            activebackground=PAPER,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Microsoft YaHei", 10),
            padx=8,
        ).pack(side="left", padx=(0, 14))
        avatar = tk.Label(header, bg=PAPER)
        avatar.photo = avatar_photo(self, peer, data["avatars"].get(peer, ""), (36, 36))
        avatar.configure(image=avatar.photo)
        avatar.pack(side="left", padx=(0, 12))
        name = tk.Frame(header, bg=PAPER)
        name.pack(side="left", fill="x", expand=True)
        tk.Label(
            name,
            text=data.get("peer_display_name", data["peer_name"]),
            font=("Microsoft YaHei", 16, "bold"),
            fg="#232a30",
            bg=PAPER,
            anchor="w",
        ).pack(fill="x")
        if product_title:
            tk.Label(
                name,
                text=f"正在咨询：{product_title}",
                bg=PAPER,
                fg="#99a2aa",
                font=("Microsoft YaHei", 9),
                wraplength=580,
                anchor="w",
            ).pack(fill="x", pady=(3, 0))
        tools = tk.Frame(header, bg=PAPER)
        tools.pack(side="right")
        tk.Frame(self, height=1, bg="#e8edf1").pack(fill="x")
        self.chat = ChatPanel(self, actor, peer, tools_parent=tools)
        self.chat.history.on_product = self.open_product_card
        self.chat.refresh()
        if product_id is not None:
            self.product_button = tk.Button(
                header,
                text="发送此商品",
                bg=OUTGOING,
                fg=ACCENT,
                relief="flat",
                command=lambda: guarded(self, lambda: self.send_product(actor, peer, product_id)),
            )
            self.product_button.pack(side="right", padx=10)
        self.chat.pack(fill="both", expand=True)
        self.chat.editor.focus_set()
        self.bind("<Escape>", lambda event: self.go_back())

    def on_resume(self):
        """Reconcile the shared draft when this peer is open through another entry."""
        value = self.chat.draft_store.chat_drafts.get(self.chat.draft_key, "")
        if self.chat.editor.get("1.0", "end-1c") != value:
            self.chat.editor.delete("1.0", "end")
            self.chat.editor.insert("1.0", value)
            self.chat.editor.edit_modified(False)

    def send_product(self, actor, peer, product_id):
        """Persist a card without consuming any unsent text draft."""
        send_product_message(actor, peer, product_id)
        self.chat.refresh()

    def open_product_card(self, product_id):
        """Resolve current visibility again; never expose private content from a snapshot."""
        # Deferred import avoids the market/storefront module dependency cycle.
        from market_ui import ProductDetail  # pylint: disable=import-outside-toplevel,cyclic-import

        guarded(self, lambda: ProductDetail(self, self.chat.actor, product_id))

    def go_back(self):
        """Return to the caller and refresh its unread indicators."""
        callback = self.on_back
        self.chat.remember_draft()
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
