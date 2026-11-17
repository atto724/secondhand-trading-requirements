"""Public seller profiles and participant-scoped offline private conversations."""

from contextlib import closing

import database
from images import copy_image

from core import active, audit, now, transaction, product_row, json_text
from database import connect_database


def seller_profile(actor, seller_id):
    """Expose an explicit public allowlist, never phone, passwords or raw IPs."""
    with closing(connect_database()) as connection:
        active(connection, actor)
        seller = active(connection, seller_id)
        profile = connection.execute(
            "SELECT nickname,bio,region,avatar_path FROM public_profiles WHERE account_id=?",
            (seller_id,),
        ).fetchone()
        stats = connection.execute(
            "SELECT COUNT(*) AS published,COALESCE(SUM(status='sold'),0) AS sold "
            "FROM products WHERE seller_id=? AND first_published_at IS NOT NULL",
            (seller_id,),
        ).fetchone()
        selling = connection.execute(
            "SELECT COUNT(*) FROM products WHERE seller_id=? AND status='published' AND blocked=0 AND deleted=0",
            (seller_id,),
        ).fetchone()[0]
        return {
            "id": seller_id,
            "username": seller["username"],
            "joined_at": seller["created_at"],
            "nickname": profile["nickname"] if profile else "",
            "bio": profile["bio"] if profile else "",
            "region": profile["region"] if profile else "",
            "avatar_path": profile["avatar_path"] if profile else "",
            "published": stats["published"],
            "sold": stats["sold"],
            "selling": selling,
            "conversion": stats["sold"] / stats["published"] if stats["published"] else None,
        }


def update_profile(actor, nickname, bio, region):
    """Only edit the caller's voluntary public profile."""
    fields = ((nickname, 30, "昵称"), (bio, 300, "个人简介"), (region, 30, "所在地"))
    for value, limit, label in fields:
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError(f"{label}最多{limit}个字符。")
    with transaction() as connection:
        active(connection, actor)
        connection.execute(
            "INSERT INTO public_profiles(account_id,nickname,bio,region,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(account_id) DO UPDATE SET nickname=excluded.nickname,bio=excluded.bio,"
            "region=excluded.region,updated_at=excluded.updated_at",
            (actor, nickname.strip(), bio.strip(), region.strip(), now()),
        )
        audit(connection, actor, "update_profile", "account", actor)


def update_avatar(actor, file_path):
    """Validate and copy an owner-only avatar, compensating failed DB writes."""
    relative = None
    try:
        with transaction() as connection:
            active(connection, actor)
            relative = copy_image(file_path)
            connection.execute(
                "INSERT INTO public_profiles(account_id,avatar_path,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(account_id) DO UPDATE SET avatar_path=excluded.avatar_path,updated_at=excluded.updated_at",
                (actor, relative, now()),
            )
            audit(connection, actor, "update_avatar", "account", actor)
    except Exception:
        if relative:
            (database.DATABASE_PATH.parent / relative).unlink(missing_ok=True)
        raise
    return relative


def send_direct_message(actor, receiver, content):
    """Recheck both accounts and atomically persist a plain-text message."""
    if actor == receiver:
        raise ValueError("不能给自己发送私信。")
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 1000:
        raise ValueError("私信内容须为1～1000个字符，不能只输入空白。")
    with transaction() as connection:
        active(connection, actor)
        active(connection, receiver)
        cursor = connection.execute(
            "INSERT INTO direct_messages(sender_id,receiver_id,content,created_at) VALUES(?,?,?,?)",
            (actor, receiver, content.strip(), now()),
        )
        # Keep message bodies out of the administrator's ordinary audit feed.
        audit(connection, actor, "send_private_message", "direct_message", cursor.lastrowid)
        return cursor.lastrowid


