"""Buyer and seller reservation progress views."""

import json
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from governance import correct_sale, resolve_dispute
from trades import (
    LABELS,
    cancel_reservation,
    complete_trade,
    confirm_reservation,
    list_reservations,
    register_delivery,
    reject_reservation,
    respond_cancel,
    transaction_detail,
)
from ui_common import (
    ACCENT,
    BG,
    INK,
    PAPER,
    MUTED,
    ProductRows,
    navigate_to,
    display_value,
    guarded,
    stored_image,
    thumbnail,
)

RESERVATION_GROUPS = (
    ("all", "全部", set(LABELS)),
    ("waiting", "待确认", {"waiting"}),
    ("trading", "交易中", {"confirmed", "delivered"}),
    ("issues", "取消 / 争议", {"cancel_requested", "manual"}),
    ("completed", "已完成", {"completed"}),
    ("ended", "已关闭", {"cancelled", "rejected", "expired", "corrected"}),
)


def reservation_status(scope, actor, row):
    """Keep precise, participant-relative progress visible within broad groups."""
    if scope == "admin":
        return LABELS[row["status"]]
    if row["status"] == "cancel_requested":
        return "等待对方回复" if row["cancel_by"] == actor else "待我处理"
    labels = {
        "waiting": "待我确认" if scope == "seller" else "待卖家确认",
        "confirmed": "待交付" if scope == "seller" else "待收货",
        "delivered": "待买家确认" if scope == "seller" else "待确认完成",
        "manual": "管理员处理中",
    }
    return labels.get(row["status"], LABELS[row["status"]])


def reservation_actions(scope, actor, row):
    """Select meaningful UI actions; authoritative services still recheck all rules."""
    if not row:
        return []
    state = row["status"]
    if scope == "admin":
        resolutions = [("核实取消", "resolve_cancel"), ("核实继续交易", "resolve_continue")]
        return {
            "manual": resolutions,
            "cancel_requested": resolutions,
            "completed": [("更正错误成交", "correct")],
        }.get(state, [])
    if actor != row["buyer_id" if scope == "buyer" else "seller_id"]:
        return []
    actions = []
    if state == "waiting":
        if scope == "buyer":
            actions = [("取消预约", "cancel")]
        elif row.get("product_status") == "published" and not row.get("blocked"):
            actions = [("确认预约", "confirm"), ("拒绝预约", "reject")]
    elif state == "confirmed":
        actions = [("申请取消", "cancel")]
        if scope == "seller" and row.get("product_status") == "reserved":
            actions.insert(0, ("登记交付", "deliver"))
    elif state == "delivered":
        actions = [("申请取消", "cancel")]
        if scope == "buyer" and row.get("product_status") == "reserved" and not row.get("blocked"):
            actions.insert(0, ("确认交易完成", "complete"))
    elif state == "cancel_requested" and row["cancel_by"] != actor:
        actions = [("同意取消", "agree"), ("不同意，转人工", "disagree")]
    return actions


