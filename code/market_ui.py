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
from seller_ui import ChatPage, SellerPage
from trades import reserve
from ui_common import (
    ACCENT,
    BG,
    INK,
    PAPER,
    ProductRows,
    avatar_photo,
    guarded,
    stored_image,
    thumbnail,
)


def status_label(value):
    """Translate the persisted product state."""
    return PRODUCT_STATUS_LABELS[ProductStatus(value)]


class ProductDetail(tk.Frame):
    """An in-page detail view that preserves the underlying list and filters."""

    def __init__(self, parent, actor, product_id):
        item = product_detail(actor, product_id)
        super().__init__(parent, bg=BG)
        self.actor, self.item = actor, item
        self.photos, self.buttons, self.index = [], [], 0
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        tk.Button(
            self,
            text={
                "MyProductsPage": "← 返回我的商品",
                "SellerPage": "← 返回卖家主页",
                "ReviewPage": "← 返回审核列表",
            }.get(type(parent).__name__, "← 返回商品列表"),
            command=self.destroy,
            bg=BG,
            fg=ACCENT,
            relief="flat",
            cursor="hand2",
        ).pack(anchor="w", padx=22, pady=14)
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scroll.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        card = tk.Frame(canvas, bg=PAPER, highlightbackground="#edcdb7", highlightthickness=1)
        window = canvas.create_window(22, 0, window=card, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=max(700, event.width - 44)),
        )
        card.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        card.columnconfigure(1, weight=1)
        left = tk.Frame(card, bg=PAPER)
        left.grid(row=0, column=0, sticky="n", padx=24, pady=24)
        self.large = tk.Label(left, bg="#f3ece3", text="暂无商品图片", width=1)
        self.large.pack()
        strip = tk.Frame(left, bg=PAPER)
        strip.pack(pady=(12, 0))
        for index, image in enumerate(item["images"]):
            try:
                photo = thumbnail(self, stored_image(image["file_path"]), (58, 58))
                self.photos.append(photo)
            except (OSError, ValueError):
                photo = ""
            button = tk.Button(
                strip,
                image=photo,
                text=str(index + 1) if not photo else "",
                command=lambda value=index: self.select_image(value),
                bg=PAPER,
                relief="flat",
                borderwidth=2,
                cursor="hand2",
            )
            button.pack(side="left", padx=3)
            self.buttons.append(button)
        navigation = tk.Frame(left, bg=PAPER)
        navigation.pack(fill="x", pady=8)
        self.previous = ttk.Button(
            navigation, text="‹ 上一张", command=lambda: self.select_image(self.index - 1)
        )
        self.previous.pack(side="left")
        self.counter = tk.Label(navigation, bg=PAPER)
        self.counter.pack(side="left", expand=True)
        self.next_button = ttk.Button(
            navigation, text="下一张 ›", command=lambda: self.select_image(self.index + 1)
        )
        self.next_button.pack(side="right")
        right = tk.Frame(card, bg=PAPER)
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 24), pady=24)

        def label(text, **options):
            widget = tk.Label(right, text=text, bg=PAPER, anchor="w", justify="left", **options)
            widget.pack(anchor="w", fill="x", pady=6)
            return widget

        title = label(
            item["title"] or "（未填写标题）", font=("Microsoft YaHei", 24), fg=INK, wraplength=420
        )
        label(item["category_name"] or "未分类", fg="#80634f")
        price_row = tk.Frame(right, bg=PAPER)
        price_row.pack(anchor="w", pady=8)
        tk.Label(
            price_row,
            text=f"¥ {price(item['price_cents'])}",
            bg=PAPER,
            fg=ACCENT,
            font=("Microsoft YaHei", 25),
        ).pack(side="left")
        if item["negotiable"]:
            tk.Label(price_row, text=" 可小刀 ", bg=ACCENT, fg="white").pack(side="left", padx=18)
        tags = tk.Frame(right, bg=PAPER)
        tags.pack(anchor="w", pady=8)
        for value in (status_label(item["status"]), item["condition_label"], item["shipping"]):
            tk.Label(tags, text=value, bg="#fff0df", fg=ACCENT, padx=9, pady=5).pack(
                side="left", padx=(0, 8)
            )
        description = label(item["description"] or "（未填写描述）", wraplength=420, fg=INK)
        can_book = (
            actor != item["seller_id"] and item["status"] == "published" and not item["blocked"]
        )
        ttk.Button(
            right,
            text=(
                "发起预约"
                if can_book
                else "本人商品" if actor == item["seller_id"] else "当前不可预约"
            ),
            style="Accent.TButton",
            state="normal" if can_book else "disabled",
            command=lambda: guarded(self, self.book),
        ).pack(anchor="w", pady=(12, 8))
        label("提交后可在「我的预约」查看确认进度。", fg="#80634f", wraplength=420)
        seller = tk.Frame(right, bg="#fffaf4", highlightbackground="#edcdb7", highlightthickness=1)
        seller.pack(fill="x", pady=(22, 10))
        avatar = tk.Label(seller, bg="#fffaf4")
        avatar.photo = avatar_photo(self, item["seller_id"], item["seller_avatar"])
        avatar.configure(image=avatar.photo)
        avatar.pack(side="left", padx=12, pady=10)
        tk.Label(
            seller, text=f"卖家 · {item['seller_name']}", bg="#fffaf4", fg=INK, padx=14, pady=14
        ).pack(anchor="w")

        def open_seller(_event=None):
            return guarded(
                self,
                lambda: SellerPage(
                    self, self.actor, self.item["seller_id"], detail_factory=ProductDetail
                ),
            )

        seller.configure(cursor="hand2")
        seller.bind("<Button-1>", open_seller)
        for widget in seller.winfo_children():
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", open_seller)
        ttk.Button(seller, text="进入卖家主页 →", command=open_seller).pack(
            anchor="e", padx=12, pady=(0, 10)
        )
        if actor != item["seller_id"]:
            ttk.Button(
                right,
                text="私信卖家 / 咨询商品",
                style="Accent.TButton",
                command=lambda: guarded(
                    self, lambda: ChatPage(self, self.actor, item["seller_id"], item["title"])
                ),
            ).pack(anchor="w", pady=8)
        label("付款和交付在线下协商，平台记录预约及交易结果。", fg="#80634f", wraplength=420)
        if item["reviews"]:
            review = item["reviews"][0]
            label(
                f"最近审核：{'通过' if review['approved'] else '驳回'} {review['reason']}",
                wraplength=420,
            )
        right.bind(
            "<Configure>",
            lambda event: [
                widget.configure(wraplength=max(200, event.width))
                for widget in (title, description)
            ],
        )
        self.bind("<Left>", lambda event: self.select_image(self.index - 1))
        self.bind("<Right>", lambda event: self.select_image(self.index + 1))
        self.bind("<Escape>", lambda event: self.destroy())
        for button in self.buttons:
            button.bind("<Left>", lambda event: self.select_image(self.index - 1))
            button.bind("<Right>", lambda event: self.select_image(self.index + 1))
            button.bind("<Escape>", lambda event: self.destroy())
        self.bind_wheel(self, canvas)
        self.focus_set()
        self.select_image(0)

    def bind_wheel(self, widget, canvas):
        """Scroll long descriptions without binding events outside this page."""
        widget.bind(
            "<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units")
        )
        for child in widget.winfo_children():
            self.bind_wheel(child, canvas)

    def select_image(self, index):
        """Switch a real thumbnail; never wrap past either end of the gallery."""
        images = self.item["images"]
        self.index = max(0, min(index, len(images) - 1))
        self.counter.configure(text=f"{self.index+1} / {len(images)}" if images else "暂无图片")
        self.previous.configure(state="normal" if self.index > 0 else "disabled")
        self.next_button.configure(state="normal" if self.index + 1 < len(images) else "disabled")
        for position, button in enumerate(self.buttons):
            button.configure(bg="#edcdb7" if position == self.index else PAPER)
        if images:
            try:
                self.large.photo = thumbnail(
                    self, stored_image(images[self.index]["file_path"]), (350, 350)
                )
                self.large.configure(image=self.large.photo, text="", width=350, height=350)
            except (OSError, ValueError):
                self.large.configure(image="", text="图片缺失，无法预览", width=35, height=18)
        else:
            self.large.configure(width=35, height=18)

    def book(self):
        """Keep booking authorization in the transactional service."""
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
        ttk.Button(
            toolbar,
            text="＋ 创建草稿",
            style="Accent.TButton",
            command=lambda: guarded(self, self.create),
        ).pack(side="right")
        ttk.Button(toolbar, text="刷新", command=lambda: guarded(self, self.refresh)).pack(
            side="right", padx=10
        )
        self.filter_bar = ttk.Frame(self)
        self.filter_bar.pack(fill="x", pady=10)
        self.filter_key = "all"
        self.table = ProductRows(self, on_open=lambda key: self.detail())
        self.table.pack(fill="both", expand=True)
        self.count = ttk.Label(self, style="Sub.TLabel", anchor="center")
        self.count.pack(fill="x", pady=8)
        self.refresh()

    def refresh(self):
        """Render owner product states without hiding historical or legacy drafts."""
        self.rows = {row["id"]: row for row in list_my_products(self.actor)}
        self.fill_products()

    def set_filter(self, key):
        """Keep state filtering local to this owner page."""
        self.filter_key = key
        self.fill_products()

    def fill_products(self):
        """Match the prototype's image, information, status and inline-action rows."""
        for widget in self.filter_bar.winfo_children():
            widget.destroy()
        for key, label in [("all", "全部")] + [
            (state.value, label) for state, label in PRODUCT_STATUS_LABELS.items()
        ]:
            count = sum(key in ("all", row["status"]) for row in self.rows.values())
            tk.Button(
                self.filter_bar,
                text=f"{label} {count}",
                command=lambda value=key: self.set_filter(value),
                bg=ACCENT if key == self.filter_key else BG,
                fg="white" if key == self.filter_key else INK,
                relief="flat",
                bd=0,
                padx=10,
                pady=7,
                cursor="hand2",
            ).pack(side="left", padx=(0, 5))
        cards = []
        for row in self.rows.values():
            if self.filter_key not in ("all", row["status"]):
                continue
            actions = [("查看详情", self.detail)]
            editable = not row["blocked"] and not row["has_live"]
            if editable and row["status"] in ("draft", "pending_review", "published", "delisted"):
                actions.append(("编辑 / 补全", self.edit))
            if editable and row["status"] in ("draft", "delisted"):
                actions.append(("提交审核", self.submit))
            if editable and row["status"] == "published":
                actions.append(("自行下架", self.delist))
            if editable and row["status"] == "draft":
                actions.append(("删除草稿", self.delete))
            description = (
                "有有效预约，暂时无法修改或下架"
                if row["has_live"]
                else {
                    "draft": "仅自己可见，完善信息后可提交审核",
                    "pending_review": "已提交，等待管理员审核",
                    "published": "已发布，可供买家浏览预约",
                    "reserved": "已确认买家，等待交易推进",
                    "sold": "交易已完成",
                    "delisted": "已自行下架，可编辑后重新审核",
                    "violation": "违规限制中，请查看处理记录",
                }.get(row["status"], "")
            )
            cards.append(
                {
                    "id": row["id"],
                    "title": row["title"] or "（待补全标题）",
                    "image": row["cover"],
                    "price": row["price_cents"],
                    "status": status_label(row["status"]),
                    "subtitle": (
                        f"{row['category_name'] or '未分类'} · 编号 {row['id']} · "
                        f"版本 {row['version']}\n{description}"
                    ),
                    "actions": actions,
                }
            )
        self.table.fill(cards)
        self.count.configure(text=f"共 {len(cards)} 件商品")

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
