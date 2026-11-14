"""Administrator authorization, moderation and correction services."""

from contextlib import closing

from accounts import create_account
from core import (
    active,
    admin,
    audit,
    audited,
    has_live_reservations,
    json_text,
    notify,
    now,
    product_row,
    reason_required,
    transaction,
)
from database import connect_database
from trades import finish_cancel, participants, reservation_row


def account_profile(actor):
    """Return the current account's nonsecret identity and roles."""
    with closing(connect_database()) as connection:
        row = active(connection, actor)
        roles = [
            item[0]
            for item in connection.execute(
                "SELECT r.name FROM roles r JOIN account_roles ar ON ar.role_id=r.id WHERE ar.account_id=?",
                (actor,),
            )
        ]
        return {"id": actor, "username": row["username"], "roles": roles}


def bootstrap_admin(username, phone, password):
    """Create the first administrator through an explicit local deployment command."""
    # Account creation is ordinary registration; promotion is guarded by a writer transaction.
    with transaction() as connection:
        if connection.execute(
            "SELECT 1 FROM account_roles ar JOIN roles r ON r.id=ar.role_id WHERE r.name='admin'"
        ).fetchone():
            raise ValueError("已有管理员，后续授权必须由管理员完成。")
    account_id = create_account(username, phone, password)
    with transaction() as connection:
        if connection.execute(
            "SELECT 1 FROM account_roles ar JOIN roles r ON r.id=ar.role_id WHERE r.name='admin'"
        ).fetchone():
            raise ValueError("管理员已由其他初始化操作创建；本次账号保留为普通用户。")
        connection.execute(
            "INSERT INTO account_roles(account_id,role_id) SELECT ?,id FROM roles WHERE name='admin'",
            (account_id,),
        )
        audit(
            connection,
            account_id,
            "bootstrap_admin",
            "account",
            account_id,
            "ordinary",
            "admin",
            "本机部署人员显式初始化",
        )
    return account_id


@audited("grant_admin")
def set_admin(actor, target, enabled, reason):
    """Grant/revoke administrator access without losing the last active administrator."""
    reason = reason_required(reason)
    with transaction() as connection:
        admin(connection, actor)
        active(connection, target)
        if enabled:
            connection.execute(
                "INSERT OR IGNORE INTO account_roles(account_id,role_id) "
                "SELECT ?,id FROM roles WHERE name='admin'",
                (target,),
            )
        else:
            count = connection.execute(
                "SELECT COUNT(*) FROM account_roles ar JOIN roles r ON r.id=ar.role_id "
                "JOIN accounts a ON a.id=ar.account_id WHERE r.name='admin' AND a.status='active'"
            ).fetchone()[0]
            has_role = connection.execute(
                "SELECT 1 FROM account_roles ar JOIN roles r ON r.id=ar.role_id "
                "WHERE ar.account_id=? AND r.name='admin'",
                (target,),
            ).fetchone()
            if has_role and count <= 1:
                raise ValueError("不能撤销最后一位有效管理员。")
            connection.execute(
                "DELETE FROM account_roles WHERE account_id=? AND role_id=(SELECT id FROM roles WHERE name='admin')",
                (target,),
            )
        audit(
            connection,
            actor,
            "grant_admin" if enabled else "revoke_admin",
            "account",
            target,
            reason=reason,
        )


def moderate_product(connection, actor, product_id, reason):
    """Hide a product and route confirmed transactions to manual handling."""
    product = product_row(connection, product_id)
    connection.execute(
        "UPDATE products SET blocked=1,status=CASE WHEN status='sold' THEN status ELSE 'violation' END,"
        "updated_at=? WHERE id=?",
        (now(), product_id),
    )
    rows = connection.execute(
        "SELECT id FROM reservations WHERE product_id=? AND status IN "
        "('waiting','confirmed','delivered','cancel_requested','manual')",
        (product_id,),
    ).fetchall()
    for item in rows:
        row = reservation_row(connection, item[0])
        status = "expired" if row["status"] == "waiting" else "manual"
        connection.execute(
            "UPDATE reservations SET status=?,reason=? WHERE id=?", (status, reason, row["id"])
        )
        participants(
            connection, row, "moderation", f"商品受到治理处理：{reason}；预约状态：{status}"
        )
    notify(connection, product["seller_id"], "moderation", f"商品被限制：{reason}", product_id)
    audit(connection, actor, "violation", "product", product_id, product, "blocked", reason)


@audited("violation")
def block_product(actor, product_id, reason):
    """Apply a reasoned product moderation action."""
    reason = reason_required(reason)
    with transaction() as connection:
        admin(connection, actor)
        moderate_product(connection, actor, product_id, reason)


@audited("release_product")
def release_product(actor, product_id, reason):
    """Remove the block while keeping the product nonpublic pending a fresh review."""
    reason = reason_required(reason)
    with transaction() as connection:
        admin(connection, actor)
        row = product_row(connection, product_id)
        if not row["blocked"]:
            raise ValueError("商品没有违规限制。")

        if has_live_reservations(connection, product_id):
            raise ValueError("请先处理该商品的有效预约或交易争议。")
        new_status = "sold" if row["status"] == "sold" else "draft"
        connection.execute(
            "UPDATE products SET blocked=0,status=?,updated_at=? WHERE id=?",
            (new_status, now(), product_id),
        )
        audit(connection, actor, "release_product", "product", product_id, row, new_status, reason)
        notify(
            connection,
            row["seller_id"],
            "release",
            "违规限制已解除，非成交商品需完善后重新审核。",
            product_id,
        )


