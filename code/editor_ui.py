"""Create/edit product form with required fields, previews and keyboard navigation."""

import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from catalog import product_detail, save_product, submit_review
from core import money, price
from images import validate_image
from products import list_categories
from ui_common import BG, guarded, stored_image, thumbnail


class ProductEditor(ttk.Frame):
    """Reuse one form for new products and version-checked edits."""

    def __init__(self, parent, actor, on_saved, product_id=None):
        original = product_detail(actor, product_id) if product_id else None
        super().__init__(parent)
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        header = ttk.Frame(self, padding=(22, 12))
        header.pack(fill="x")
        ttk.Button(header, text="← 返回我的商品", command=self.close).pack(side="left")
        ttk.Label(header, text="编辑商品" if product_id else "创建商品", style="Title.TLabel").pack(
            side="left", padx=20
        )
        footer = ttk.Frame(self, padding=(22, 8))
        footer.pack(side="bottom", fill="x")
        content = ttk.Frame(self)
        content.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(content, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(fill="both", expand=True)
        self.actor = actor
        self.on_saved = on_saved
        self.product_id = product_id
        self.original = original
        self.existing = list(self.original["images"]) if self.original else []
        self.sources = []
        self.photos = []
        self.categories = {row["name"]: row["id"] for row in list_categories()}
        self.variables = {}
        self.widgets = {}
        self.saving = False
        body = ttk.Frame(self.canvas, padding=22)
        window = self.canvas.create_window(0, 0, window=body, anchor="nw")
        self.canvas.bind(
            "<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width)
        )
        body.bind(
            "<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text="完善商品信息", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 16)
        )
        form = ttk.Frame(body)
        form.grid(row=1, column=0, sticky="nsew", padx=(0, 22))
        form.columnconfigure(1, weight=1)
        form.rowconfigure(6, weight=1)
        definitions = [
            ("title", "商品名称 *", None),
            ("category", "商品分类 *", list(self.categories)),
            ("price", "价格（元）*", None),
            ("condition", "成色", ["未注明", "全新", "九成新", "八成新", "有使用痕迹"]),
            ("shipping", "运费 / 交付", ["线下自提", "包邮", "不包邮"]),
        ]
        for row, (key, label, choices) in enumerate(definitions):
            variable = tk.StringVar(master=self)
            self.variables[key] = variable
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=7, padx=(0, 12))
            widget = (
                ttk.Combobox(form, textvariable=variable, values=choices, state="readonly")
                if choices
                else ttk.Entry(form, textvariable=variable)
            )
            widget.grid(row=row, column=1, sticky="ew", pady=7)
            self.widgets[key] = widget
        self.variables["condition"].set("未注明")
        self.variables["shipping"].set("线下自提")
        self.negotiable = tk.BooleanVar(master=self)
        ttk.Checkbutton(form, text="可议价 / 可小刀", variable=self.negotiable).grid(
            row=5, column=1, sticky="w", pady=6
        )
        ttk.Label(form, text="商品描述 *").grid(row=6, column=0, sticky="nw", pady=8)
        self.description = tk.Text(
            form, height=8, width=35, wrap="word", font=("Microsoft YaHei", 10)
        )
        self.description.grid(row=6, column=1, sticky="nsew", pady=8)
        self.widgets["description"] = self.description
        self.image_area = ttk.Frame(body)
        self.image_area.grid(row=1, column=1, sticky="nsew")
        ttk.Label(self.image_area, text="商品图片（选填，最多 5 张）").pack(anchor="w")
        buttons = ttk.Frame(self.image_area)
        buttons.pack(fill="x", pady=10)
        ttk.Button(
            buttons, text="添加图片", command=lambda: guarded(self, self.choose_images)
        ).pack(side="left")
        ttk.Button(buttons, text="移除所选", command=self.remove_image).pack(side="left", padx=6)
        self.image_list = tk.Listbox(self.image_area, height=5, exportselection=False)
        self.image_list.pack(fill="x", pady=5)
        self.preview = ttk.Label(self.image_area)
        self.preview.pack(pady=10)
        self.image_list.bind("<<ListboxSelect>>", self.preview_selected)
        ttk.Label(
            footer,
            text="* 必填；Enter 下一项；描述框 Enter 换行；Ctrl+Enter 保存。",
            wraplength=800,
        ).pack(anchor="w", pady=6)
        ttk.Label(footer, text="草稿仅本人可见，审核通过后才公开。", style="Sub.TLabel").pack(
            anchor="w", pady=4
        )
        actions = ttk.Frame(footer)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="取消", command=self.close).pack(side="left")
        ttk.Button(actions, text="保存草稿", command=lambda: self.save(False)).pack(
            side="right", padx=5
        )
        ttk.Button(
            actions, text="提交审核", style="Accent.TButton", command=lambda: self.save(True)
        ).pack(side="right", padx=5)
        sequence = ["title", "category", "price", "condition", "shipping", "description"]
        for key, next_key in zip(sequence, sequence[1:]):
            self.widgets[key].bind(
                "<Return>",
                lambda event, current=key, target=next_key: self.advance(current, target),
            )
        self.bind_shortcuts(self)
        if self.original:
            item = self.original
            for key, value in (
                ("title", item["title"]),
                ("price", price(item["price_cents"])),
                ("condition", item["condition_label"]),
                ("shipping", item["shipping"]),
            ):
                self.variables[key].set(value)
            category = next(
                (name for name, key in self.categories.items() if key == item["category_id"]), ""
            )
            self.variables["category"].set(category)
            self.negotiable.set(bool(item["negotiable"]))
            self.description.insert("1.0", item["description"])
        self.refresh_images()
        self.widgets["title"].focus_set()

    def bind_shortcuts(self, widget):
        """Keep shortcuts local to this form now that it is not a separate window."""
        widget.bind("<Control-Return>", self.keyboard_save)
        widget.bind("<Escape>", self.close)
        for child in widget.winfo_children():
            self.bind_shortcuts(child)

    def close(self, _event=None):
        """Return to the existing list without writing pending form changes."""
        self.destroy()
        return "break"

    def validate_field(self, key):
        """Validate before moving focus or submitting with skipped fields."""
        if key == "title":
            value = self.variables[key].get().strip()
            if not value or len(value) > 100:
                raise ValueError("标题必填，长度为 1～100 个字符。")
        elif key == "category":
            if self.variables[key].get() not in self.categories:
                raise ValueError("请选择商品分类。")
        elif key == "price":
            money(self.variables[key].get())
        elif key == "description":
            value = self.description.get("1.0", "end-1c").strip()
            if not value or len(value) > 5000:
                raise ValueError("描述必填，长度为 1～5000 个字符。")

    def advance(self, key, next_key):
        """Advance only after the current input passes validation."""
        try:
            self.validate_field(key)
        except ValueError as error:
            messagebox.showwarning("请检查输入", str(error), parent=self)
            self.widgets[key].focus_set()
        else:
            self.widgets[next_key].focus_set()
        return "break"

    def keyboard_save(self, _event):
        """Save without turning Ctrl+Enter into a description newline."""
        self.save(False)
        return "break"

    def choose_images(self):
        """Validate image choices before retaining them in form memory."""
        paths = filedialog.askopenfilenames(
            parent=self, title="选择商品图片", filetypes=[("JPEG / PNG", "*.jpg *.jpeg *.png")]
        )
        candidates = list(dict.fromkeys(self.sources + list(paths)))
        if len(candidates) + len(self.existing) > 5:
            raise ValueError("最多选择 5 张图片，请先移除不需要的图片。")
        for path in candidates:
            validate_image(path)
        self.sources = candidates
        self.refresh_images()

    def refresh_images(self):
        """Refresh filenames and show the first available preview."""

        self.image_list.delete(0, "end")
        for image in self.existing:
            self.image_list.insert("end", "已保存 · " + Path(image["file_path"]).name[:16])
        for source in self.sources:
            self.image_list.insert("end", Path(source).name)
        if self.existing or self.sources:
            self.image_list.selection_set(0)
            self.preview_selected()
        else:
            self.preview.configure(image="", text="尚未选择图片")
            self.photos.clear()

    def preview_selected(self, _event=None):
        """Display a selected local or already stored image."""
        selection = self.image_list.curselection()
        if not selection:
            return
        index = selection[0]
        path = (
            stored_image(self.existing[index]["file_path"])
            if index < len(self.existing)
            else self.sources[index - len(self.existing)]
        )
        try:
            photo = thumbnail(self, path, (270, 230))
            self.photos = [photo]
            self.preview.configure(image=photo, text="")
        except (OSError, ValueError):
            self.preview.configure(image="", text="图片缺失或无法预览，请移除后重新选择。")

    def remove_image(self):
        """Remove a selection from the pending form without changing storage yet."""
        selection = self.image_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index < len(self.existing):
            self.existing.pop(index)
        else:
            self.sources.pop(index - len(self.existing))
        self.refresh_images()

    def save(self, submit):
        """Save a complete product once, then optionally submit the saved version."""
        if self.saving:
            return
        for key in ("title", "category", "price", "description"):
            try:
                self.validate_field(key)
            except ValueError as error:
                messagebox.showwarning("请检查输入", str(error), parent=self)
                self.widgets[key].focus_set()
                return
        self.saving = True
        succeeded = False
        try:
            product_id = save_product(
                self.actor,
                self.variables["title"].get(),
                self.description.get("1.0", "end-1c"),
                self.categories[self.variables["category"].get()],
                money(self.variables["price"].get()),
                self.sources,
                self.product_id,
                self.original["version"] if self.original else None,
                self.variables["condition"].get(),
                self.variables["shipping"].get(),
                self.negotiable.get(),
                [image["id"] for image in self.existing],
            )
            self.product_id = product_id
            self.original = product_detail(self.actor, product_id)
            self.existing = list(self.original["images"])
            self.sources.clear()
            self.refresh_images()
            succeeded = True
            if submit and self.original["status"] != "pending_review":
                submit_review(self.actor, product_id, self.original["version"])
        except (ValueError, OSError, sqlite3.Error) as error:
            prefix = "草稿已保存，但提交审核失败：" if succeeded else ""
            messagebox.showerror("操作未完成", prefix + str(error), parent=self)
        else:
            parent, callback = self.master, self.on_saved
            self.destroy()
            guarded(parent, callback)
        finally:
            self.saving = False
