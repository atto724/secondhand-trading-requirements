"""Product browsing cards, seller management and image-rich detail views."""

import math
import tkinter as tk
from tkinter import messagebox, ttk

from catalog import (
    delete_draft,
    delist_product,
    product_detail,
    search_products,
    submit_review,
)
from core import money, price
from domain import PRODUCT_STATUS_LABELS, ProductStatus
from editor_ui import ProductEditor
from products import list_categories, list_my_products
from trades import reserve
from ui_common import ACCENT, BG, INK, PAPER, DataTable, Window, guarded, stored_image, thumbnail


def status_label(value):
    """Translate the persisted product state."""
    return PRODUCT_STATUS_LABELS[ProductStatus(value)]


class ProductDetail(Window):
    """Show real product images and fields without revealing seller phone publicly."""

    def __init__(self, parent, actor, product_id):
        item = product_detail(actor, product_id)
        super().__init__(parent, item["title"] or "商品详情", "980x700")
        self.photos = []
        self.actor = actor
        self.item = item
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill="both", expand=True)
        left = ttk.Frame(frame)
        left.pack(side="left", fill="both", expand=True, padx=(0, 24))
        self.large = ttk.Label(left, text="暂无商品图片", anchor="center")
        self.large.pack(fill="both", expand=True)
        strip = ttk.Frame(left)
        strip.pack(fill="x", pady=10)
        for index, image in enumerate(item["images"]):
            ttk.Button(
                strip, text=str(index + 1), command=lambda current=image: self.show_image(current)
            ).pack(side="left", padx=3)
        if item["images"]:
            self.show_image(item["images"][0])
        right = ttk.Frame(frame)
        right.pack(side="right", fill="both", expand=True)
        ttk.Label(
            right, text=item["title"] or "（未填写标题）", style="Title.TLabel", wraplength=400
        ).pack(anchor="w", pady=10)
        ttk.Label(
            right,
            text=f"¥ {price(item['price_cents'])}",
            foreground=ACCENT,
            font=("Microsoft YaHei", 23),
        ).pack(anchor="w", pady=12)
        tags = f"{status_label(item['status'])} · {item['condition_label']} · {item['shipping']}"
        if item["negotiable"]:
            tags += " · 可小刀"
        ttk.Label(right, text=tags, wraplength=400).pack(anchor="w", pady=8)
        text = tk.Text(
            right, height=8, width=35, wrap="word", font=("Microsoft YaHei", 11), relief="flat"
        )
        text.insert("1.0", item["description"] or "（未填写描述）")
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, pady=12)
        ttk.Label(
            right,
            text=f"卖家：{item['seller_name']}\n内容版本：{item['version']}",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)
        if item["reviews"]:
            review = item["reviews"][0]
            ttk.Label(
                right,
                text=f"最近审核：{'通过' if review['approved'] else '驳回'} {review['reason']}",
                wraplength=400,
            ).pack(anchor="w", pady=8)
        if actor != item["seller_id"] and item["status"] == "published":
            ttk.Button(
                right,
                text="发起预约",
                style="Accent.TButton",
                command=lambda: guarded(self, self.book),
            ).pack(anchor="w", pady=12)
        ttk.Label(
            right,
            text="付款和交付在线下协商，平台只记录预约及交易结果。",
            wraplength=380,
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)

    def show_image(self, image):
        """Load one picture with safe fallback if a file is missing."""
        try:
            photo = thumbnail(self, stored_image(image["file_path"]), (390, 390))
            self.photos = [photo]
            self.large.configure(image=photo, text="")
        except (OSError, ValueError):
            self.large.configure(image="", text="图片缺失，无法预览")

    def book(self):
        """Create or recover the current buyer's live reservation."""
        reservation_id = reserve(self.actor, self.item["id"])
        messagebox.showinfo(
            "预约已记录", f"预约编号：{reservation_id}\n请在“我的预约”查看进度。", parent=self
        )


