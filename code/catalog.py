"""Product lifecycle services shared by desktop views and tests."""

from contextlib import closing

import database
from accounts import require_role
from core import (
    active,
    admin,
    audit,
    audited,
    check_version,
    has_live_reservations,
    history,
    notify,
    now,
    owner,
    product_row,
    transaction,
    validate_content,
)
from database import connect_database
from images import copy_image


@audited("save_product")
def save_product(
    actor,
    title,
    description,
    category_id,
    cents,
    image_paths=None,
    product_id=None,
    expected_version=None,
    condition="未注明",
    shipping="线下自提",
    negotiable=False,
    keep_image_ids=None,
):
    """Create or edit a product and atomically attach selected image copies."""
    sources = list(image_paths or [])
    saved_paths = []
    if condition not in ("全新", "九成新", "八成新", "有使用痕迹", "未注明"):
        raise ValueError("请选择有效成色。")
    if shipping not in ("线下自提", "包邮", "不包邮"):
        raise ValueError("请选择有效运费方式。")
    try:
        with transaction() as connection:

            require_role(connection, actor, "seller")
            validate_content(connection, title, description, category_id, cents)
            previous = None
            if product_id is not None:
                previous = owner(connection, actor, product_id)
                check_version(previous, expected_version)
                if previous["status"] not in ("draft", "pending_review", "published", "delisted"):
                    raise ValueError("当前状态不允许编辑，请先完成交易或解除违规。")
                if previous["blocked"] or has_live_reservations(connection, product_id):
                    raise ValueError("有有效预约或违规限制，暂时无法修改。")
                history(connection, actor, previous)
                existing = connection.execute(
                    "SELECT id FROM product_images WHERE product_id=?", (product_id,)
                ).fetchall()
                existing_ids = {row["id"] for row in existing}
                kept = existing_ids if keep_image_ids is None else set(keep_image_ids)
                if not kept.issubset(existing_ids):
                    raise ValueError("图片不属于当前商品。")
                for image_id in existing_ids - kept:
                    connection.execute("DELETE FROM product_images WHERE id=?", (image_id,))
                # Old files remain available to historical snapshots and backups.
                status = "pending_review" if previous["status"] == "published" else "draft"
                connection.execute(
                    "UPDATE products SET title=?,description=?,category_id=?,price_cents=?,"
                    "condition_label=?,shipping=?,negotiable=?,status=?,version=version+1,"
                    "updated_at=? WHERE id=?",
                    (
                        title.strip(),
                        description.strip(),
                        category_id,
                        cents,
                        condition,
                        shipping,
                        int(negotiable),
                        status,
                        now(),
                        product_id,
                    ),
                )
            else:
                cursor = connection.execute(
                    "INSERT INTO products(seller_id,title,description,category_id,price_cents,"
                    "condition_label,shipping,negotiable,status) VALUES(?,?,?,?,?,?,?,?,'draft')",
                    (
                        actor,
                        title.strip(),
                        description.strip(),
                        category_id,
                        cents,
                        condition,
                        shipping,
                        int(negotiable),
                    ),
                )
                product_id = cursor.lastrowid
            rows = connection.execute(
                "SELECT display_order FROM product_images WHERE product_id=? ORDER BY display_order",
                (product_id,),
            ).fetchall()
            if len(rows) + len(sources) > 5:
                raise ValueError("每件商品最多保存 5 张图片。")
            offset = max((row[0] for row in rows), default=-1) + 1
            for order, source in enumerate(sources, offset):
                relative = copy_image(source)
                saved_paths.append(relative)
                connection.execute(
                    "INSERT INTO product_images(product_id,file_path,display_order) VALUES(?,?,?)",
                    (product_id, relative, order),
                )
            current = product_row(connection, product_id)
            audit(
                connection,
                actor,
                "save_product",
                "product",
                product_id,
                dict(previous) if previous else "",
                current,
            )
    except Exception:
        for relative in saved_paths:
            try:
                (database.DATABASE_PATH.parent / relative).unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return product_id


@audited("submit_review")
def submit_review(actor, product_id, expected_version):
    """Submit complete, unblocked owner content for administrator review."""
    with transaction() as connection:
        product = owner(connection, actor, product_id)
        check_version(product, expected_version)
        if product["status"] not in ("draft", "delisted") or product["blocked"]:
            raise ValueError("只有草稿或自行下架商品可以提交审核。")
        validate_content(
            connection,
            product["title"],
            product["description"],
            product["category_id"],
            product["price_cents"],
        )
        if has_live_reservations(connection, product_id):
            raise ValueError("存在有效预约，无法提交。")
        connection.execute(
            "UPDATE products SET status='pending_review',updated_at=? WHERE id=?",
            (now(), product_id),
        )
        audit(
            connection,
            actor,
            "submit_review",
            "product",
            product_id,
            product["status"],
            "pending_review",
        )


