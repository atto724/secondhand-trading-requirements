"""Shared desktop widgets, image rendering and error presentation."""

import json
import logging
import sqlite3
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

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


def avatar_photo(parent, account_id, relative="", size=(56, 56), circular=False):
    """Render a stored or default avatar; circular masking changes only UI pixels."""
    candidates = []
    if relative:
        try:
            candidates.append(stored_image(relative))
        except ValueError:
            pass
    candidates.append(Path(demo_assets.__file__).parent / f"avatar_{(account_id-1)%4+1}.jpg")
    for path in candidates:
        try:
            if not circular:
                return thumbnail(parent, path, size)
            with Image.open(path) as source:
                picture = ImageOps.fit(
                    ImageOps.exif_transpose(source).convert("RGBA"),
                    size,
                    method=Image.Resampling.LANCZOS,
                )
            mask = Image.new("L", (size[0] * 4, size[1] * 4), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, mask.width - 1, mask.height - 1), fill=255)
            picture.putalpha(mask.resize(size, Image.Resampling.LANCZOS))
            return ImageTk.PhotoImage(picture, master=parent)
        except (OSError, ValueError):
            continue
    raise ValueError("头像资源无法读取。")


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


class ProductRows(ttk.Frame):
    """Scrollable horizontal product cards with keyed selection and inline actions."""

    def __init__(self, parent, on_open=None):
        super().__init__(parent)
        self.on_open = on_open
        self.current = None
        self.cards = {}
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind(
            "<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<MouseWheel>", self.wheel)

    def resize(self, event):
        """Keep descriptions and controls inside the available viewport."""
        self.canvas.itemconfigure(self.window, width=event.width)
        for card in self.cards.values():
            for label in card["labels"]:
                label.configure(wraplength=max(120, event.width - 400))

    def wheel(self, event):
        """Scroll cards without installing application-wide bindings."""
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def selection(self):
        """Expose the selected key without depending on a hidden tree widget."""
        return (self.current,) if self.current in self.cards else ()

    def keys(self):
        """Return displayed keys in their visual order."""
        return tuple(self.cards)

    def selected(self):
        """Require explicit selection before a transaction action."""
        if not self.selection():
            raise ValueError("请先选择一条记录。")
        return int(self.current)

    def select(self, key):
        """Highlight a card and notify its host when it becomes selected."""
        key = str(key)
        if key not in self.cards:
            return
        self.current = key
        for identity, card in self.cards.items():
            card["frame"].configure(highlightbackground=ACCENT if identity == key else "#edcdb7")
        self.event_generate("<<CardSelected>>")

    def invoke(self, key, function):
        """Bind each inline action to that specific record before calling the host."""
        self.select(key)
        guarded(self, function)

    def fill(self, rows):
        """Replace cards while retaining a still-visible selection."""
        previous = self.current
        for widget in self.body.winfo_children():
            widget.destroy()
        self.cards = {}
        for item in rows:
            key = str(item["id"])
            card = tk.Frame(
                self.body,
                bg=PAPER,
                highlightbackground="#edcdb7",
                highlightthickness=1,
                padx=14,
                pady=12,
            )
            card.pack(fill="x", pady=(0, 12))
            image = tk.Label(card, text="暂无图片", bg="#f3ece3", fg=MUTED, width=10, height=5)
            if item.get("image"):
                try:
                    image.photo = thumbnail(self, stored_image(item["image"]), (88, 88))
                    image.configure(image=image.photo, text="", width=88, height=88)
                except (OSError, ValueError):
                    image.configure(text="图片缺失")
            image.pack(side="left", anchor="n", padx=(0, 16))
            actions = tk.Frame(card, bg=PAPER, width=240)
            actions.pack(side="right", anchor="ne", padx=(12, 0))
            tk.Label(actions, text=item["status"], bg="#fbe9d8", fg=ACCENT, padx=12, pady=5).grid(
                row=0, column=0, columnspan=2, sticky="e", pady=(0, 8)
            )
            buttons = []
            for index, (text, function) in enumerate(item.get("actions", [])):
                button = tk.Button(
                    actions,
                    text=text,
                    command=lambda identity=key, action=function: self.invoke(identity, action),
                    bg="#fffaf4",
                    fg=ACCENT,
                    activebackground="#fbe9d8",
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground="#edcdb7",
                    highlightcolor=ACCENT,
                    padx=12,
                    pady=5,
                    cursor="hand2",
                    font=("Microsoft YaHei", 10),
                )
                button.grid(row=1 + index // 2, column=index % 2, padx=(6, 0), pady=3, sticky="e")
                buttons.append(button)
            info = tk.Frame(card, bg=PAPER)
            info.pack(side="left", fill="both", expand=True)
            title = tk.Label(
                info,
                text=item["title"],
                font=("Microsoft YaHei", 14),
                bg=PAPER,
                fg=INK,
                anchor="w",
                justify="left",
                wraplength=400,
            )
            title.pack(fill="x")
            cents = item.get("price")
            tk.Label(
                info,
                text=f"¥ {cents/100:.2f}" if cents is not None else "价格未记录",
                font=("Microsoft YaHei", 12),
                bg=PAPER,
                fg=ACCENT,
                anchor="w",
            ).pack(fill="x", pady=3)
            subtitle = tk.Label(
                info,
                text=item.get("subtitle", ""),
                bg=PAPER,
                fg=MUTED,
                anchor="w",
                justify="left",
                wraplength=400,
            )
            subtitle.pack(fill="x")
            self.cards[key] = {
                "frame": card,
                "labels": [title, subtitle],
                "buttons": buttons,
                "data": item,
            }
            for widget in (card, image, info, title, subtitle):
                widget.bind("<Button-1>", lambda event, identity=key: self.select(identity))
                widget.bind("<MouseWheel>", self.wheel)
                if self.on_open:
                    widget.bind(
                        "<Double-1>",
                        lambda event, identity=key: self.invoke(
                            identity, lambda: self.on_open(int(identity))
                        ),
                    )
        if not self.cards:
            tk.Label(
                self.body, text="该分类暂无记录", bg=BG, fg=MUTED, font=("Microsoft YaHei", 12)
            ).pack(pady=48)
        self.current = previous if previous in self.cards else None
        if self.current:
            self.select(self.current)
        self.canvas.yview_moveto(0)


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
