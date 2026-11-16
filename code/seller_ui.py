"""In-page seller storefront, voluntary profiles and private-message views."""

import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import ttk

from catalog import search_products
from community import conversation, inbox, seller_profile, send_direct_message, update_profile
from core import price
from ui_common import ACCENT, BG, INK, PAPER, DataTable, guarded


def local_time(value):
    """Render recorded UTC events in the same UTC+8 used by reports."""
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(timezone(timedelta(hours=8)))
        .strftime("%Y-%m-%d %H:%M")
    )


class ChatPanel(ttk.Frame):
    """Read and send one participant-scoped conversation, with explicit refresh."""

    def __init__(self, parent, actor, peer):
        super().__init__(parent, padding=12)
        self.actor, self.peer, self.before = actor, peer, None
        self.history = tk.Text(
            self, height=10, wrap="word", bg=PAPER, fg=INK, relief="flat", state="disabled"
        )
        scrollbar = ttk.Scrollbar(self, command=self.history.yview)
        self.history.configure(yscrollcommand=scrollbar.set)
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
        history_frame = ttk.Frame(self)
        history_frame.pack(fill="both", expand=True)
        # Reparenting Tk widgets is unsupported; pack into their original parent using in_.
        self.history.pack(in_=history_frame, side="left", fill="both", expand=True)
        scrollbar.pack(in_=history_frame, side="right", fill="y")
        ttk.Label(
            self,
            text="私信（最多1000字）：Enter换行，Ctrl+Enter发送；消息仅在本机数据库内流转。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)
        self.editor = tk.Text(self, height=3, wrap="word", font=("Microsoft YaHei", 10))
        self.editor.pack(fill="x")
        self.editor.bind("<Control-Return>", self.keyboard_send)
        self.send_button = ttk.Button(
            self,
            text="发送私信",
            style="Accent.TButton",
            command=lambda: guarded(self, self.send_message),
        )
        self.send_button.pack(anchor="e", pady=8)
        self.refresh()

    def refresh(self, older=False):
        """Load the newest or preceding 100 rows without discarding an unsent draft."""
        data = conversation(self.actor, self.peer, self.before if older else None)
        rows = data["rows"]
        self.history.configure(state="normal")
        if not older:
            self.history.delete("1.0", "end")
        text = "".join(
            f"{'我' if row['sender_id'] == self.actor else data['peer_name']}  "
            f"{local_time(row['created_at'])}\n{row['content']}\n\n"
            for row in rows
        )
        self.history.insert(
            "1.0" if older else "end", text or "还没有消息，可以先向卖家询问商品情况。\n"
        )
        self.history.configure(state="disabled")
        if not older:
            self.history.see("end")
        if rows:
            self.before = rows[0]["id"]
        self.older.configure(state="normal" if len(rows) == 100 else "disabled")
        self.send_button.configure(state="normal" if data["can_send"] else "disabled")
        self.status.configure(text="" if data["can_send"] else "对方账号不可用，历史消息仍可查看。")

    def send_message(self):
        """Clear the draft only after successful persistence."""
        send_direct_message(self.actor, self.peer, self.editor.get("1.0", "end-1c"))
        self.editor.delete("1.0", "end")
        self.refresh()
        self.status.configure(text="已发送")

    def keyboard_send(self, _event):
        """Prevent Ctrl+Enter from inserting an extra newline after sending."""
        guarded(self, self.send_message)
        return "break"


class InboxPage(ttk.Frame):
    """Expose private replies through the persistent message-center navigation."""

    def __init__(self, parent, actor):
        super().__init__(parent, padding=12)
        self.actor = actor
        ttk.Button(self, text="刷新会话", command=lambda: guarded(self, self.refresh)).pack(
            anchor="w", pady=6
        )
        self.table = DataTable(
            self,
            [
                ("name", "联系人", 160),
                ("unread", "未读", 60),
                ("content", "最近消息", 400),
                ("time", "时间", 150),
            ],
        )
        self.table.pack(fill="x")
        self.table.tree.configure(height=4)
        self.table.tree.bind("<<TreeviewSelect>>", lambda event: guarded(self, self.open_chat))
        self.slot = ttk.Frame(self)
        self.slot.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        """Refresh only the list; opening a conversation marks its incoming rows read."""
        self.table.fill(
            [
                (
                    row["peer_id"],
                    (
                        row["username"],
                        row["unread"],
                        row["content"][:60],
                        local_time(row["created_at"]),
                    ),
                )
                for row in inbox(self.actor)
            ]
        )

    def open_chat(self):
        """Never supply an unrelated sender/recipient pair from UI state."""
        if not self.table.tree.selection():
            return
        peer = self.table.selected()
        panel = ChatPanel(self.slot, self.actor, peer)
        for widget in self.slot.winfo_children():
            if widget != panel:
                widget.destroy()
        panel.pack(fill="both", expand=True)


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
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=20, pady=(0, 12))
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
        if actor != seller_id:
            chat = ttk.Frame(tabs)
            tabs.add(chat, text="私信卖家")

            def load_chat(_event=None):
                if tabs.select() == str(chat) and not chat.winfo_children():
                    guarded(
                        chat,
                        lambda: ChatPanel(chat, actor, seller_id).pack(fill="both", expand=True),
                    )

            tabs.bind("<<NotebookTabChanged>>", load_chat)
            ttk.Button(header, text="私信卖家 →", command=lambda: tabs.select(chat)).pack(
                anchor="e", padx=18, pady=8
            )
        else:
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
            self.saved = ttk.Label(edit, style="Sub.TLabel")
            self.saved.grid(row=4, column=0, columnspan=2, sticky="w")
            ttk.Button(
                edit, text="保存公开资料", command=lambda: guarded(self, self.save_profile)
            ).grid(row=3, column=1, sticky="e", pady=10)
        self.refresh()

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
