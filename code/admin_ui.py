"""Administrator review, account governance, messages and maintenance desktop views."""

import json
import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import filedialog, simpledialog, ttk

from catalog import review_product, search_products
from governance import block_product, list_accounts, release_product, set_account_enabled, set_admin
from market_ui import ProductDetail, status_label
from operations import (
    backup_status,
    create_backup,
    export_audit,
    mark_read,
    messages,
    platform_statistics,
    query_audit,
    seller_statistics,
    verify_backup,
)
from ui_common import DataTable, TextWindow, guarded


class ReviewPage(ttk.Frame):
    """Display all product states for reasoned review and moderation."""

    def __init__(self, parent, actor):
        super().__init__(parent, padding=18)
        self.actor = actor
        self.rows = {}
        ttk.Label(self, text="商品审核与治理", style="Title.TLabel").pack(anchor="w", pady=12)
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=8)
        for label, function in [
            ("刷新", self.refresh),
            ("查看详情", self.detail),
            ("审核通过", lambda: self.review(True)),
            ("驳回审核", lambda: self.review(False)),
            ("违规下架", self.block),
            ("解除违规", self.release),
        ]:
            ttk.Button(
                toolbar, text=label, command=lambda action=function: guarded(self, action)
            ).pack(side="left", padx=4)
        self.table = DataTable(
            self,
            [
                ("id", "编号", 60),
                ("title", "标题", 250),
                ("seller", "卖家", 130),
                ("status", "状态", 120),
                ("version", "版本", 60),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        """Load latest review versions and all states."""
        rows = []
        page = 1
        while True:
            batch, total = search_products(self.actor, scope="admin", page_size=100, page=page)
            rows.extend(batch)
            if len(rows) >= total:
                break
            page += 1
        self.rows = {row["id"]: row for row in rows}
        self.table.fill(
            (
                row["id"],
                (
                    row["id"],
                    row["title"],
                    row["seller_name"],
                    status_label(row["status"]),
                    row["version"],
                ),
            )
            for row in rows
        )

    def detail(self):
        """Inspect the content being reviewed."""
        ProductDetail(self, self.actor, self.table.selected())

    def review(self, approved):
        """Use the displayed version to reject stale review submissions."""
        key = self.table.selected()
        reason = (
            "" if approved else simpledialog.askstring("审核驳回", "请填写驳回原因：", parent=self)
        )
        if reason is None:
            return
        review_product(self.actor, key, self.rows[key]["version"], approved, reason)
        self.refresh()

    def block(self):
        """Moderate a product and its reservations together."""
        key = self.table.selected()
        reason = simpledialog.askstring("违规处理", "请填写违规依据：", parent=self)
        if reason is not None:
            block_product(self.actor, key, reason)
            self.refresh()

    def release(self):
        """Release a restriction without directly republishing the item."""
        key = self.table.selected()
        reason = simpledialog.askstring("解除违规", "请填写核实依据：", parent=self)
        if reason is not None:
            release_product(self.actor, key, reason)
            self.refresh()


class AccountsPage(ttk.Frame):
    """Explicit administrator authorization and account status changes."""

    def __init__(self, parent, actor):
        super().__init__(parent, padding=18)
        self.actor = actor
        ttk.Label(self, text="账号与授权", style="Title.TLabel").pack(anchor="w", pady=12)
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=8)
        actions = [
            ("刷新", self.refresh),
            ("禁用账号", lambda: self.change("enabled", False)),
            ("恢复账号", lambda: self.change("enabled", True)),
            ("授予管理员", lambda: self.change("admin", True)),
            ("撤销管理员", lambda: self.change("admin", False)),
        ]
        for label, function in actions:
            ttk.Button(
                toolbar, text=label, command=lambda action=function: guarded(self, action)
            ).pack(side="left", padx=4)
        self.table = DataTable(
            self,
            [
                ("id", "账号编号", 70),
                ("name", "登录名", 180),
                ("status", "状态", 100),
                ("roles", "角色", 260),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        """Refresh roles from the database rather than UI state."""
        rows = list_accounts(self.actor)
        self.table.fill(
            (row["id"], (row["id"], row["username"], row["status"], row["roles"])) for row in rows
        )

    def change(self, kind, enabled):
        """Require an explanation for every privileged account mutation."""
        key = self.table.selected()
        reason = simpledialog.askstring("操作依据", "请填写原因：", parent=self)
        if reason is not None:
            function = set_admin if kind == "admin" else set_account_enabled
            function(self.actor, key, enabled, reason)
            self.refresh()


class MessagesPage(ttk.Frame):
    """Caller-specific notification inbox."""

    def __init__(self, parent, actor):
        super().__init__(parent, padding=18)
        self.actor = actor
        self.rows = {}
        ttk.Label(self, text="消息中心", style="Title.TLabel").pack(anchor="w", pady=12)
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=8)
        ttk.Button(toolbar, text="刷新", command=lambda: guarded(self, self.refresh)).pack(
            side="left"
        )
        ttk.Button(toolbar, text="查看并标为已读", command=lambda: guarded(self, self.read)).pack(
            side="left", padx=8
        )
        self.table = DataTable(
            self,
            [
                ("id", "编号", 60),
                ("read", "阅读", 65),
                ("type", "事件", 100),
                ("content", "消息内容", 550),
                ("date", "发送时间（UTC）", 200),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", lambda event: guarded(self, self.read))
        self.refresh()

    def refresh(self):
        """Load only messages belonging to the signed-in account."""
        rows = messages(self.actor)
        self.rows = {row["id"]: row for row in rows}
        self.table.fill(
            (
                row["id"],
                (
                    row["id"],
                    "已读" if row["is_read"] else "未读",
                    row["event_type"],
                    row["content"],
                    row["created_at"],
                ),
            )
            for row in rows
        )

    def read(self):
        """Display message linkage to real product/reservation records."""
        key = self.table.selected()
        TextWindow(self, "站内消息", self.rows[key])
        mark_read(self.actor, key)
        self.refresh()


class ReportsPage(ttk.Frame):
    """Custom date ranges for seller and administrator metrics."""

    def __init__(self, parent, actor, administrator=False):

        super().__init__(parent, padding=18)
        self.actor = actor
        self.administrator = administrator
        local_today = datetime.now(timezone(timedelta(hours=8))).date()
        self.start = tk.StringVar(master=self, value=str(local_today.replace(day=1)))
        self.end = tk.StringVar(master=self, value=str(local_today))
        ttk.Label(
            self, text="平台统计" if administrator else "我的统计", style="Title.TLabel"
        ).pack(anchor="w", pady=12)
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=12)
        for label, variable in [("开始日期", self.start), ("结束日期（包含）", self.end)]:
            ttk.Label(toolbar, text=label).pack(side="left", padx=5)
            ttk.Entry(toolbar, textvariable=variable, width=14).pack(side="left", padx=5)
        ttk.Button(toolbar, text="查询", command=lambda: guarded(self, self.query)).pack(
            side="left", padx=8
        )
        ttk.Label(
            self, text="日期格式 YYYY-MM-DD，统一按北京时间（UTC+8）划分区间。", style="Sub.TLabel"
        ).pack(anchor="w")
        self.result = tk.Text(self, wrap="word", font=("Microsoft YaHei", 11), padx=16, pady=16)
        self.result.pack(fill="both", expand=True, pady=12)
        self.query()

    def query(self):
        """Show metric definitions together with computed values."""

        function = platform_statistics if self.administrator else seller_statistics
        result = function(self.actor, self.start.get(), self.end.get())
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", json.dumps(result, ensure_ascii=False, indent=2))
        self.result.configure(state="disabled")


class MaintenancePage(ttk.Frame):
    """Audit filtering/export and verified, non-destructive backup operations."""

    def __init__(self, parent, actor):

        super().__init__(parent, padding=18)
        self.actor = actor
        self.keyword = tk.StringVar(master=self)
        ttk.Label(self, text="审计与备份", style="Title.TLabel").pack(anchor="w", pady=12)
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=8)
        ttk.Label(toolbar, text="动作 / 对象 / 人员编号 / 原因").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.keyword, width=24).pack(side="left", padx=8)
        for label, action in [
            ("查询日志", self.refresh),
            ("日志详情", self.detail),
            ("导出 CSV", self.export),
            ("创建备份", self.backup),
            ("验证备份恢复", self.verify),
            ("备份记录", self.runs),
        ]:
            ttk.Button(
                toolbar, text=label, command=lambda function=action: guarded(self, function)
            ).pack(side="left", padx=2)
        ttk.Label(
            self,
            text="备份包含数据库与图片；验证恢复在临时目录进行，不覆盖当前数据。应用开启时每日自动备份一次。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)
        self.table = DataTable(
            self,
            [
                ("id", "编号", 60),
                ("actor", "操作人", 70),
                ("action", "动作", 170),
                ("object", "对象", 120),
                ("result", "结果", 80),
                ("reason", "原因", 250),
                ("time", "时间（UTC）", 200),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.rows = {}
        self.refresh()

    def refresh(self):
        """Use the audited service for every log query."""
        rows = query_audit(self.actor, self.keyword.get())
        self.rows = {row["id"]: row for row in rows}
        self.table.fill(
            (
                row["id"],
                (
                    row["id"],
                    row["actor_id"],
                    row["action"],
                    f"{row['object_type']}:{row['object_id']}",
                    row["result"],
                    row["reason"],
                    row["created_at"],
                ),
            )
            for row in rows
        )

    def detail(self):
        """Show structured before/after values."""
        TextWindow(self, "审计详情", self.rows[self.table.selected()])

    def export(self):
        """Choose a local CSV export destination."""
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")]
        )
        if path:
            export_audit(self.actor, path, self.keyword.get())
            self.refresh()

    def backup(self):
        """Create a backup using SQLite's consistent backup API."""
        TextWindow(self, "备份已创建", str(create_backup(self.actor)))
        self.refresh()

    def verify(self):
        """Exercise restore integrity without overwriting production data."""
        path = filedialog.askopenfilename(parent=self, filetypes=[("备份 ZIP", "*.zip")])
        if path:
            TextWindow(self, "恢复验证结果", verify_backup(path))

    def runs(self):
        """Show success and failure maintenance records."""
        TextWindow(self, "最近备份记录", backup_status(self.actor))
