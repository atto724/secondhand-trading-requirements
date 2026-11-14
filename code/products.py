"""Small compatibility facade for product services and category lookups."""

from contextlib import closing

from catalog import save_product, search_products
from database import connect_database


def list_categories():
    """Read the shared category list for forms and search filters."""
    with closing(connect_database()) as connection:
        return connection.execute("SELECT id,name FROM categories ORDER BY id").fetchall()


def create_draft(
    seller_id, title="", description="", category_id=None, price_cents=0, image_paths=None
):
    """Delegate the original guided API to the single authoritative implementation."""
    return save_product(seller_id, title, description, category_id, price_cents, image_paths)


def list_my_products(seller_id):
    """Return all owned rows through paginated queries rather than silently truncating."""
    result = []
    page = 1
    while True:
        rows, total = search_products(seller_id, scope="mine", page=page, page_size=100)
        result.extend(rows)
        if len(result) >= total:
            return result
        page += 1
