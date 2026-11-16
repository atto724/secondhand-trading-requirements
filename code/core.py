"""Shared transaction, audit, notification and validation utilities."""

import json
import logging
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from threading import RLock

from database import connect_database

LOGGER = logging.getLogger(__name__)
WRITE_LOCK = RLock()


def now():
    """Return an ISO timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def json_text(value):
    """Serialize rows and dictionaries without losing Chinese text."""
    if hasattr(value, "keys"):
        value = dict(value)
    return json.dumps(value, ensure_ascii=False, default=str)


@contextmanager
def transaction():
    """Serialize writers and roll back every update on failure."""
    # Queue same-process writers instead of sending 100 connections into busy polling.
    # SQLite still provides the authoritative lock across separate application processes.
    with WRITE_LOCK:
        with closing(connect_database()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection


def active(connection, actor):
    """Require an existing active account."""
    row = connection.execute("SELECT * FROM accounts WHERE id=?", (actor,)).fetchone()
    if row is None or row["status"] != "active":
        raise ValueError("账号不存在或已被禁用，请重新登录。")
    return row


def require_role(connection, actor, role_name):
    """Require an active account and a current database role assignment."""
    active(connection, actor)
    permitted = connection.execute(
        "SELECT 1 FROM account_roles ar JOIN roles r ON r.id=ar.role_id "
        "WHERE ar.account_id=? AND r.name=?",
        (actor, role_name),
    ).fetchone()
    if permitted is None:
        raise ValueError("当前账号没有执行此操作所需的角色。")


def admin(connection, actor):
    """Require current administrator permission."""
    require_role(connection, actor, "admin")


def product_row(connection, product_id):
    """Fetch a nondeleted product."""
    row = connection.execute(
        "SELECT * FROM products WHERE id=? AND deleted=0", (product_id,)
    ).fetchone()
    if row is None:
        raise ValueError("商品不存在或已删除，请刷新。")
    return row


def owner(connection, actor, product_id):
    """Require seller ownership as well as an active seller role."""
    require_role(connection, actor, "seller")
    row = product_row(connection, product_id)
    if row["seller_id"] != actor:
        raise ValueError("只能操作自己的商品。")
    return row


def audit(
    connection, actor, action, kind, object_id, before="", after="", reason="", result="success"
):
    """Append a structured audit record in the caller's transaction."""
    connection.execute(
        "INSERT INTO audit_logs(actor_id,action,object_type,object_id,before_value,"
        "after_value,result,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            actor,
            action,
            kind,
            object_id,
            json_text(before),
            json_text(after),
            result,
            reason,
            now(),
        ),
    )


def audited(action):
    """Record failed service calls after their business transaction rolls back."""

    def decorate(function):
        @wraps(function)
        def wrapped(actor, *args, **kwargs):
            try:
                return function(actor, *args, **kwargs)
            except Exception as error:
                try:
                    with transaction() as connection:
                        exists = connection.execute(
                            "SELECT id FROM accounts WHERE id=?", (actor,)
                        ).fetchone()
                        audit(
                            connection,
                            actor if exists else None,
                            action,
                            "request",
                            None,
                            reason=str(error),
                            result="failure",
                        )
                except Exception:
                    LOGGER.exception("Could not append failure audit")
                raise

        return wrapped

    return decorate


def notify(connection, receiver, event, content, product_id=None, reservation_id=None):
    """Deliver a local notification without undoing completed business updates."""
    connection.execute("SAVEPOINT notification")
    try:
        connection.execute(
            "INSERT INTO messages(receiver_id,product_id,reservation_id,event_type,"
            "content,created_at) VALUES(?,?,?,?,?,?)",
            (receiver, product_id, reservation_id, event, content, now()),
        )
    except Exception:
        connection.execute("ROLLBACK TO notification")
        LOGGER.exception("Notification unavailable; business records remain authoritative")
    finally:
        connection.execute("RELEASE notification")


def history(connection, actor, product):
    """Preserve the previous public product content before any edit."""
    content = dict(product)
    content["images"] = [
        dict(row)
        for row in connection.execute(
            "SELECT file_path,display_order FROM product_images WHERE product_id=? ORDER BY display_order",
            (product["id"],),
        )
    ]
    connection.execute(
        "INSERT INTO product_history(product_id,version,content,actor_id,created_at) "
        "VALUES(?,?,?,?,?)",
        (product["id"], product["version"], json_text(content), actor, now()),
    )


def money(text, allow_zero=False):
    """Convert yuan text to exact integer cents."""
    try:
        amount = Decimal(str(text).strip())
        if not amount.is_finite() or not 0 <= amount <= Decimal("99999999.99"):
            raise ValueError("价格应在 0～99999999.99 元之间。")
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise ValueError("价格最多精确到分。")
        if not allow_zero and cents == 0:
            raise ValueError("价格必须大于零。")
        return int(cents)
    except InvalidOperation as error:
        raise ValueError("请输入有效的数字价格。") from error


def price(cents):
    """Format cents for display without floating point arithmetic."""
    return f"{cents // 100}.{cents % 100:02d}"


def validate_content(connection, title, description, category_id, cents):
    """Apply the strengthened required fields even to legacy drafts."""
    if not title.strip() or len(title.strip()) > 100:
        raise ValueError("标题必填，长度不能超过 100 个字符。")
    if not description.strip() or len(description.strip()) > 5000:
        raise ValueError("描述必填，长度不能超过 5000 个字符。")
    if isinstance(cents, bool) or not isinstance(cents, int) or not 1 <= cents <= 9_999_999_999:
        raise ValueError("价格必须大于零且不超过 99999999.99 元。")
    if not connection.execute(
        "SELECT id FROM categories WHERE id=? AND is_active=1", (category_id,)
    ).fetchone():
        raise ValueError("请选择有效分类。")


def has_live_reservations(connection, product_id):
    """Treat delivery, cancellation and manual handling as active reservations."""
    return (
        connection.execute(
            "SELECT 1 FROM reservations WHERE product_id=? AND status IN "
            "('waiting','confirmed','delivered','cancel_requested','manual') LIMIT 1",
            (product_id,),
        ).fetchone()
        is not None
    )


def check_version(product, expected):
    """Reject updates originating from a stale editor or review page."""
    if product["version"] != expected:
        raise ValueError("商品内容已变化，请刷新后重试。")


def reason_required(reason):
    """Normalize and require a short operational explanation."""
    reason = reason.strip()
    if not reason or len(reason) > 1000:
        raise ValueError("请填写原因或核实依据，长度为 1～1000 个字符。")
    return reason
