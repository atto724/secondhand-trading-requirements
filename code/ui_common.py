"""Shared desktop widgets, image rendering and error presentation."""

import json
import logging
import sqlite3
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tkinter import messagebox, ttk

from PIL import Image, ImageOps, ImageTk

import database
import demo_assets

BG = "#fbf3e6"
PAPER = "#ffffff"
INK = "#3e2d23"
ACCENT = "#ad4326"
MUTED = "#80634f"


def configure_style(root):
    """Apply the warm palette from the experiment-two UI prototypes."""
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei", 10), foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG)
    style.configure("Title.TLabel", font=("Microsoft YaHei", 22))
    style.configure("Sub.TLabel", foreground=MUTED)
    style.configure("TButton", padding=(12, 7), background="#fffaf4")
    style.map("TButton", background=[("active", "#f3dfca")])
    style.configure("Accent.TButton", background=ACCENT, foreground="white")
    style.map("Accent.TButton", background=[("active", "#91371f")])
    style.configure("Treeview", rowheight=32, background=PAPER, fieldbackground=PAPER)
    style.configure("Treeview.Heading", padding=8, background="#f4e4d2")


def guarded(parent, function):
    """Present expected operational failures without terminating the event loop."""
    try:
        return function()
    except (ValueError, OSError, sqlite3.Error) as error:
        messagebox.showerror("操作未完成", str(error), parent=parent)
        return None
    except Exception:
        logging.exception("Unexpected desktop operation failure")
        messagebox.showerror("操作未完成", "发生未预期错误，请查看 data/app.log。", parent=parent)
        return None