@audited("account_status")
def set_account_enabled(actor, target, enabled, reason):
    """Disable accounts and route their affected transactions to manual resolution."""
    reason = reason_required(reason)
    with transaction() as connection:
        admin(connection, actor)
        target_row = connection.execute("SELECT * FROM accounts WHERE id=?", (target,)).fetchone()
        if target_row is None:
            raise ValueError("账号不存在。")
        if target == actor and not enabled:
            raise ValueError("不能禁用当前正在操作的管理员账号。")
        status = "active" if enabled else "disabled"
        if not enabled:
            # Never leave the deployment without an active administrator.
            target_admin = connection.execute(
                "SELECT 1 FROM account_roles ar JOIN roles r ON r.id=ar.role_id "
                "WHERE ar.account_id=? AND r.name='admin'",
                (target,),
            ).fetchone()
            other_admin = connection.execute(
                "SELECT 1 FROM account_roles ar JOIN roles r ON r.id=ar.role_id "
                "JOIN accounts a ON a.id=ar.account_id WHERE r.name='admin' AND a.status='active' "
                "AND a.id<>?",
                (target,),
            ).fetchone()
            if target_admin and not other_admin:
                raise ValueError("不能禁用最后一位有效管理员。")
        connection.execute("UPDATE accounts SET status=? WHERE id=?", (status, target))
        if not enabled:
            for product in connection.execute(
                "SELECT id FROM products WHERE seller_id=? AND deleted=0", (target,)
            ).fetchall():
                moderate_product(connection, actor, product[0], reason)
            for item in connection.execute(
                "SELECT id FROM reservations WHERE buyer_id=? AND status IN "
                "('waiting','confirmed','delivered','cancel_requested')",
                (target,),
            ).fetchall():
                row = reservation_row(connection, item[0])
                new = "expired" if row["status"] == "waiting" else "manual"
                connection.execute(
                    "UPDATE reservations SET status=?,reason=? WHERE id=?", (new, reason, row["id"])
                )
                participants(
                    connection,
                    row,
                    "account_disabled",
                    "参与方账号已禁用，请查看交易状态或联系管理员。",
                )
        audit(
            connection,
            actor,
            "account_status",
            "account",
            target,
            target_row["status"],
            status,
            reason,
        )
        # Re-enabling accounts never restores product visibility or old reservations.


@audited("resolve_dispute")
def resolve_dispute(actor, reservation_id, cancel, reason):
    """Resolve a manual/overdue transaction without declaring a sale for the buyer."""
    reason = reason_required(reason)
    with transaction() as connection:
        admin(connection, actor)
        row = reservation_row(connection, reservation_id)
        if row["status"] not in ("manual", "cancel_requested", "delivered"):
            raise ValueError("该预约当前不属于可处理争议。")
        if cancel:
            finish_cancel(connection, row)
        else:
            active(connection, row["buyer_id"])
            active(connection, row["seller_id"])
            if row["blocked"] or row["product_status"] != "reserved":
                raise ValueError("商品仍受限制，只能先核实取消或解除治理。")
            new_status = "delivered" if row["delivered_at"] else "confirmed"
            connection.execute(
                "UPDATE reservations SET status=?,cancel_by=NULL,cancel_previous=NULL,reason=? WHERE id=?",
                (new_status, reason, reservation_id),
            )
        audit(
            connection,
            actor,
            "resolve_dispute",
            "reservation",
            reservation_id,
            row["status"],
            "cancelled" if cancel else "continue",
            reason,
        )
        participants(connection, row, "dispute", f"管理员已核实处理：{reason}")


@audited("correct_sale")
def correct_sale(actor, reservation_id, reason):
    """Append a correction chain and move a falsely completed sale to review."""
    reason = reason_required(reason)
    with transaction() as connection:
        admin(connection, actor)
        row = reservation_row(connection, reservation_id)
        if row["status"] != "completed" or row["product_status"] != "sold":
            raise ValueError("只能更正已完成的成交记录。")
        connection.execute(
            "INSERT INTO corrections(reservation_id,admin_id,before_value,after_value,reason,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (reservation_id, actor, json_text(row), "pending_review", reason, now()),
        )
        connection.execute(
            "UPDATE reservations SET status='corrected' WHERE id=?", (reservation_id,)
        )
        connection.execute(
            "UPDATE products SET status='pending_review',sold_at=NULL,updated_at=? WHERE id=?",
            (now(), row["product_id"]),
        )
        audit(
            connection,
            actor,
            "correct_sale",
            "reservation",
            reservation_id,
            row,
            "corrected",
            reason,
        )
        participants(connection, row, "correction", f"成交记录已更正，保留原始记录：{reason}")


def list_accounts(actor):
    """List account metadata without leaking passwords or unnecessary phone numbers."""
    with closing(connect_database()) as connection:
        admin(connection, actor)
        return [
            dict(row)
            for row in connection.execute(
                "SELECT a.id,a.username,a.status,a.created_at,"
                "(SELECT group_concat(r.name,',') FROM account_roles ar JOIN roles r ON r.id=ar.role_id "
                "WHERE ar.account_id=a.id) AS roles FROM accounts a ORDER BY a.id"
            )
        ]