@audited("review")
def review_product(actor, product_id, expected_version, approved, reason=""):
    """Review exactly the version displayed to the administrator."""
    with transaction() as connection:
        admin(connection, actor)
        product = product_row(connection, product_id)
        check_version(product, expected_version)
        active(connection, product["seller_id"])
        if product["status"] != "pending_review" or product["blocked"]:
            raise ValueError("商品已被处理或受违规限制，请刷新。")
        if not approved and not reason.strip():
            raise ValueError("驳回审核必须填写原因。")
        validate_content(
            connection,
            product["title"],
            product["description"],
            product["category_id"],
            product["price_cents"],
        )
        status = "published" if approved else "draft"
        stamp = now()
        connection.execute(
            "UPDATE products SET status=?,updated_at=?,first_published_at="
            "CASE WHEN ? THEN COALESCE(first_published_at,?) ELSE first_published_at END WHERE id=?",
            (status, stamp, bool(approved), stamp, product_id),
        )
        connection.execute(
            "INSERT INTO reviews(product_id,version,admin_id,approved,reason,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (product_id, expected_version, actor, int(approved), reason, stamp),
        )
        audit(
            connection,
            actor,
            "review_approved" if approved else "review_rejected",
            "product",
            product_id,
            product["status"],
            status,
            reason,
        )
        notify(
            connection, product["seller_id"], "review", f"商品审核：{status}。{reason}", product_id
        )


@audited("delist")
def delist_product(actor, product_id):
    """Allow voluntary delisting only when no live reservation exists."""
    with transaction() as connection:
        product = owner(connection, actor, product_id)
        if product["status"] != "published" or has_live_reservations(connection, product_id):
            raise ValueError("仅无有效预约的已发布商品可以自行下架。")
        connection.execute(
            "UPDATE products SET status='delisted',updated_at=? WHERE id=?", (now(), product_id)
        )
        audit(connection, actor, "delist", "product", product_id, "published", "delisted")


@audited("delete_draft")
def delete_draft(actor, product_id):
    """Soft-delete a draft, preserving history and stored images."""
    with transaction() as connection:
        product = owner(connection, actor, product_id)
        if product["status"] != "draft" or has_live_reservations(connection, product_id):
            raise ValueError("只能删除无有效预约的草稿。")
        connection.execute(
            "UPDATE products SET deleted=1,updated_at=? WHERE id=?", (now(), product_id)
        )
        audit(connection, actor, "delete_draft", "product", product_id, product, "deleted")


def product_detail(actor, product_id):
    """Return public content, or private content to its owner/administrator."""
    with closing(connect_database()) as connection:
        active(connection, actor)
        product = product_row(connection, product_id)
        is_admin = connection.execute(
            "SELECT 1 FROM account_roles ar JOIN roles r ON r.id=ar.role_id "
            "WHERE ar.account_id=? AND r.name='admin'",
            (actor,),
        ).fetchone()
        seller = connection.execute(
            "SELECT username,status FROM accounts WHERE id=?", (product["seller_id"],)
        ).fetchone()
        public = (
            product["status"] == "published"
            and not product["blocked"]
            and seller["status"] == "active"
        )
        if not public and product["seller_id"] != actor and not is_admin:
            raise ValueError("商品当前不可公开查看，请从预约记录查看历史快照。")
        result = dict(product)
        result["seller_name"] = seller["username"]
        result["images"] = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM product_images WHERE product_id=? ORDER BY display_order",
                (product_id,),
            )
        ]
        result["reviews"] = (
            [
                dict(row)
                for row in connection.execute(
                    "SELECT version,approved,reason,created_at FROM reviews WHERE product_id=? ORDER BY id DESC",
                    (product_id,),
                )
            ]
            if product["seller_id"] == actor or is_admin
            else []
        )
        return result


def search_products(
    actor,
    keyword="",
    category_id=None,
    minimum=None,
    maximum=None,
    sort="latest",
    page=1,
    page_size=8,
    scope="public",
    status="",
):
    """Apply combined filters and real pagination without exposing private drafts."""
    if isinstance(page, bool) or not isinstance(page, int) or page < 1 or not 1 <= page_size <= 100:
        raise ValueError("分页参数无效。")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("最低价不能高于最高价。")
    orders = {
        "latest": "p.id DESC",
        "price_asc": "p.price_cents,p.id DESC",
        "price_desc": "p.price_cents DESC,p.id DESC",
    }
    if sort not in orders:
        raise ValueError("排序方式无效。")
    with closing(connect_database()) as connection:
        active(connection, actor)
        clauses, values = ["p.deleted=0"], []
        if scope == "public":
            clauses += ["p.status='published'", "p.blocked=0", "a.status='active'"]
        elif scope == "mine":
            clauses.append("p.seller_id=?")
            values.append(actor)
        elif scope == "admin":
            admin(connection, actor)
        else:
            raise ValueError("查询范围无效。")
        if keyword.strip():
            clauses.append("(instr(p.title,?)>0 OR instr(p.description,?)>0)")
            values += [keyword.strip(), keyword.strip()]
        if category_id is not None:
            clauses.append("p.category_id=?")
            values.append(category_id)
        for operator, bound in ((">=", minimum), ("<=", maximum)):
            if bound is not None:
                clauses.append(f"p.price_cents {operator} ?")
                values.append(bound)
        if status:
            clauses.append("p.status=?")
            values.append(status)
        base = (
            " FROM products p JOIN accounts a ON a.id=p.seller_id "
            "LEFT JOIN categories c ON c.id=p.category_id WHERE " + " AND ".join(clauses)
        )
        count = connection.execute("SELECT COUNT(*)" + base, values).fetchone()[0]
        rows = connection.execute(
            "SELECT p.*,c.name AS category_name,a.username AS seller_name,"
            "(SELECT file_path FROM product_images WHERE product_id=p.id "
            "ORDER BY display_order LIMIT 1) AS cover"
            + base
            + " ORDER BY "
            + orders[sort]
            + " LIMIT ? OFFSET ?",
            values + [page_size, (page - 1) * page_size],
        ).fetchall()
        return [dict(row) for row in rows], count
