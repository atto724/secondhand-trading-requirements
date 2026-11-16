"""Reservation and offline delivery state machine."""

import json
from datetime import datetime, timedelta, timezone

from accounts import require_role
from core import (
    active,
    admin,
    audit,
    audited,
    json_text,
    notify,
    now,
    product_row,
    reason_required,
    transaction,
)

LABELS = {
    "waiting": "等待卖家确认",
    "confirmed": "卖家已确认",
    "delivered": "待买家确认完成",
    "cancel_requested": "取消协商中",
    "manual": "待管理员处理",
    "completed": "交易已完成",
    "cancelled": "已取消",
    "rejected": "卖家已拒绝",
    "expired": "已失效",
    "corrected": "已更正",
}


def reservation_row(connection, reservation_id):
    """Fetch a reservation and the current seller/status of its product."""
    row = connection.execute(
        "SELECT r.*,p.seller_id,p.status AS product_status,p.blocked "
        "FROM reservations r JOIN products p ON p.id=r.product_id WHERE r.id=?",
        (reservation_id,),
    ).fetchone()
    if row is None:
        raise ValueError("预约不存在。")
    return row


def participants(connection, reservation, event, text):
    """Send the same progress update to both transaction participants."""
    for account in (reservation["buyer_id"], reservation["seller_id"]):
        notify(connection, account, event, text, reservation["product_id"], reservation["id"])


