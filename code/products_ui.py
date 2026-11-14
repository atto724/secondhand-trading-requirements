"""Seller product list window."""

import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import filedialog, messagebox, ttk
from domain import PRODUCT_STATUS_LABELS, ProductStatus
from products import (
    add_product_image,
    create_draft,
    list_categories,
    list_my_products,
)
from images import validate_image
class MyProductsWindow(tk.Toplevel):
    """Display products belonging to the current seller."""

    def __init__(self, parent: tk.Misc, seller_id: int) -> None:
        super().__init__(parent)
        self.seller_id = seller_id
        self.title("我的商品")
        self.geometry("850x450")
        self.transient(parent)

        container = ttk.Frame(self, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(container)
        toolbar.pack(fill=tk.X, pady=(0, 12))

        ttk.Button(
            toolbar, text="刷新", command=self.refresh
        ).pack(side=tk.LEFT)

        ttk.Button(
            toolbar,
            text="创建草稿",
            command=self.open_draft,
        ).pack(side=tk.LEFT, padx=8)

 
        ttk.Button(
            toolbar, text="关闭", command=self.destroy
        ).pack(side=tk.RIGHT)

        table_frame = ttk.Frame(container)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("id", "title", "category", "price", "status")
        self.table = ttk.Treeview(
            table_frame, columns=columns, show="headings"
        )

        headings = [
            ("id", "编号", 60),
            ("title", "商品标题", 280),
            ("category", "分类", 100),
            ("price", "价格（元）", 100),
            ("status", "状态", 100),
        ]
        for name, label, width in headings:
            self.table.heading(name, text=label)
            self.table.column(name, width=width, minwidth=50)

        scrollbar = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.table.yview
        )
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.refresh()
        self.grab_set()

    def refresh(self) -> None:
        """Reload the current seller's products."""
        try:
            products = list_my_products(self.seller_id)
        except ValueError as error:
            messagebox.showerror("查询失败", str(error), parent=self)
            return

        for item in self.table.get_children():
            self.table.delete(item)

        for product in products:
            cents = product["price_cents"]
            price = f"{cents // 100}.{cents % 100:02d}"
            status = PRODUCT_STATUS_LABELS[
                ProductStatus(product["status"])
            ]
            self.table.insert(
                "",
                tk.END,
                iid=str(product["id"]),
                values=(
                    product["id"],
                    product["title"] or "（未填写标题）",
                    product["category_name"] or "（未分类）",
                    price,
                    status,
                ),
            )
    def open_draft(self):
        """Open the draft form and refresh the list after saving."""
        window = DraftWindow(self, self.seller_id, self.refresh)
        self.wait_window(window)
        if self.winfo_exists():
            self.grab_set()

    def add_image(self) -> None:
        """Attach one selected image to the selected product."""
        selected = self.table.selection()
        if len(selected) != 1:
            messagebox.showwarning(
                "请选择商品",
                "请先选中一件草稿商品。",
                parent=self,
            )
            return

        product_id = int(selected[0])
        source_path = filedialog.askopenfilename(
            parent=self,
            title="选择商品图片",
            filetypes=[
                ("JPEG 和 PNG 图片", "*.jpg *.jpeg *.png"),
                ("所有文件", "*.*"),
            ],
        )
        if not source_path:
            return

        try:
            add_product_image(
                self.seller_id, product_id, source_path
            )
        except (ValueError, OSError) as error:
            messagebox.showerror(
                "添加失败", str(error), parent=self
            )
        else:
            messagebox.showinfo(
                "添加成功",
                "图片已保存。每件商品最多添加 5 张。",
                parent=self,
            )

