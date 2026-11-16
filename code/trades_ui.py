"""Buyer and seller reservation progress views."""

import json
from tkinter import StringVar, messagebox, simpledialog, ttk

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
from ui_common import ProductRows, TextWindow, display_value, guarded

RESERVATION_GROUPS = (
    ("waiting", "待确认预约", {"waiting"}),
    ("confirmed", "待交付", {"confirmed"}),
    ("delivered", "待买家确认完成", {"delivered"}),
    ("cancel_requested", "取消协商中", {"cancel_requested"}),
    ("manual", "待管理员处理", {"manual"}),
    ("completed", "已完成", {"completed"}),
    ("ended", "已结束", {"cancelled", "rejected", "expired", "corrected"}),
    ("all", "全部预约", set(LABELS)),
)


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
        self.group_key = "waiting"
        self.group_text = StringVar(master=self)
        self.group_options = {}
        filters = ttk.Frame(self)
        filters.pack(fill="x", pady=8)
        ttk.Label(filters, text="按预约状态查看：").pack(side="left")
        self.group_box = ttk.Combobox(
            filters, textvariable=self.group_text, state="readonly", width=30
        )
        self.group_box.pack(side="left", padx=8)
        self.group_box.bind("<<ComboboxSelected>>", self.choose_group)
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
        first_load = not self.group_options
        self.rows = {row["id"]: row for row in rows}
        options = []
        for key, label, states in RESERVATION_GROUPS:
            count = sum(row["status"] in states for row in rows)
            text = f"{label}（{count}）"
            options.append(text)
            self.group_options[text] = key
        self.group_box.configure(values=options)
        if first_load:
            self.group_key = next(
                (
                    key
                    for key, _, states in RESERVATION_GROUPS
                    if any(row["status"] in states for row in rows)
                ),
                "waiting",
            )
        self.group_options = dict(zip(options, (group[0] for group in RESERVATION_GROUPS)))
        self.group_text.set(
            next(text for text, key in self.group_options.items() if key == self.group_key)
        )
        self.fill_group()

    def choose_group(self, _event=None):
        """Filter cached rows without mixing statuses or retaining stale actions."""
        self.group_key = self.group_options[self.group_text.get()]
        self.fill_group()

    def fill_group(self):
        """Classify reservations; all ended states retain their precise row labels."""
        selection = self.table.selection()
        selected = selection[0] if selection else None
        states = next(states for key, _, states in RESERVATION_GROUPS if key == self.group_key)
        rows = [row for row in self.rows.values() if row["status"] in states]
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
                    "status": LABELS[row["status"]],
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
            hint = f"当前状态：{LABELS[row['status']]}。"
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