def expire_waiting(connection, stamp=None):
    """Expire requests independently at the 48-hour boundary."""
    instant = stamp or datetime.now(timezone.utc)
    cutoff = (
        (instant - timedelta(hours=48)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )
    rows = connection.execute(
        "SELECT id FROM reservations WHERE status='waiting' AND created_at<=?", (cutoff,)
    ).fetchall()
    for row in rows:
        reservation = reservation_row(connection, row["id"])
        connection.execute("UPDATE reservations SET status='expired' WHERE id=?", (row["id"],))
        audit(
            connection, None, "reservation_timeout", "reservation", row["id"], "waiting", "expired"
        )
        participants(connection, reservation, "timeout", "预约超过 48 小时，已失效。")


def run_timeouts():
    """Run timeout work while the desktop application is open."""
    with transaction() as connection:
        expire_waiting(connection)
        cutoff = (
            (datetime.now(timezone.utc) - timedelta(days=7))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        rows = connection.execute(
            "SELECT id FROM reservations WHERE status='delivered' AND delivered_at<=? "
            "AND reminder_sent=0",
            (cutoff,),
        ).fetchall()
        for row in rows:
            reservation = reservation_row(connection, row["id"])
            connection.execute("UPDATE reservations SET reminder_sent=1 WHERE id=?", (row["id"],))
            participants(
                connection,
                reservation,
                "reminder",
                "交付登记已超过 7 天，请确认或联系管理员处理争议。",
            )
            for administrator in connection.execute(
                "SELECT ar.account_id FROM account_roles ar JOIN roles r ON r.id=ar.role_id "
                "JOIN accounts a ON a.id=ar.account_id WHERE r.name='admin' AND a.status='active'"
            ):
                notify(
                    connection,
                    administrator[0],
                    "dispute",
                    "交付超过 7 天仍未确认，请核实。",
                    reservation["product_id"],
                    reservation["id"],
                )
            audit(
                connection,
                None,
                "delivery_reminder",
                "reservation",
                row["id"],
                "delivered",
                "delivered",
            )


@audited("reserve")
def reserve(actor, product_id):
    """Create an immutable offer snapshot or return an existing live request."""
    with transaction() as connection:
        require_role(connection, actor, "buyer")
        expire_waiting(connection)
        product = product_row(connection, product_id)
        if product["seller_id"] == actor:
            raise ValueError("不能预约自己发布的商品。")
        existing = connection.execute(
            "SELECT id FROM reservations WHERE buyer_id=? AND product_id=? "
            "AND status IN ('waiting','confirmed','delivered','cancel_requested','manual')",
            (actor, product_id),
        ).fetchone()
        if existing:
            return existing["id"]
        active(connection, product["seller_id"])
        if product["status"] != "published" or product["blocked"]:
            raise ValueError("商品已不可预约，请刷新列表。")
        snapshot = dict(product)
        snapshot["images"] = [
            row[0]
            for row in connection.execute(
                "SELECT file_path FROM product_images WHERE product_id=? ORDER BY display_order",
                (product_id,),
            )
        ]
        reservation_id = connection.execute(
            "INSERT INTO reservations(product_id,buyer_id,status,snapshot,created_at) "
            "VALUES(?,?,'waiting',?,?)",
            (product_id, actor, json_text(snapshot), now()),
        ).lastrowid
        audit(connection, actor, "reserve", "reservation", reservation_id, "", "waiting")
        notify(
            connection,
            product["seller_id"],
            "reservation",
            "收到新的商品预约。",
            product_id,
            reservation_id,
        )
        return reservation_id


@audited("confirm_reservation")
def confirm_reservation(actor, reservation_id):
    """Confirm exactly one buyer and invalidate every other waiting request."""
    with transaction() as connection:
        require_role(connection, actor, "seller")
        expire_waiting(connection)
        row = reservation_row(connection, reservation_id)
        if row["seller_id"] != actor:
            raise ValueError("只能确认自己商品的预约。")
        active(connection, row["buyer_id"])
        if row["status"] != "waiting" or row["product_status"] != "published" or row["blocked"]:
            raise ValueError("预约或商品状态已变化，请刷新。")
        connection.execute(
            "UPDATE reservations SET status='confirmed',confirmed_at=? WHERE id=?",
            (now(), reservation_id),
        )
        connection.execute(
            "UPDATE products SET status='reserved',updated_at=? WHERE id=?",
            (now(), row["product_id"]),
        )
        others = connection.execute(
            "SELECT id FROM reservations WHERE product_id=? AND status='waiting'",
            (row["product_id"],),
        ).fetchall()
        for other in others:
            other_row = reservation_row(connection, other[0])
            connection.execute(
                "UPDATE reservations SET status='expired',reason='卖家已确认其他买家' WHERE id=?",
                (other[0],),
            )
            notify(
                connection,
                other_row["buyer_id"],
                "expired",
                "卖家已确认其他买家，本预约失效。",
                row["product_id"],
                other[0],
            )
        audit(
            connection,
            actor,
            "confirm_reservation",
            "reservation",
            reservation_id,
            "waiting",
            "confirmed",
        )
        participants(connection, row, "confirmed", "卖家已确认预约，可在预约详情查看交易电话。")


@audited("reject_reservation")
def reject_reservation(actor, reservation_id, reason):
    """Reject a waiting buyer request with a reason."""
    reason = reason_required(reason)
    with transaction() as connection:
        require_role(connection, actor, "seller")
        expire_waiting(connection)
        row = reservation_row(connection, reservation_id)
        if row["seller_id"] != actor or row["status"] != "waiting":
            raise ValueError("无权操作或预约不再等待确认。")
        connection.execute(
            "UPDATE reservations SET status='rejected',reason=? WHERE id=?",
            (reason, reservation_id),
        )
        audit(
            connection,
            actor,
            "reject_reservation",
            "reservation",
            reservation_id,
            "waiting",
            "rejected",
            reason,
        )
        participants(connection, row, "rejected", f"预约被拒绝：{reason}")


def finish_cancel(connection, row):
    """Restore visibility only if both accounts and the product remain eligible."""
    seller = connection.execute(
        "SELECT status FROM accounts WHERE id=?", (row["seller_id"],)
    ).fetchone()
    product = product_row(connection, row["product_id"])
    connection.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (row["id"],))
    if product["status"] == "reserved":
        status = (
            "published" if not product["blocked"] and seller["status"] == "active" else "violation"
        )
        connection.execute(
            "UPDATE products SET status=?,updated_at=? WHERE id=?",
            (status, now(), row["product_id"]),
        )


@audited("cancel_request")
def cancel_reservation(actor, reservation_id, reason):
    """Cancel waiting intent or request bilateral cancellation after confirmation."""
    reason = reason_required(reason)
    with transaction() as connection:
        active(connection, actor)
        expire_waiting(connection)
        row = reservation_row(connection, reservation_id)
        if actor not in (row["buyer_id"], row["seller_id"]):
            raise ValueError("只能取消自己参与的预约。")
        if row["status"] == "waiting" and actor == row["buyer_id"]:
            connection.execute(
                "UPDATE reservations SET status='cancelled',reason=? WHERE id=?",
                (reason, reservation_id),
            )
            status = "cancelled"
        elif row["status"] in ("confirmed", "delivered"):
            connection.execute(
                "UPDATE reservations SET status='cancel_requested',cancel_by=?,cancel_previous=?,reason=? WHERE id=?",
                (actor, row["status"], reason, reservation_id),
            )
            status = "cancel_requested"
        else:
            raise ValueError("当前状态不能发起取消。等待预约由卖家使用拒绝操作。")
        audit(
            connection,
            actor,
            "cancel_request",
            "reservation",
            reservation_id,
            row["status"],
            status,
            reason,
        )
        participants(connection, row, "cancel", f"取消进度：{LABELS[status]}。{reason}")


@audited("cancel_response")
def respond_cancel(actor, reservation_id, agree):
    """Only the other participant may approve or reject a cancellation request."""
    with transaction() as connection:
        active(connection, actor)
        row = reservation_row(connection, reservation_id)
        if actor not in (row["buyer_id"], row["seller_id"]) or actor == row["cancel_by"]:
            raise ValueError("应由交易另一方处理取消申请。")
        if row["status"] != "cancel_requested":
            raise ValueError("没有待处理的取消申请。")
        if agree:
            finish_cancel(connection, row)
        else:
            connection.execute(
                "UPDATE reservations SET status='manual' WHERE id=?", (reservation_id,)
            )
        audit(
            connection,
            actor,
            "cancel_response",
            "reservation",
            reservation_id,
            "cancel_requested",
            "cancelled" if agree else "manual",
        )
        participants(
            connection, row, "cancel", "取消已同意。" if agree else "取消存在争议，交管理员处理。"
        )


@audited("deliver")
def register_delivery(actor, reservation_id):
    """Record the seller's offline delivery without marking the product sold."""
    with transaction() as connection:
        require_role(connection, actor, "seller")
        row = reservation_row(connection, reservation_id)
        if (
            row["seller_id"] != actor
            or row["status"] != "confirmed"
            or row["product_status"] != "reserved"
        ):
            raise ValueError("仅卖家可为已确认预约登记交付。")
        connection.execute(
            "UPDATE reservations SET status='delivered',delivered_at=? WHERE id=?",
            (now(), reservation_id),
        )
        audit(connection, actor, "deliver", "reservation", reservation_id, "confirmed", "delivered")
        participants(connection, row, "delivered", "卖家已登记交付，等待买家确认。")


@audited("complete")
def complete_trade(actor, reservation_id):
    """Mark sold only after the buyer confirms the seller's delivery record."""
    with transaction() as connection:
        require_role(connection, actor, "buyer")
        row = reservation_row(connection, reservation_id)
        if row["buyer_id"] != actor:
            raise ValueError("只有该预约的买家可以确认完成。")
        if row["status"] == "completed":
            return
        active(connection, row["seller_id"])
        if row["status"] != "delivered" or row["product_status"] != "reserved" or row["blocked"]:
            raise ValueError("卖家尚未登记交付或交易已转人工处理。")
        stamp = now()
        connection.execute(
            "UPDATE reservations SET status='completed',completed_at=? WHERE id=?",
            (stamp, reservation_id),
        )
        connection.execute(
            "UPDATE products SET status='sold',sold_at=?,updated_at=? WHERE id=?",
            (stamp, stamp, row["product_id"]),
        )
        audit(
            connection, actor, "complete", "reservation", reservation_id, "delivered", "completed"
        )
        participants(connection, row, "completed", "买家已确认完成，交易已成交。")


def list_reservations(actor, scope="buyer"):
    """Return only the caller's side of transactions unless explicitly an admin."""
    with transaction() as connection:
        active(connection, actor)
        expire_waiting(connection)
        if scope == "admin":
            admin(connection, actor)
            where, args = "1=1", ()
        elif scope == "seller":
            where, args = "p.seller_id=?", (actor,)
        elif scope == "buyer":
            where, args = "r.buyer_id=?", (actor,)
        else:
            raise ValueError("查询范围无效。")
        return [
            dict(row)
            for row in connection.execute(
                "SELECT r.*,p.seller_id,p.status AS product_status,p.blocked,"
                "p.title AS current_title,a.username AS buyer_name "
                "FROM reservations r JOIN products p ON p.id=r.product_id "
                "JOIN accounts a ON a.id=r.buyer_id WHERE " + where + " ORDER BY r.id DESC",
                args,
            )
        ]


@audited("transaction_detail")
def transaction_detail(actor, reservation_id, admin_reason=""):
    """Return snapshots and reveal contact numbers only under explicit authorization."""
    with transaction() as connection:
        active(connection, actor)
        row = reservation_row(connection, reservation_id)
        participant = actor in (row["buyer_id"], row["seller_id"])
        if not participant:
            admin(connection, actor)
            admin_reason = reason_required(admin_reason)
        result = dict(row)
        result["snapshot"] = json.loads(row["snapshot"])
        identities = {
            item["id"]: item["username"]
            for item in connection.execute(
                "SELECT id,username FROM accounts WHERE id IN (?,?)",
                (row["buyer_id"], row["seller_id"]),
            )
        }
        result["buyer_name"] = identities[row["buyer_id"]]
        result["seller_name"] = identities[row["seller_id"]]
        result["contact"] = None
        if row["status"] in ("confirmed", "delivered", "cancel_requested") or not participant:
            if participant:
                other = row["seller_id"] if actor == row["buyer_id"] else row["buyer_id"]
                result["contact"] = connection.execute(
                    "SELECT phone FROM accounts WHERE id=?", (other,)
                ).fetchone()[0]
            else:
                result["contact"] = [
                    dict(item)
                    for item in connection.execute(
                        "SELECT id,phone FROM accounts WHERE id IN (?,?)",
                        (row["buyer_id"], row["seller_id"]),
                    )
                ]
            audit(
                connection,
                actor,
                "view_contact",
                "reservation",
                reservation_id,
                reason=admin_reason,
            )
        return result