def thumbnail(parent, path, size=(170, 150)):
    """Return a correctly oriented thumbnail while keeping originals unchanged."""
    with Image.open(path) as source:
        picture = ImageOps.exif_transpose(source).convert("RGB")
        picture.thumbnail(size)
        canvas = Image.new("RGB", size, "#f3ece3")
        canvas.paste(picture, ((size[0] - picture.width) // 2, (size[1] - picture.height) // 2))
        return ImageTk.PhotoImage(canvas, master=parent)


def stored_image(relative):
    """Resolve application images inside the configured data directory."""
    root = database.DATABASE_PATH.parent.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("图片路径无效。")
    return path


def avatar_photo(parent, account_id, relative="", size=(56, 56)):
    """Load a stored avatar or a bundled default without relying on temporary files."""
    if relative:
        try:
            return thumbnail(parent, stored_image(relative), size)
        except (OSError, ValueError):
            pass
    default = Path(demo_assets.__file__).parent / f"avatar_{(account_id-1)%4+1}.jpg"
    return thumbnail(parent, default, size)


class Window(tk.Toplevel):
    """A resizable secondary window with Escape-to-close support."""

    def __init__(self, parent, title, size="950x650"):
        super().__init__(parent)
        self.title(title)
        self.geometry(size)
        self.minsize(700, 500)
        self.configure(bg=BG)
        self.transient(parent)
        self.bind("<Escape>", lambda event: self.destroy())


class DataTable(ttk.Frame):
    """Scrollable keyed table with safe single-row selection."""

    def __init__(self, parent, columns):
        super().__init__(parent)
        self.tree = ttk.Treeview(
            self, columns=[item[0] for item in columns], show="headings", selectmode="browse"
        )
        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=50)
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def fill(self, rows):
        """Replace displayed rows while preserving no stale selection."""
        self.tree.delete(*self.tree.get_children())
        for key, values in rows:
            self.tree.insert("", "end", iid=str(key), values=values)

    def selected(self):
        """Return the selected numeric object ID or explain missing selection."""
        selection = self.tree.selection()
        if len(selection) != 1:
            raise ValueError("请先选择一条记录。")
        return int(selection[0])


def enable_unread_dots(table):
    """Use a real red image indicator without recoloring message text."""
    table.unread_dot = tk.PhotoImage(master=table, width=10, height=10)
    for y in range(10):
        for x in range(10):
            if (x - 4.5) ** 2 + (y - 4.5) ** 2 <= 20:
                table.unread_dot.put("#ed4141", (x, y))
    table.tree.configure(show=("tree", "headings"))
    table.tree.column("#0", width=26, minwidth=26, stretch=False)
    table.tree.heading("#0", text="")


def set_unread_dot(table, key, unread):
    """Removing the image leaves no 'read/unread' text or numeric badge."""
    table.tree.item(str(key), image=table.unread_dot if unread else "")


FIELD_LABELS = {
    "id": "编号",
    "name": "名称",
    "total": "发布数量",
    "sold": "成交数量",
    "actor_id": "操作人编号",
    "action": "操作",
    "object_type": "对象类型",
    "object_id": "对象编号",
    "before_value": "操作前",
    "after_value": "操作后",
    "result": "结果",
    "reason": "原因 / 处理依据",
    "created_at": "记录时间",
    "updated_at": "最后更新时间",
    "receiver_id": "接收人编号",
    "product_id": "商品编号",
    "reservation_id": "预约编号",
    "event_type": "事件类型",
    "content": "内容",
    "is_read": "阅读状态",
    "file_name": "备份文件",
    "file_path": "图片文件",
    "seller_id": "卖家编号",
    "buyer_id": "买家编号",
    "phone": "联系电话",
    "title": "商品名称",
    "description": "商品描述",
    "category_id": "分类编号",
    "price_cents": "商品价格",
    "status": "状态",
    "version": "内容版本",
    "condition_label": "成色",
    "shipping": "交付 / 运费",
    "negotiable": "可议价",
    "blocked": "违规限制",
    "deleted": "已删除",
    "images": "商品图片",
    "display_order": "显示顺序",
    "first_published_at": "首次发布时间",
    "sold_at": "成交时间",
    "confirmed_at": "预约确认时间",
    "delivered_at": "交付登记时间",
    "completed_at": "交易完成时间",
    "cancel_by": "取消申请人",
    "cancel_previous": "取消前状态",
    "reminder_sent": "已发送提醒",
    "snapshot": "预约时商品信息",
    "approved": "审核通过",
    "admin_id": "管理员编号",
    "roles": "角色",
    "username": "登录名",
    "password_hash": "密码信息",
}
VALUE_LABELS = {
    "active": "正常",
    "disabled": "已禁用",
    "buyer": "买家",
    "seller": "卖家",
    "admin": "管理员",
    "success": "成功",
    "failure": "失败",
    "draft": "草稿",
    "pending_review": "待审核",
    "published": "已发布",
    "reserved": "已预约",
    "sold": "已成交",
    "delisted": "已下架",
    "violation": "违规下架",
    "waiting": "等待卖家确认",
    "confirmed": "卖家已确认",
    "delivered": "待买家确认完成",
    "cancel_requested": "取消协商中",
    "manual": "待管理员处理",
    "completed": "交易已完成",
    "cancelled": "已取消",
    "rejected": "已拒绝",
    "expired": "已失效",
    "corrected": "已更正",
    "deleted": "已删除",
    "blocked": "已限制",
    "ordinary": "普通用户",
    "buyer,seller": "买家、卖家",
    "continue": "继续交易",
    "account": "账号",
    "product": "商品",
    "reservation": "预约",
    "request": "请求",
    "audit": "审计",
    "report": "统计",
    "backup": "备份",
    "register": "账号注册",
    "login": "账号登录",
    "bootstrap_admin": "初始化管理员",
    "save_product": "保存商品",
    "submit_review": "提交审核",
    "review": "商品审核",
    "review_approved": "审核通过",
    "review_rejected": "审核驳回",
    "delist": "商品下架",
    "delete_draft": "删除草稿",
    "reserve": "发起预约",
    "confirm_reservation": "确认预约",
    "reject_reservation": "拒绝预约",
    "reservation_timeout": "预约超时",
    "timeout": "预约超时",
    "cancel_request": "申请取消",
    "cancel_response": "处理取消申请",
    "cancel": "取消进度",
    "deliver": "登记交付",
    "complete": "确认成交",
    "delivery_reminder": "交付确认提醒",
    "transaction_detail": "查看交易详情",
    "view_contact": "查看交易电话",
    "grant_admin": "授予管理员",
    "revoke_admin": "撤销管理员",
    "release_product": "解除商品限制",
    "account_status": "变更账号状态",
    "resolve_dispute": "处理交易争议",
    "correct_sale": "更正成交",
    "platform_statistics": "查询平台统计",
    "query_audit": "查询日志",
    "export_audit": "导出日志",
    "moderation": "违规处理",
    "release": "解除限制",
    "account_disabled": "账号禁用",
    "correction": "成交更正",
    "reminder": "确认提醒",
    "dispute": "交易争议",
}


def display_value(value, key=""):  # pylint: disable=too-many-return-statements
    """Format a scalar for people without changing stored values."""
    if key == "password_hash":
        return "不展示密码信息"
    if value is None or value == "":
        return "未记录"
    if key == "price_cents" and isinstance(value, int):
        return f"¥ {value // 100}.{value % 100:02d}"
    if key in ("negotiable", "blocked", "deleted", "approved", "reminder_sent"):
        return "是" if value else "否"
    if key == "is_read":
        return "已读" if value else "未读"
    if isinstance(value, str) and (key.endswith("_at") or "时间" in key):
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if instant.tzinfo:
                return instant.astimezone(timezone(timedelta(hours=8))).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
        except ValueError:
            pass
    if key == "roles" and isinstance(value, str):
        return "、".join(VALUE_LABELS.get(role, role) for role in value.split(","))
    return VALUE_LABELS.get(str(value), str(value))


class MetricCards(ttk.Frame):
    """Readable numeric summaries arranged in a fixed-column grid."""

    def __init__(self, parent, metrics, columns=4):
        super().__init__(parent)
        for column in range(columns):
            self.columnconfigure(column, weight=1, uniform="metric")
        for index, (label, value) in enumerate(metrics):
            card = tk.Frame(
                self,
                bg=PAPER,
                padx=16,
                pady=12,
                highlightthickness=1,
                highlightbackground="#e7cfb6",
            )
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=5, pady=5)
            tk.Label(
                card, text=label, bg=PAPER, fg=MUTED, wraplength=235, font=("Microsoft YaHei", 10)
            ).pack(anchor="w")
            tk.Label(card, text=str(value), bg=PAPER, fg=ACCENT, font=("Microsoft YaHei", 24)).pack(
                anchor="w", pady=(8, 0)
            )