def conversation(actor, peer, before=None):
    """Read one caller/peer pair; older pages use a stable ID cursor."""
    if actor == peer:
        raise ValueError("不能打开与自己的私信会话。")
    if before is not None and (
        not isinstance(before, int) or isinstance(before, bool) or before < 1
    ):
        raise ValueError("私信分页参数无效。")
    with transaction() as connection:
        active(connection, actor)
        target = connection.execute(
            "SELECT a.username,a.status,COALESCE(p.nickname,'') AS nickname FROM accounts a "
            "LEFT JOIN public_profiles p ON p.account_id=a.id WHERE a.id=?",
            (peer,),
        ).fetchone()
        if not target:
            raise ValueError("对方账号不存在。")
        rows = connection.execute(
            "SELECT * FROM direct_messages WHERE ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)) "
            "AND id<? ORDER BY id DESC LIMIT 100",
            (actor, peer, peer, actor, before or 9223372036854775807),
        ).fetchall()
        ids = [row["id"] for row in rows if row["receiver_id"] == actor]
        if ids:
            marks = ",".join("?" for _ in ids)
            connection.execute(
                f"UPDATE direct_messages SET is_read=1 WHERE receiver_id=? AND id IN ({marks})",
                [actor] + ids,
            )
        return {
            "peer_name": target["username"],
            "peer_display_name": target["nickname"] or target["username"],
            "avatars": {
                row["account_id"]: row["avatar_path"]
                for row in connection.execute(
                    "SELECT account_id,avatar_path FROM public_profiles WHERE account_id IN (?,?)",
                    (actor, peer),
                )
            },
            "can_send": target["status"] == "active",
            "rows": [dict(row) for row in reversed(rows)],
        }


def latest_read_message(actor, peer):
    """Return an ID only when the latest outgoing message was marked read."""
    with closing(connect_database()) as connection:
        active(connection, actor)
        row = connection.execute(
            "SELECT id,is_read FROM direct_messages WHERE sender_id=? AND receiver_id=? ORDER BY id DESC LIMIT 1",
            (actor, peer),
        ).fetchone()
        return row["id"] if row and row["is_read"] else None


def inbox(actor):
    """List caller-owned conversations and incoming unread counts only."""
    with closing(connect_database()) as connection:
        active(connection, actor)
        return [
            dict(row)
            for row in connection.execute(
                "WITH mine AS (SELECT *,CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END AS peer_id "
                "FROM direct_messages WHERE sender_id=? OR receiver_id=?) "
                "SELECT m.peer_id,a.username,m.content,m.created_at,COALESCE(p.nickname,'') AS nickname,"
                "COALESCE(p.avatar_path,'') AS avatar_path,"
                "(SELECT COUNT(*) FROM direct_messages u WHERE u.receiver_id=? "
                "AND u.sender_id=m.peer_id AND u.is_read=0) AS unread "
                "FROM mine m JOIN accounts a ON a.id=m.peer_id "
                "LEFT JOIN public_profiles p ON p.account_id=m.peer_id WHERE m.id IN "
                "(SELECT MAX(id) FROM mine GROUP BY peer_id) ORDER BY m.id DESC",
                (actor, actor, actor, actor),
            )
        ]


def send_product_message(actor, receiver, product_id):
    """Send a public seller-owned product snapshot only after an explicit action."""
    if actor == receiver:
        raise ValueError("不能给自己发送商品消息。")
    with transaction() as connection:
        active(connection, actor)
        active(connection, receiver)
        product = product_row(connection, product_id)
        if product["seller_id"] != receiver:
            raise ValueError("该商品不属于当前咨询的卖家。")
        if product["status"] != "published" or product["blocked"]:
            raise ValueError("商品当前不可咨询，请刷新商品详情。")
        image = connection.execute(
            "SELECT file_path FROM product_images WHERE product_id=? ORDER BY display_order LIMIT 1",
            (product_id,),
        ).fetchone()
        snapshot = {
            "id": product_id,
            "title": product["title"],
            "price_cents": product["price_cents"],
            "image": image[0] if image else None,
        }
        cursor = connection.execute(
            "INSERT INTO direct_messages(sender_id,receiver_id,content,created_at,product_snapshot) VALUES(?,?,?,?,?)",
            (actor, receiver, "[商品] " + product["title"], now(), json_text(snapshot)),
        )
        audit(connection, actor, "send_product_message", "direct_message", cursor.lastrowid)
        return cursor.lastrowid
