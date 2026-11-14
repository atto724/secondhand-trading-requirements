"""Product management services."""
import sqlite3
import database
from images import copy_image

from contextlib import closing

from accounts import require_role
from database import connect_database
from domain import ProductStatus


def create_draft(
    seller_id: int,
    title: str = "",
    description: str = "",
    category_id: int | None = None,
    price_cents: int = 0,
) -> int:
    """Create a product draft owned by an active seller."""
    title = title.strip()
    description = description.strip()
    if not title:
        raise ValueError("请填写商品标题。")
    if not description:
        raise ValueError("请填写商品描述。")
    if category_id is None:
        raise ValueError("请选择商品分类。")

    if len(title) > 100:
        raise ValueError("商品标题不能超过 100 个字符。")
    if len(description) > 5000:
        raise ValueError("商品描述不能超过 5000 个字符。")
    if (
        type(price_cents) is not int
        or not 1 <= price_cents <= 9_999_999_999
    ):
        raise ValueError("价格必须在 0.01～99999999.99 元之间。")

    if category_id is not None and type(category_id) is not int:
        raise ValueError("分类编号必须为整数。")

    with closing(connect_database()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            require_role(connection, seller_id, "seller")

            if category_id is not None:
                category = connection.execute(
                    "SELECT id FROM categories WHERE id = ?",
                    (category_id,),
                ).fetchone()
                if category is None:
                    raise ValueError("所选分类不存在。")

            cursor = connection.execute(
                "INSERT INTO products "
                "(seller_id, category_id, title, description, "
                "price_cents, status) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    seller_id,
                    category_id,
                    title,
                    description,
                    price_cents,
                    ProductStatus.DRAFT.value,
                ),
            )
            product_id = cursor.lastrowid

    return product_id

def list_my_products(seller_id: int) -> list[sqlite3.Row]:
    """Return products owned by an active seller."""
    with closing(connect_database()) as connection:
        connection.execute("BEGIN")
        with connection:
            require_role(connection, seller_id, "seller")
            products = connection.execute(
                "SELECT p.id, p.title, p.price_cents, p.status, "
                "p.version, p.created_at, c.name AS category_name "
                "FROM products AS p "
                "LEFT JOIN categories AS c ON c.id = p.category_id "
                "WHERE p.seller_id = ? "
                "ORDER BY p.created_at DESC, p.id DESC",
                (seller_id,),
            ).fetchall()

    return products

def list_categories() -> list[sqlite3.Row]:
    """Return available product categories."""
    with closing(connect_database()) as connection:
        return connection.execute(
            "SELECT id, name FROM categories ORDER BY id"
        ).fetchall()

def add_product_image(
    seller_id: int,
    product_id: int,
    source_path: str,
) -> int:
    """Attach an image to a draft owned by the current seller."""
    saved_path = None

    try:
        with closing(connect_database()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with connection:
                require_role(connection, seller_id, "seller")

                product = connection.execute(
                    "SELECT seller_id, status FROM products WHERE id = ?",
                    (product_id,),
                ).fetchone()

                if product is None or product["seller_id"] != seller_id:
                    raise ValueError("商品不存在或无权操作。")
                if product["status"] != ProductStatus.DRAFT.value:
                    raise ValueError("目前只能为草稿添加图片。")

                image_info = connection.execute(
                    "SELECT COUNT(*) AS total, "
                    "COALESCE(MAX(display_order), -1) AS last_order "
                    "FROM product_images WHERE product_id = ?",
                    (product_id,),
                ).fetchone()

                if image_info["total"] >= 5:
                    raise ValueError("每件商品最多添加 5 张图片。")

                saved_path = copy_image(source_path)
                cursor = connection.execute(
                    "INSERT INTO product_images "
                    "(product_id, file_path, display_order) "
                    "VALUES (?, ?, ?)",
                    (
                        product_id,
                        saved_path,
                        image_info["last_order"] + 1,
                    ),
                )
                image_id = cursor.lastrowid
    except Exception:
        if saved_path is not None:
            saved_file = database.DATABASE_PATH.parent / saved_path
            saved_file.unlink(missing_ok=True)
        raise

    return image_id
