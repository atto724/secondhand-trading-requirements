"""Compatibility names for the product windows used during guided development."""

from editor_ui import ProductEditor as DraftWindow

__all__ = ["DraftWindow", "MyProductsWindow"]
from market_ui import MyProductsPage
from ui_common import Window


class MyProductsWindow(Window):
    """Embed the current seller product page in a secondary window."""

    def __init__(self, parent, seller_id):
        super().__init__(parent, "我的商品", "1100x650")
        MyProductsPage(self, seller_id).pack(fill="both", expand=True)
