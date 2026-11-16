"""Administrator review, account governance, messages and maintenance desktop views."""

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
    mark_all_messages_read,
    messages,
    platform_statistics,
    query_audit,
    seller_statistics,
    verify_backup,
)
from ui_common import (
    ACCENT,
    MUTED,
    PAPER,
    DataTable,
    MetricCards,
    TextWindow,
    display_value,
    enable_unread_dots,
    set_unread_dot,
    guarded,
)


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
            (
                row["id"],
                (
                    row["id"],
                    row["username"],
                    display_value(row["status"]),
                    display_value(row["roles"], "roles"),
                ),
            )
            for row in rows
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
        ttk.Button(toolbar, text="查看消息", command=lambda: guarded(self, self.read)).pack(
            side="left", padx=8
        )
        ttk.Button(toolbar, text="全部已读", command=lambda: guarded(self, self.read_all)).pack(
            side="left", padx=8
        )
        detail = ttk.LabelFrame(self, text="消息详情", padding=12)
        detail.pack(side="bottom", fill="x", pady=(10, 0))
        self.message_body = tk.Text(
            detail, height=6, wrap="word", relief="flat", bg=PAPER, state="disabled"
        )
        self.message_body.pack(fill="both", expand=True)
        self.table = DataTable(
            self,
            [
                ("id", "编号", 60),
                ("type", "事件", 100),
                ("content", "消息内容", 550),
                ("date", "发送时间（北京时间）", 200),
            ],
        )
        enable_unread_dots(self.table)
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
                    display_value(row["event_type"]),
                    row["content"],
                    display_value(row["created_at"], "created_at"),
                ),
            )
            for row in rows
        )

        for row in rows:
            set_unread_dot(self.table, row["id"], not row["is_read"])

    def read(self):
        """Read the selected notification in this page rather than a new window."""
        key = self.table.selected()
        mark_read(self.actor, key)
        row = self.rows[key]
        text = (
            f"{display_value(row['event_type'])}  ·  {display_value(row['created_at'],'created_at')}\n\n"
            f"{row['content']}\n\n商品编号：{row['product_id'] or '无'}    预约编号：{row['reservation_id'] or '无'}"
        )
        self.message_body.configure(state="normal")
        self.message_body.delete("1.0", "end")
        self.message_body.insert("1.0", text)
        self.message_body.configure(state="disabled")
        self.refresh()
        self.table.tree.selection_set(str(key))

    def read_all(self):
        """Clear this account's red dots across both message-center sections."""
        mark_all_messages_read(self.actor)
        self.refresh()


