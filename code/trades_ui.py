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
from ui_common import ACCENT, BG, INK, ProductRows, TextWindow, display_value, guarded

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
        self.table.fill(cards)
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
        TextWindow(
            self,
            "预约详情与原始快照",
            {
                "预约编号": data["id"],
                "状态": LABELS[data["status"]],
                "创建时间（北京时间）": data["created_at"],
                "取消/处理原因": data["reason"],
                "交付登记时间": data["delivered_at"],
                "成交确认时间": data["completed_at"],
                "交易联系电话": data["contact"] or "当前状态不可查看",
                "预约时商品快照": data["snapshot"],
            },
        )

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