class TextWindow(Window):
    """Render structured details as Chinese sections, tables and image previews."""

    def __init__(self, parent, title, content):
        super().__init__(parent, title, "960x720")
        self.photos = []
        header = ttk.Frame(self, padding=(20, 15))
        header.pack(fill="x")
        ttk.Label(header, text=title, style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="关闭", command=self.destroy).pack(side="right")
        ttk.Label(self, text="所有时间按北京时间（UTC+8）显示。", style="Sub.TLabel").pack(
            anchor="w", padx=22
        )
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=16, pady=12)
        canvas.configure(yscrollcommand=scrollbar.set)
        body = ttk.Frame(canvas, padding=6)
        item = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        self.render(body, content)

    def render(self, parent, content, key=""):
        """Recursively display saved dictionaries without exposing JSON syntax."""
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (ValueError, TypeError):
                pass
        if isinstance(content, dict):
            for field, value in content.items():
                label = FIELD_LABELS.get(field, field)
                if field == "images" and isinstance(value, list):
                    self.image_section(parent, value)
                elif isinstance(value, (dict, list)) or field in ("before_value", "after_value"):
                    section = ttk.LabelFrame(parent, text=label, padding=12)
                    section.pack(fill="x", pady=7)
                    self.render(section, value, field)
                else:
                    row = ttk.Frame(parent, padding=(10, 8))
                    row.pack(fill="x")
                    row.columnconfigure(1, weight=1)
                    ttk.Label(row, text=label, width=20, style="Sub.TLabel").grid(
                        row=0, column=0, sticky="nw"
                    )
                    ttk.Label(
                        row, text=display_value(value, field), wraplength=570, justify="left"
                    ).grid(row=0, column=1, sticky="w")
        elif isinstance(content, list):
            if not content:
                ttk.Label(parent, text="暂无记录", style="Sub.TLabel").pack(anchor="w", pady=12)
            elif all(isinstance(row, dict) for row in content):
                keys = list(dict.fromkeys(field for row in content for field in row))
                table = DataTable(
                    parent, [(field, FIELD_LABELS.get(field, field), 160) for field in keys]
                )
                table.tree.configure(height=min(10, max(2, len(content))))
                table.pack(fill="x", pady=8)
                table.fill(
                    (index, [display_value(row.get(field), field) for field in keys])
                    for index, row in enumerate(content)
                )
            else:
                for index, value in enumerate(content, 1):
                    ttk.Label(
                        parent, text=f"{index}. {display_value(value, key)}", wraplength=700
                    ).pack(anchor="w", pady=4)
        else:
            ttk.Label(
                parent, text=display_value(content, key), wraplength=720, justify="left"
            ).pack(anchor="w", pady=10)

    def image_section(self, parent, images):
        """Show snapshot images instead of internal filesystem paths."""
        section = ttk.LabelFrame(parent, text="商品图片", padding=12)
        section.pack(fill="x", pady=8)
        if not images:
            ttk.Label(section, text="未添加图片", style="Sub.TLabel").pack(anchor="w")
        for index, image in enumerate(images):
            relative = image.get("file_path") if isinstance(image, dict) else image
            try:
                photo = thumbnail(self, stored_image(relative), (150, 130))
                self.photos.append(photo)
                ttk.Label(section, image=photo).grid(
                    row=index // 4, column=index % 4, padx=5, pady=5
                )
            except (ValueError, OSError, TypeError):
                ttk.Label(section, text=f"图片 {index + 1} 缺失或不可读取").grid(
                    row=index // 4, column=index % 4, padx=5, pady=5
                )