class ReportsPage(ttk.Frame):
    """Present statistical summaries as metric cards, charts and Chinese tables."""

    def __init__(self, parent, actor, administrator=False):
        super().__init__(parent, padding=18)
        self.actor = actor
        self.administrator = administrator
        self.chart_data = []
        self.chart = None
        self.result_data = {}
        self.platform_rows = []
        local_today = datetime.now(timezone(timedelta(hours=8))).date()
        self.start = tk.StringVar(master=self, value=str(local_today.replace(day=1)))
        self.end = tk.StringVar(master=self, value=str(local_today))
        ttk.Label(
            self, text="平台统计" if administrator else "我的统计", style="Title.TLabel"
        ).pack(anchor="w", pady=(0, 12))
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=8)
        for label, variable in [("开始日期", self.start), ("结束日期（包含）", self.end)]:
            ttk.Label(toolbar, text=label).pack(side="left", padx=5)
            entry = ttk.Entry(toolbar, textvariable=variable, width=14)
            entry.pack(side="left", padx=5)
            entry.bind("<Return>", lambda event: guarded(self, self.query))
        ttk.Button(
            toolbar, text="查询", style="Accent.TButton", command=lambda: guarded(self, self.query)
        ).pack(side="left", padx=8)
        ttk.Label(
            self, text="日期格式 YYYY-MM-DD；所有日期区间按北京时间划分。", style="Sub.TLabel"
        ).pack(anchor="w", pady=5)
        self.result = ttk.Frame(self)
        self.result.pack(fill="both", expand=True, pady=10)
        self.query()

    def query(self):
        """Validate first, then replace the last successful visualization."""
        function = platform_statistics if self.administrator else seller_statistics
        result = function(self.actor, self.start.get(), self.end.get())
        self.result_data = result
        for widget in self.result.winfo_children():
            widget.destroy()
        if self.administrator:
            self.platform_view(result)
        else:
            self.seller_view(result)

    def seller_view(self, result):
        """Keep current inventory separate from period and cohort statistics."""
        metrics = [
            ("区间首次发布", f"{result['区间首次发布数']} 件"),
            ("当前在售 · 截至现在", f"{result['当前在售数（非区间指标）']} 件"),
            ("区间确认成交", f"{result['区间确认成交数']} 件"),
            ("首次发布样本成交率", result["区间首次发布商品截至当前成交率"]),
        ]
        MetricCards(self.result, metrics).pack(fill="x")
        ttk.Label(self.result, text="分类发布与成交", font=("Microsoft YaHei", 13)).pack(
            anchor="w", pady=(14, 5)
        )
        self.chart_data = result["分类成交情况（首次发布样本）"]
        self.chart = tk.Canvas(self.result, height=175, bg=PAPER, highlightthickness=0)
        self.chart.pack(fill="x", pady=4)
        self.chart.bind("<Configure>", self.draw_chart)
        table = DataTable(
            self.result,
            [
                ("category", "商品分类", 200),
                ("total", "区间首次发布数", 170),
                ("sold", "其中已成交数", 170),
                ("rate", "样本成交率", 150),
            ],
        )
        table.tree.configure(height=4)
        table.pack(fill="both", expand=True, pady=8)
        table.fill(
            (
                index,
                (
                    row["name"] or "未分类",
                    row["total"],
                    row["sold"] or 0,
                    f"{(row['sold'] or 0) / row['total']:.1%}" if row["total"] else "无可计算数据",
                ),
            )
            for index, row in enumerate(self.chart_data)
        )
        ttk.Label(
            self.result,
            text="计算口径：成交率 = 区间内首次发布、截至当前已成交的商品数 ÷ 区间首次发布数。"
            "当前在售数不受日期区间限制；区间成交数按买家确认成交时间计算。",
            wraplength=1000,
            justify="left",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)

    def draw_chart(self, _event=None):
        """Render grouped quantity bars that resize with the statistics page."""
        chart = self.chart
        chart.delete("all")
        if not self.chart_data:
            chart.create_text(
                max(180, chart.winfo_width() // 2),
                85,
                text="所选日期内没有首次发布商品，暂无分类统计。",
                fill=MUTED,
                font=("Microsoft YaHei", 11),
            )
            return
        chart.create_rectangle(18, 12, 30, 24, fill="#dcc3a8", outline="")
        chart.create_text(38, 18, anchor="w", text="首次发布", fill=MUTED)
        chart.create_rectangle(135, 12, 147, 24, fill=ACCENT, outline="")
        chart.create_text(155, 18, anchor="w", text="其中成交", fill=MUTED)
        maximum = max(1, max(row["total"] for row in self.chart_data))
        available = max(100, chart.winfo_width() - 230)
        height = max(175, 42 + len(self.chart_data) * 31)
        chart.configure(height=height)
        for index, row in enumerate(self.chart_data):
            y = 43 + index * 31
            total, sold = row["total"], row["sold"] or 0
            chart.create_text(18, y + 8, text=row["name"] or "未分类", anchor="w", fill=MUTED)
            chart.create_rectangle(
                120, y, 120 + available * total / maximum, y + 9, fill="#dcc3a8", outline=""
            )
            chart.create_rectangle(
                120, y + 11, 120 + available * sold / maximum, y + 20, fill=ACCENT, outline=""
            )
            chart.create_text(
                132 + available * total / maximum,
                y + 9,
                text=f"{total} / {sold}",
                anchor="w",
                fill=MUTED,
            )

    def platform_view(self, result):
        """Show event metrics with explicit record identifiers for drill-down."""
        metrics = [
            (label, value["数量"]) for label, value in result.items() if isinstance(value, dict)
        ]
        MetricCards(self.result, metrics, columns=3).pack(fill="x")
        ttk.Label(self.result, text="统计明细索引", font=("Microsoft YaHei", 13)).pack(
            anchor="w", pady=(14, 5)
        )
        self.platform_rows = [
            (label, value) for label, value in result.items() if isinstance(value, dict)
        ]
        table = DataTable(
            self.result,
            [
                ("metric", "统计指标", 290),
                ("count", "事件数量", 110),
                ("records", "明细记录编号", 480),
            ],
        )
        table.pack(fill="both", expand=True, pady=8)
        table.fill(
            (index, (label, value["数量"], "、".join(map(str, value["明细编号"])) or "暂无记录"))
            for index, (label, value) in enumerate(self.platform_rows)
        )
        table.tree.bind("<Double-1>", lambda event: self.platform_detail(table.selected()))
        ttk.Label(
            self.result,
            text="各指标分别按自身事件时间计数；确认成交事件包含后续被更正的成交。"
            "双击一行查看完整编号清单，便于在对应业务页面核对。",
            wraplength=1000,
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)

    def platform_detail(self, index):
        """Open a readable list instead of dumping a result dictionary."""
        label, value = self.platform_rows[index]
        TextWindow(
            self,
            label,
            {"统计指标": label, "事件数量": value["数量"], "明细记录编号": value["明细编号"]},
        )


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
                ("time", "时间（北京时间）", 200),
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
                    display_value(row["action"]),
                    f"{display_value(row['object_type'])} · {row['object_id'] or '—'}",
                    display_value(row["result"]),
                    row["reason"],
                    display_value(row["created_at"], "created_at"),
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
        TextWindow(
            self,
            "备份已创建",
            {
                "备份状态": "成功",
                "保存位置": str(create_backup(self.actor)),
                "备份内容": "数据库与商品图片",
            },
        )
        self.refresh()

    def verify(self):
        """Exercise restore integrity without overwriting production data."""
        path = filedialog.askopenfilename(parent=self, filetypes=[("备份 ZIP", "*.zip")])
        if path:
            TextWindow(self, "恢复验证结果", verify_backup(path))

    def runs(self):
        """Show success and failure maintenance records."""
        TextWindow(self, "最近备份记录", backup_status(self.actor))