class CatalogPage(ttk.Frame):
    """Public product filters and eight real cards per page."""

    def __init__(self, parent, actor):
        super().__init__(parent, padding=18)
        self.actor = actor
        self.page = 1
        self.total = 0
        self.photos = []
        self.categories = {row["name"]: row["id"] for row in list_categories()}
        ttk.Label(self, text="浏览商品", style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        filters = ttk.Frame(self)
        filters.pack(fill="x")
        self.keyword = tk.StringVar(master=self)
        self.category = tk.StringVar(master=self, value="全部分类")
        self.minimum = tk.StringVar(master=self)
        self.maximum = tk.StringVar(master=self)
        self.sort = tk.StringVar(master=self, value="最新发布")
        widgets = [
            ttk.Entry(filters, textvariable=self.keyword, width=20),
            ttk.Combobox(
                filters,
                textvariable=self.category,
                values=["全部分类"] + list(self.categories),
                state="readonly",
                width=12,
            ),
            ttk.Entry(filters, textvariable=self.minimum, width=9),
            ttk.Entry(filters, textvariable=self.maximum, width=9),
            ttk.Combobox(
                filters,
                textvariable=self.sort,
                values=["最新发布", "价格从低到高", "价格从高到低"],
                state="readonly",
                width=15,
            ),
        ]
        for widget, label in zip(widgets, ["关键词", "分类", "最低价", "最高价", "排序"]):
            ttk.Label(filters, text=label).pack(side="left", padx=(0, 4))
            widget.pack(side="left", padx=(0, 8))
            widget.bind("<Return>", lambda event: self.query())
        ttk.Button(filters, text="查询", style="Accent.TButton", command=self.query).pack(
            side="left", padx=4
        )
        ttk.Label(
            self, text="仅展示当前可预约商品；最低价和最高价单位为元。", style="Sub.TLabel"
        ).pack(anchor="w", pady=12)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.cards = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.cards, anchor="nw")
        self.cards.bind(
            "<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self.window_id, width=event.width),
        )
        footer = ttk.Frame(self)
        footer.pack(fill="x", pady=10)
        ttk.Button(footer, text="上一页", command=lambda: self.turn(-1)).pack(side="left")
        self.page_label = ttk.Label(footer)
        self.page_label.pack(side="left", padx=20)
        ttk.Button(footer, text="下一页", command=lambda: self.turn(1)).pack(side="left")
        self.query()

    def query(self):
        """Reset pagination when filters change."""
        self.page = 1
        guarded(self, self.refresh)

    def refresh(self):
        """Render cards using actual database results and stored cover pictures."""
        rows, self.total = search_products(
            self.actor,
            self.keyword.get(),
            self.categories.get(self.category.get()),
            money(self.minimum.get(), True) if self.minimum.get().strip() else None,
            money(self.maximum.get(), True) if self.maximum.get().strip() else None,
            {"最新发布": "latest", "价格从低到高": "price_asc", "价格从高到低": "price_desc"}[
                self.sort.get()
            ],
            self.page,
        )
        for child in self.cards.winfo_children():
            child.destroy()
        self.photos.clear()
        for column in range(4):
            self.cards.columnconfigure(column, weight=1, uniform="card")
        if not rows:
            ttk.Label(
                self.cards,
                text="暂无符合条件的商品。可先创建草稿并由管理员审核发布。",
                wraplength=700,
            ).grid(row=0, column=0, columnspan=4, pady=60)
        for index, item in enumerate(rows):
            card = tk.Frame(
                self.cards,
                bg=PAPER,
                padx=12,
                pady=12,
                highlightbackground="#e7cfb6",
                highlightthickness=1,
            )
            card.grid(row=index // 4, column=index % 4, padx=7, pady=7, sticky="nsew")
            image_label = tk.Label(card, text="暂无图片", bg="#f3ece3", width=22, height=8)
            if item["cover"]:
                try:
                    photo = thumbnail(self, stored_image(item["cover"]), (175, 150))
                    self.photos.append(photo)
                    image_label.configure(image=photo, width=175, height=150, text="")
                except (OSError, ValueError):
                    image_label.configure(text="图片缺失")
            image_label.pack(fill="x")
            tk.Label(
                card,
                text=item["title"],
                bg=PAPER,
                fg=INK,
                wraplength=185,
                font=("Microsoft YaHei", 12),
                anchor="w",
            ).pack(fill="x", pady=(8, 3))
            tk.Label(card, text=item["category_name"], bg=PAPER, fg=INK, anchor="w").pack(fill="x")
            tk.Label(
                card,
                text="¥ " + price(item["price_cents"]),
                bg=PAPER,
                fg=ACCENT,
                font=("Microsoft YaHei", 16),
                anchor="w",
            ).pack(fill="x", pady=5)
            ttk.Button(
                card,
                text="查看详情",
                command=lambda key=item["id"]: guarded(
                    self, lambda: ProductDetail(self, self.actor, key)
                ),
            ).pack(anchor="e")
        self.page_label.configure(
            text=f"第 {self.page} / {max(1, math.ceil(self.total / 8))} 页 · 共 {self.total} 件"
        )
        self.canvas.yview_moveto(0)

    def turn(self, delta):
        """Prevent navigation outside the actual result range."""
        target = self.page + delta
        if 1 <= target <= max(1, math.ceil(self.total / 8)):
            self.page = target
            guarded(self, self.refresh)


class MyProductsPage(ttk.Frame):
    """Manage all owner states, including legacy incomplete drafts."""

    def __init__(self, parent, actor):
        super().__init__(parent, padding=18)
        self.actor = actor
        self.rows = {}
        ttk.Label(self, text="我的商品", style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=8)
        for label, action in [
            ("创建草稿", self.create),
            ("编辑 / 补全旧草稿", self.edit),
            ("查看详情", self.detail),
            ("提交审核", self.submit),
            ("自行下架", self.delist),
            ("删除草稿", self.delete),
            ("刷新", self.refresh),
        ]:
            ttk.Button(
                toolbar, text=label, command=lambda function=action: guarded(self, function)
            ).pack(side="left", padx=3)
        ttk.Label(
            self,
            text="有等待或已确认预约时不能修改或自行下架；旧空草稿需补全后审核，或直接删除。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=8)
        self.table = DataTable(
            self,
            [
                ("id", "编号", 60),
                ("title", "商品标题", 240),
                ("category", "分类", 100),
                ("price", "价格（元）", 100),
                ("status", "状态", 100),
                ("version", "版本", 60),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", lambda event: guarded(self, self.detail))
        self.refresh()

    def refresh(self):
        """Load every owned product state."""
        rows = list_my_products(self.actor)
        self.rows = {row["id"]: row for row in rows}
        self.table.fill(
            (
                row["id"],
                (
                    row["id"],
                    row["title"] or "（待补全标题）",
                    row["category_name"] or "（待选择分类）",
                    price(row["price_cents"]),
                    status_label(row["status"]),
                    row["version"],
                ),
            )
            for row in rows
        )

    def create(self):
        """Open an empty create form."""
        ProductEditor(self, self.actor, self.refresh)

    def edit(self):
        """Open a form carrying the current version for conflict checking."""
        ProductEditor(self, self.actor, self.refresh, self.table.selected())

    def detail(self):
        """Inspect current content and review results."""
        ProductDetail(self, self.actor, self.table.selected())

    def submit(self):
        """Submit selected complete content for review."""
        key = self.table.selected()
        submit_review(self.actor, key, self.rows[key]["version"])
        self.refresh()

    def delist(self):
        """Perform a checked voluntary delisting."""
        delist_product(self.actor, self.table.selected())
        self.refresh()

    def delete(self):
        """Confirm soft deletion of a selected draft."""
        key = self.table.selected()
        if messagebox.askyesno(
            "删除草稿", "确定删除选中的草稿？商品将从列表移除，审计记录保留。", parent=self
        ):
            delete_draft(self.actor, key)
            self.refresh()