class ReservationDetail(tk.Frame):
    """A read-only, in-page booking view built from authorized historical content."""

    def __init__(self, parent, actor, data, scope="buyer", admin_reason=""):
        super().__init__(parent, bg=BG)
        self.actor, self.data, self.scope, self.admin_reason = actor, data, scope, admin_reason
        self.photos = []
        self.picture_index = 0
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=22, pady=14)
        back = {"buyer": "← 返回我的预约", "seller": "← 返回卖家预约", "admin": "← 返回交易管理"}[
            scope
        ]
        tk.Button(
            header,
            text=back,
            command=self.destroy,
            bg=BG,
            fg=ACCENT,
            relief="flat",
            bd=0,
            cursor="hand2",
        ).pack(side="left")
        ttk.Button(header, text="刷新详情", command=lambda: guarded(self, self.reload)).pack(
            side="right"
        )
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(self, command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.body = tk.Frame(self.canvas, bg=BG)
        window = self.canvas.create_window(20, 0, window=self.body, anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(window, width=max(680, event.width - 40)),
        )
        self.body.bind(
            "<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        title = tk.Frame(self.body, bg=BG)
        title.pack(fill="x", pady=(0, 14))
        tk.Label(title, text="预约详情", font=("Microsoft YaHei", 22), bg=BG, fg=INK).pack(
            side="left"
        )
        tk.Label(
            title,
            text=reservation_status(scope, actor, data),
            bg="#fbe9d8",
            fg=ACCENT,
            padx=16,
            pady=7,
        ).pack(side="right")
        tk.Label(
            self.body,
            text=f"预约编号 {data['id']}   ·   创建于 {display_value(data['created_at'],'created_at')}",
            bg=BG,
            fg=MUTED,
        ).pack(anchor="w", pady=(0, 12))
        snapshot = data["snapshot"]
        card = self.section("预约时的商品")
        tk.Label(
            card, text="商品信息保存于发起预约时，后续修改不会改变这份记录。", bg=PAPER, fg=MUTED
        ).pack(anchor="w", pady=(0, 12))
        content = tk.Frame(card, bg=PAPER)
        content.pack(fill="both", expand=True)
        content.columnconfigure(1, weight=1)
        gallery = tk.Frame(content, bg=PAPER)
        gallery.grid(row=0, column=0, sticky="n", padx=(0, 24))
        self.large = tk.Label(gallery, bg="#f3ece3")
        self.large.pack()
        self.images = snapshot.get("images", [])
        strip = tk.Frame(gallery, bg=PAPER)
        strip.pack(pady=8)
        for index, value in enumerate(self.images):
            try:
                relative = value.get("file_path") if isinstance(value, dict) else value
                photo = thumbnail(self, stored_image(relative), (45, 45))
                self.photos.append(photo)
                tk.Button(
                    strip,
                    image=photo,
                    command=lambda position=index: self.show_image(position),
                    relief="flat",
                    bg=PAPER,
                    bd=1,
                ).pack(side="left", padx=3)
            except (OSError, ValueError, TypeError):
                tk.Button(
                    strip,
                    text=f"图片{index+1}",
                    command=lambda position=index: self.show_image(position),
                ).pack(side="left", padx=3)
        info = tk.Frame(content, bg=PAPER)
        info.grid(row=0, column=1, sticky="nsew")
        tk.Label(
            info,
            text=snapshot.get("title") or "商品标题未记录",
            font=("Microsoft YaHei", 20),
            bg=PAPER,
            fg=INK,
            wraplength=500,
            justify="left",
        ).pack(anchor="w")
        cents = snapshot.get("price_cents")
        tk.Label(
            info,
            text=f"¥ {cents/100:.2f}" if cents is not None else "价格未记录",
            font=("Microsoft YaHei", 24),
            bg=PAPER,
            fg=ACCENT,
        ).pack(anchor="w", pady=12)
        tags = " · ".join(
            str(snapshot.get(key) or "未注明") for key in ("condition_label", "shipping")
        )
        tk.Label(
            info,
            text=tags + (" · 可议价" if snapshot.get("negotiable") else ""),
            bg="#fff1e3",
            fg=ACCENT,
            padx=10,
            pady=5,
        ).pack(anchor="w")
        self.description = tk.Label(
            info,
            text=snapshot.get("description") or "暂无文字描述",
            bg=PAPER,
            fg=INK,
            wraplength=500,
            justify="left",
            anchor="w",
        )
        self.description.pack(fill="x", pady=14)
        info.bind(
            "<Configure>",
            lambda event: self.description.configure(wraplength=max(180, event.width)),
        )
        self.show_image(0)
        self.render_progress(data)
        people = self.section("交易双方与联系方式")
        self.field(people, "买家", data.get("buyer_name", f"用户 {data['buyer_id']}"))
        self.field(people, "卖家", data.get("seller_name", f"用户 {data['seller_id']}"))
        contact = data.get("contact")
        if isinstance(contact, list):
            contact = "；".join(f"账号 {row['id']}：{row['phone']}" for row in contact)
        self.contact_text = contact or "当前状态暂不可查看交易电话。"
        self.field(people, "交易电话", self.contact_text)
        tk.Label(
            people,
            text="平台记录预约及交易结果，付款和交付由双方线下协商。",
            bg=PAPER,
            fg=MUTED,
            wraplength=850,
        ).pack(anchor="w", pady=8)
        handling = self.section("取消与处理说明")
        self.field(handling, "处理原因", data.get("reason") or "暂无取消或争议处理记录。")
        if data.get("cancel_by"):
            self.field(
                handling, "申请方", "买家" if data["cancel_by"] == data["buyer_id"] else "卖家"
            )
        self.bind_scroll(self)
        self.bind("<Escape>", lambda event: self.destroy())
        self.focus_set()

    def render_progress(self, data):
        """Show actual milestone times, including closed or corrected histories."""
        progress = self.section("交易进度")
        steps = (
            ("发起预约", "created_at"),
            ("卖家确认", "confirmed_at"),
            ("登记交付", "delivered_at"),
            ("确认成交", "completed_at"),
        )
        for index, (label, key) in enumerate(steps):
            progress.columnconfigure(index, weight=1, uniform="step")
            cell = tk.Frame(progress, bg=PAPER)
            cell.grid(row=1, column=index, sticky="nsew", padx=8, pady=10)
            stamp = data.get(key)
            tk.Label(
                cell,
                text=f"{'●' if stamp else '○'}  {label}",
                bg=PAPER,
                fg=ACCENT if stamp else MUTED,
                font=("Microsoft YaHei", 11),
            ).pack(anchor="w")
            tk.Label(
                cell,
                text=display_value(stamp, key) if stamp else "尚未发生",
                bg=PAPER,
                fg=MUTED,
                wraplength=175,
                justify="left",
            ).pack(anchor="w", pady=6)
        if data["status"] in (
            "cancelled",
            "rejected",
            "expired",
            "corrected",
            "manual",
            "cancel_requested",
        ):
            tk.Label(
                progress,
                text=f"当前：{LABELS[data['status']]}，以上时间保留实际发生记录，以当前状态为准。",
                bg=PAPER,
                fg=ACCENT,
                wraplength=850,
            ).grid(row=2, column=0, columnspan=4, sticky="w", pady=8)

    def section(self, title):
        """Create a flat, bordered white information section."""
        card = tk.Frame(
            self.body,
            bg=PAPER,
            highlightbackground="#edcdb7",
            highlightthickness=1,
            padx=20,
            pady=16,
        )
        card.pack(fill="x", pady=(0, 16))
        # Progress uses grid inside its content; keep section title in its own parent.
        heading = tk.Label(card, text=title, bg=PAPER, fg=INK, font=("Microsoft YaHei", 13))
        heading.pack(anchor="w", pady=(0, 10))
        content = tk.Frame(card, bg=PAPER)
        content.pack(fill="both", expand=True)
        return content

    def field(self, parent, label, value):
        """Render readable labels and wrapped values rather than internal field names."""
        tk.Label(
            parent,
            text=f"{label}：{value}",
            bg=PAPER,
            fg=INK,
            wraplength=900,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=6)

    def show_image(self, index):
        """Keep original snapshot images available with missing-file fallback."""
        self.picture_index = index
        if not self.images:
            self.large.configure(image="", text="预约时未添加商品图片", width=30, height=14)
            return
        value = self.images[index]
        relative = value.get("file_path") if isinstance(value, dict) else value
        try:
            self.large.photo = thumbnail(self, stored_image(relative), (280, 280))
            self.large.configure(image=self.large.photo, text="", width=280, height=280)
        except (OSError, ValueError, TypeError):
            self.large.configure(image="", text="原图片缺失，无法预览", width=30, height=14)

    def bind_scroll(self, widget):
        """Allow scrolling from anywhere in a long detail view."""
        widget.bind(
            "<MouseWheel>", lambda event: self.canvas.yview_scroll(-int(event.delta / 120), "units")
        )
        for child in widget.winfo_children():
            self.bind_scroll(child)

    def reload(self):
        """Recheck current authorization and contact visibility when refreshing."""
        data = transaction_detail(self.actor, self.data["id"], self.admin_reason)
        ReservationDetail(self.master, self.actor, data, self.scope, self.admin_reason)
        self.destroy()


class ReservationsPage(ttk.Frame):
    """Display a caller-owned reservation list with role-checked actions."""

    def __init__(self, parent, actor, scope="buyer"):
        super().__init__(parent, padding=18)
        self.actor = actor
        self.scope = scope
        self.rows = {}
        title = {"buyer": "我的预约", "seller": "卖家预约管理", "admin": "交易争议与更正"}[scope]
        ttk.Label(self, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        self.group_key = "all"
        self.group_buttons = {}
        self.initialized = False
        filters = ttk.Frame(self)
        filters.pack(fill="x", pady=8)
        ttk.Button(filters, text="刷新", command=lambda: guarded(self, self.refresh)).pack(
            side="left", padx=6
        )
        self.detail_button = ttk.Button(
            filters,
            text="预约详情 / 快照",
            state="disabled",
            command=lambda: guarded(self, self.detail),
        )
        self.detail_button.pack(side="left")
        categories = ttk.Frame(self)
        categories.pack(fill="x", pady=(6, 14))
        for key, label, _ in RESERVATION_GROUPS:
            item = tk.Frame(categories, bg=BG)
            item.pack(side="left", padx=(0, 16))
            button = tk.Button(
                item,
                text=label,
                command=lambda value=key: self.choose_group(value),
                font=("Microsoft YaHei", 12),
                bg=BG,
                fg=INK,
                activebackground=BG,
                relief="flat",
                bd=0,
                padx=7,
                pady=8,
                cursor="hand2",
            )
            button.pack()
            underline = tk.Frame(item, height=2, bg=BG)
            underline.pack(fill="x")
            self.group_buttons[key] = (button, underline)

        self.action_hint = ttk.Label(
            self, text="先选择状态分类，再选中一条预约查看可用操作。", style="Sub.TLabel"
        )
        self.action_hint.pack(anchor="w")
        ttk.Label(
            self,
            text="以创建预约时的商品快照为准。确认预约后才能查看交易电话；取消和争议均保留记录。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)
        self.table = ProductRows(self, on_open=lambda key: self.detail())
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<CardSelected>>", self.show_actions)
        self.refresh()

    def on_resume(self):
        """Update live rows while keeping the existing session controls."""
        self.refresh()

    def refresh(self):
        """Refresh states/counts and retain the selected classification."""
        rows = list_reservations(self.actor, self.scope)
        self.rows = {row["id"]: row for row in rows}
        if not self.initialized:
            self.group_key = next(
                (
                    key
                    for key, _, states in RESERVATION_GROUPS
                    if key not in ("all", "completed", "ended")
                    and any(row["status"] in states for row in rows)
                ),
                "all",
            )
            self.initialized = True
        for key, label, states in RESERVATION_GROUPS:
            count = sum(row["status"] in states for row in rows)
            button, underline = self.group_buttons[key]
            button.configure(text=f"{label} {count}", fg=ACCENT if key == self.group_key else INK)
            underline.configure(bg=ACCENT if key == self.group_key else BG)
        self.fill_group()

    def choose_group(self, key):
        """Switch simplified visual categories without changing transaction states."""
        if key not in self.group_buttons:
            raise ValueError("预约分类无效。")
        self.group_key = key
        for value, (button, underline) in self.group_buttons.items():
            button.configure(fg=ACCENT if value == key else INK)
            underline.configure(bg=ACCENT if value == key else BG)
        self.fill_group()

    def fill_group(self):
        """Classify reservations; all ended states retain their precise row labels."""
        selection = self.table.selection()
        selected = selection[0] if selection else None
        states = next(states for key, _, states in RESERVATION_GROUPS if key == self.group_key)
        rows = [row for row in self.rows.values() if row["status"] in states]
        if self.group_key == "issues":
            rows.sort(
                key=lambda row: (
                    (
                        0
                        if row["status"] == "cancel_requested" and row["cancel_by"] != self.actor
                        else 1 if row["status"] == "cancel_requested" else 2
                    ),
                    -row["id"],
                )
            )
        handlers = self.operation_handlers()
        cards = []
        for row in rows:
            snapshot = json.loads(row["snapshot"])
            images = snapshot.get("images", [])
            cover = images[0] if images else None
            if isinstance(cover, dict):
                cover = cover.get("file_path")
            actions = [("预约详情 / 快照", self.detail)]
            actions += [
                (label, handlers[key])
                for label, key in reservation_actions(self.scope, self.actor, row)
            ]
            note = (
                "你已申请取消，等待对方处理。"
                if row["status"] == "cancel_requested" and row["cancel_by"] == self.actor
                else LABELS[row["status"]]
            )
            cards.append(
                {
                    "id": row["id"],
                    "title": snapshot["title"],
                    "image": cover,
                    "price": snapshot.get("price_cents"),
                    "status": reservation_status(self.scope, self.actor, row),
                    "subtitle": (
                        f"预约编号 {row['id']} · 买家 {row['buyer_name']} · "
                        f"{display_value(row['created_at'],'created_at')}\n{note}"
                    ),
                    "actions": actions,
                }
            )
        self.table.fill(
            cards,
            "暂时没有预约" if not self.rows else "该分类暂无预约",
            (
                "浏览喜欢的商品后，可以在详情页发起预约。"
                if self.scope == "buyer"
                else "收到买家预约后，会在这里显示；也可以先管理自己的商品。"
            ),
            (
                (lambda: self.choose_group("all"))
                if self.rows
                else (
                    lambda: navigate_to(self, "浏览商品" if self.scope == "buyer" else "我的商品")
                )
            ),
            (
                "查看全部预约"
                if self.rows
                else ("去浏览商品" if self.scope == "buyer" else "管理我的商品")
            ),
        )
        if selected in self.table.keys():
            self.table.select(selected)
        self.show_actions()
        if not rows:
            self.action_hint.configure(text="该分类暂无预约，可切换其他状态查看。")

    def show_actions(self, _event=None):
        """Rebuild only the selected reservation's valid action controls."""
        selection = self.table.selection()
        row = self.rows.get(int(selection[0])) if selection else None
        self.detail_button.configure(state="normal" if row else "disabled")
        actions = reservation_actions(self.scope, self.actor, row)
        hint = "选中一条预约后，显示该预约当前可用的操作。"
        if row:
            hint = f"当前状态：{reservation_status(self.scope,self.actor,row)}。"
            if row["status"] == "cancel_requested" and row["cancel_by"] == self.actor:
                hint += "你已申请取消，等待对方处理。"
            elif not actions:
                hint += "当前无需操作，可查看预约详情。"
        self.action_hint.configure(text=hint)

    def operation_handlers(self):
        """Share existing transactional handlers between inline card actions."""
        return {
            "confirm": self.confirm,
            "reject": self.reject,
            "cancel": self.cancel,
            "deliver": self.deliver,
            "complete": self.complete,
            "agree": lambda: self.respond(True),
            "disagree": lambda: self.respond(False),
            "resolve_cancel": lambda: self.resolve(True),
            "resolve_continue": lambda: self.resolve(False),
            "correct": self.correct,
        }

    def reason(self, title):
        """Ask for a required reason; cancellation leaves the operation untouched."""
        return simpledialog.askstring(title, "请填写原因或核实依据：", parent=self)

    def detail(self):
        """Inspect the immutable snapshot and authorized contact field."""
        key = self.table.selected()
        reason = self.reason("管理员访问依据") if self.scope == "admin" else ""
        if reason is None:
            return
        data = transaction_detail(self.actor, key, reason)
        ReservationDetail(self, self.actor, data, self.scope, reason)

    def confirm(self):
        """Confirm one buyer after explicit user intent."""
        key = self.table.selected()
        if messagebox.askyesno(
            "确认预约", "确认该买家后，其他等待预约将失效。是否继续？", parent=self
        ):
            confirm_reservation(self.actor, key)
            self.refresh()

    def reject(self):
        """Reject a selected waiting request."""
        key = self.table.selected()
        reason = self.reason("拒绝预约")
        if reason is not None:
            reject_reservation(self.actor, key, reason)
            self.refresh()

    def cancel(self):
        """Cancel intent or start bilateral cancellation."""
        key = self.table.selected()
        reason = self.reason("取消预约")
        if reason is not None:
            cancel_reservation(self.actor, key, reason)
            self.refresh()

    def respond(self, agree):
        """Respond as the other participant."""
        respond_cancel(self.actor, self.table.selected(), agree)
        self.refresh()

    def deliver(self):
        """Record actual offline delivery, leaving final confirmation to the buyer."""
        key = self.table.selected()
        if messagebox.askyesno("登记交付", "确认已实际完成线下交付？", parent=self):
            register_delivery(self.actor, key)
            self.refresh()

    def complete(self):
        """Confirm receipt and final completion."""
        key = self.table.selected()
        if messagebox.askyesno("确认完成", "确认已收到商品并完成交易？", parent=self):
            complete_trade(self.actor, key)
            self.refresh()

    def resolve(self, cancel):
        """Apply a reasoned administrator dispute resolution."""

        key = self.table.selected()
        reason = self.reason("核实争议")
        if reason is not None:
            resolve_dispute(self.actor, key, cancel, reason)
            self.refresh()

    def correct(self):
        """Append a correction instead of rewriting completed history."""

        key = self.table.selected()
        reason = self.reason("更正错误成交")
        if reason is not None:
            correct_sale(self.actor, key, reason)
            self.refresh()