class DraftWindow(tk.Toplevel):
    """Collect required information for a product draft."""

    def __init__(self, parent, seller_id, on_saved):
        super().__init__(parent)
        self.seller_id = seller_id
        self.on_saved = on_saved
        self.image_paths = []
        self.title("创建商品草稿")
        self.geometry("600x600")
        self.transient(parent)

        self.product_title = tk.StringVar(master=self)
        self.price = tk.StringVar(master=self)
        self.category = tk.StringVar(master=self)
        self.categories = {
            row["name"]: row["id"] for row in list_categories()
        }

        form = ttk.Frame(self, padding=20)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)
        form.rowconfigure(3, weight=1)

        ttk.Label(form, text="标题 *").grid(
            row=0, column=0, padx=(0, 12), pady=8, sticky=tk.W
        )
        title_entry = ttk.Entry(
            form, textvariable=self.product_title
        )
        title_entry.grid(row=0, column=1, pady=8, sticky=tk.EW)

        ttk.Label(form, text="分类 *").grid(
            row=1, column=0, padx=(0, 12), pady=8, sticky=tk.W
        )
        category_box = ttk.Combobox(
            form,
            textvariable=self.category,
            values=list(self.categories),
            state="readonly",
        )
        category_box.grid(row=1, column=1, pady=8, sticky=tk.EW)

        ttk.Label(form, text="价格（元）*").grid(
            row=2, column=0, padx=(0, 12), pady=8, sticky=tk.W
        )
        price_entry = ttk.Entry(form, textvariable=self.price)
        price_entry.grid(row=2, column=1, pady=8, sticky=tk.EW)

        ttk.Label(form, text="描述 *").grid(
            row=3, column=0, padx=(0, 12), pady=8, sticky=tk.NW
        )
        self.description = tk.Text(
            form, height=8, width=35, wrap=tk.WORD
        )
        self.description.grid(
            row=3, column=1, pady=8, sticky=tk.NSEW
        )

        image_area = ttk.Frame(form)
        image_area.grid(
            row=4, column=0, columnspan=2, pady=8, sticky=tk.EW
        )

        ttk.Button(
            image_area,
            text="选择商品图片（选填）",
            command=self.choose_images,
        ).pack(side=tk.LEFT)

        ttk.Button(
            image_area,
            text="清空选择",
            command=self.clear_images,
        ).pack(side=tk.LEFT, padx=8)

        self.image_summary = ttk.Label(
            form, text="尚未选择图片", wraplength=480
        )
        self.image_summary.grid(
            row=5, column=0, columnspan=2, pady=8, sticky=tk.W
        )

        ttk.Label(
            form,
            text="* 为必填；描述框 Enter 换行，Ctrl+Enter 保存。",
        ).grid(row=6, column=0, columnspan=2, pady=8)

        ttk.Button(
            form, text="保存草稿", command=self.save
        ).grid(row=7, column=0, columnspan=2, pady=12)
        self.title_entry = title_entry
        self.category_box = category_box
        self.price_entry = price_entry

        title_entry.bind(
            "<Return>", lambda event: self.advance_field("title")
        )
        category_box.bind(
            "<Return>", lambda event: self.advance_field("category")
        )
        price_entry.bind(
            "<Return>", lambda event: self.advance_field("price")
        )
        self.bind("<Control-Return>", self.save_from_keyboard)

        title_entry.focus_set()
        self.grab_set()

    def save_from_keyboard(self, event):
        """Save once and stop further handling of this key event."""
        self.save()
        return "break"

    def save(self):
        """Validate the form and persist the product."""
        for field in ("title", "category", "price", "description"):
            try:
                self.validate_field(field)
            except ValueError as error:
                messagebox.showwarning(
                    "请检查输入", str(error), parent=self
                )
                self.field_widget(field).focus_set()
                return
        try:
            category_id = self.categories.get(self.category.get())
            if category_id is None:
                raise ValueError("请选择商品分类。")

            price_text = self.price.get().strip()
            if not price_text:
                raise ValueError("请填写商品价格。")

            amount = Decimal(price_text)
            if (
                not amount.is_finite()
                or not Decimal("0.01") <= amount <= Decimal("99999999.99")
            ):
                raise ValueError("价格须在 0.01～99999999.99 元之间。")

            cents = amount * 100
            if cents != cents.to_integral_value():
                raise ValueError("价格最多精确到分。")

            create_draft(
                self.seller_id,
                title=self.product_title.get(),
                description=self.description.get("1.0", "end-1c"),
                category_id=category_id,
                price_cents=int(cents),
            )
        except InvalidOperation:
            messagebox.showerror(
                "保存失败", "请输入有效的数字价格。", parent=self
            )
        except ValueError as error:
            messagebox.showerror("保存失败", str(error), parent=self)
        else:
            self.on_saved()
            self.destroy()

    def choose_images(self):
        """Select and validate images without saving them yet."""
        paths = filedialog.askopenfilenames(
            parent=self,
            title="选择商品图片，最多 5 张",
            filetypes=[
                ("JPEG 和 PNG 图片", "*.jpg *.jpeg *.png"),
                ("所有文件", "*.*"),
            ],
        )
        if not paths:
            return

        candidates = list(dict.fromkeys(self.image_paths + list(paths)))
        if len(candidates) > 5:
            messagebox.showerror(
                "选择失败", "每件商品最多选择 5 张图片。", parent=self
            )
            return

        try:
            for path in candidates:
                validate_image(path)
        except (ValueError, OSError) as error:
            messagebox.showerror("选择失败", str(error), parent=self)
            return

        self.image_paths = candidates
        self.image_summary.configure(
            text=f"已选择 {len(candidates)} 张图片（等待保存）"
        )

    def clear_images(self):
        """Discard the current image selection."""
        self.image_paths.clear()
        self.image_summary.configure(text="尚未选择图片")

    def validate_field(self, field):
        """Validate one required field."""
        if field == "title":
            title = self.product_title.get().strip()
            if not title:
                raise ValueError("请填写商品标题。")
            if len(title) > 100:
                raise ValueError("商品标题不能超过 100 个字符。")

        elif field == "category":
            if self.category.get() not in self.categories:
                raise ValueError("请选择商品分类。")

        elif field == "price":
            text = self.price.get().strip()
            if not text:
                raise ValueError("请填写商品价格。")
            try:
                amount = Decimal(text)
                if (
                    not amount.is_finite()
                    or not Decimal("0.01")
                    <= amount
                    <= Decimal("99999999.99")
                ):
                    raise ValueError("价格须在 0.01～99999999.99 元之间。")
                if amount * 100 != (amount * 100).to_integral_value():
                    raise ValueError("价格最多精确到分。")
            except InvalidOperation as error:
                raise ValueError("请输入有效的数字价格。") from error

        elif field == "description":
            description = self.description.get("1.0", "end-1c").strip()
            if not description:
                raise ValueError("请填写商品描述。")
            if len(description) > 5000:
                raise ValueError("商品描述不能超过 5000 个字符。")

    def field_widget(self, field):
        """Return the input widget for a field."""
        return {
            "title": self.title_entry,
            "category": self.category_box,
            "price": self.price_entry,
            "description": self.description,
        }[field]

    def advance_field(self, field):
        """Move forward only when the current field is valid."""
        try:
            self.validate_field(field)
        except ValueError as error:
            messagebox.showwarning("请检查输入", str(error), parent=self)
            self.field_widget(field).focus_set()
        else:
            next_field = {
                "title": "category",
                "category": "price",
                "price": "description",
            }[field]
            self.field_widget(next_field).focus_set()
        return "break"