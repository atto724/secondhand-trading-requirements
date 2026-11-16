"""Buyer and seller reservation progress views."""

import json
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
from ui_common import DataTable, TextWindow, display_value, guarded


class ReservationsPage(ttk.Frame):
    """Display a caller-owned reservation list with role-checked actions."""

    def __init__(self, parent, actor, scope="buyer"):
        super().__init__(parent, padding=18)
        self.actor = actor
        self.scope = scope
        self.rows = {}
        title = {"buyer": "我的预约", "seller": "卖家预约管理", "admin": "交易争议与更正"}[scope]
        ttk.Label(self, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=8)
        actions = [("刷新", self.refresh), ("预约详情 / 快照", self.detail)]
        if scope == "seller":
            actions += [
                ("确认预约", self.confirm),
                ("拒绝预约", self.reject),
                ("登记交付", self.deliver),
            ]
        if scope != "admin":
            actions += [
                ("取消 / 申请取消", self.cancel),
                ("同意取消", lambda: self.respond(True)),
                ("不同意，转人工", lambda: self.respond(False)),
            ]
        if scope == "buyer":
            actions += [("确认交易完成", self.complete)]
        if scope == "admin":
            actions += [
                ("核实取消", lambda: self.resolve(True)),
                ("核实继续交易", lambda: self.resolve(False)),
                ("更正错误成交", self.correct),
            ]
        for index, (label, action) in enumerate(actions):
            ttk.Button(
                toolbar, text=label, command=lambda function=action: guarded(self, function)
            ).grid(row=index // 5, column=index % 5, padx=3, pady=4, sticky="ew")
        ttk.Label(
            self,
            text="以创建预约时的商品快照为准。确认预约后才能查看交易电话；取消和争议均保留记录。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)
        self.table = DataTable(
            self,
            [
                ("id", "预约编号", 70),
                ("title", "预约时商品", 210),
                ("buyer", "买家", 120),
                ("status", "预约状态", 150),
                ("created", "创建时间（北京时间）", 200),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", lambda event: guarded(self, self.detail))
        self.refresh()

    def refresh(self):
        """Refresh live transaction state without reusing cached authorization."""
        rows = list_reservations(self.actor, self.scope)
        self.rows = {row["id"]: row for row in rows}
        self.table.fill(
            (
                row["id"],
                (
                    row["id"],
                    json.loads(row["snapshot"])["title"],
                    row["buyer_name"],
                    LABELS[row["status"]],
                    display_value(row["created_at"], "created_at"),
                ),
            )
            for row in rows
        )

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
