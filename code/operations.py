"""Messages, statistics, audit export and portable backup operations."""

import csv
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import database
from core import active, admin, audit, now, transaction
from database import connect_database


def messages(actor):
    """Read only the caller's notifications."""
    with closing(connect_database()) as connection:
        active(connection, actor)
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM messages WHERE receiver_id=? ORDER BY id DESC", (actor,)
            )
        ]


def mark_read(actor, message_id):
    """Mark a caller-owned notification as read."""
    with transaction() as connection:
        active(connection, actor)
        cursor = connection.execute(
            "UPDATE messages SET is_read=1 WHERE id=? AND receiver_id=?", (message_id, actor)
        )
        if cursor.rowcount != 1:
            raise ValueError("消息不存在或无权操作。")


def date_range(start, end):
    """Interpret inclusive local dates as a half-open UTC interval."""
    local = timezone(timedelta(hours=8))
    try:
        lower = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=local)
        upper = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=local) + timedelta(days=1)
    except ValueError as error:
        raise ValueError("日期格式应为 YYYY-MM-DD。") from error
    if lower >= upper:
        raise ValueError("起始日期不能晚于结束日期。")
    return tuple(
        value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        for value in (lower, upper)
    )


def seller_statistics(actor, start, end):
    """Keep cohort conversion, period completions and current inventory distinct."""
    lower, upper = date_range(start, end)
    with closing(connect_database()) as connection:
        active(connection, actor)
        cohort = connection.execute(
            "SELECT COUNT(*) AS total,SUM(status='sold') AS sold FROM products "
            "WHERE seller_id=? AND first_published_at>=? AND first_published_at<?",
            (actor, lower, upper),
        ).fetchone()
        current = connection.execute(
            "SELECT COUNT(*) FROM products WHERE seller_id=? AND status='published' AND deleted=0",
            (actor,),
        ).fetchone()[0]
        sold = connection.execute(
            "SELECT COUNT(*) FROM products WHERE seller_id=? AND sold_at>=? AND sold_at<? AND status='sold'",
            (actor, lower, upper),
        ).fetchone()[0]
        categories = [
            dict(row)
            for row in connection.execute(
                "SELECT c.name,COUNT(*) AS total,SUM(p.status='sold') AS sold "
                "FROM products p LEFT JOIN categories c ON c.id=p.category_id "
                "WHERE p.seller_id=? AND p.first_published_at>=? AND p.first_published_at<? GROUP BY c.id",
                (actor, lower, upper),
            )
        ]
        return {
            "时区": "Asia/Shanghai（UTC+8）",
            "区间首次发布数": cohort["total"],
            "当前在售数（非区间指标）": current,
            "区间确认成交数": sold,
            "区间首次发布商品截至当前成交率": (
                f"{(cohort['sold'] or 0) / cohort['total']:.1%}"
                if cohort["total"]
                else "无可计算数据"
            ),
            "分类成交情况（首次发布样本）": categories,
        }


def platform_statistics(actor, start, end):
    """Count each metric using its own event timestamp and provide traceable IDs."""
    lower, upper = date_range(start, end)
    with transaction() as connection:
        admin(connection, actor)
        definitions = {
            "新增用户": ("accounts", "created_at", "1=1"),
            "首次发布": ("products", "first_published_at", "1=1"),
            "审核通过": ("reviews", "created_at", "approved=1"),
            "违规下架事件": ("audit_logs", "created_at", "action='violation' AND result='success'"),
            "预约创建": ("reservations", "created_at", "1=1"),
            "确认成交事件（包含后续更正）": (
                "audit_logs",
                "created_at",
                "action='complete' AND result='success'",
            ),
        }
        result = {"时区": "Asia/Shanghai（UTC+8）；区间包含结束日期"}
        for label, (table, stamp, predicate) in definitions.items():
            rows = connection.execute(
                f"SELECT id FROM {table} WHERE {stamp}>=? AND {stamp}<? AND {predicate}",
                (lower, upper),
            ).fetchall()
            result[label] = {"数量": len(rows), "明细编号": [row[0] for row in rows]}
        audit(connection, actor, "platform_statistics", "report", None, reason=f"{start} 至 {end}")
        return result


def query_audit(actor, keyword="", start="2000-01-01", end="2099-12-31"):
    """Search audit records with an audit trail for the query itself."""
    lower, upper = date_range(start, end)
    with transaction() as connection:
        admin(connection, actor)
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM audit_logs WHERE created_at>=? AND created_at<? AND "
                "(instr(action,?)>0 OR instr(object_type,?)>0 OR instr(reason,?)>0 "
                "OR CAST(actor_id AS TEXT)=? OR CAST(object_id AS TEXT)=?) ORDER BY id DESC LIMIT 2000",
                (lower, upper, keyword, keyword, keyword, keyword, keyword),
            )
        ]
        audit(
            connection,
            actor,
            "query_audit",
            "audit",
            None,
            reason=f"{start} 至 {end}；关键词={keyword}",
        )
        return rows


def export_audit(actor, destination, keyword="", start="2000-01-01", end="2099-12-31"):
    """Export CSV with formula injection protection and a separate export audit."""
    rows = query_audit(actor, keyword, start, end)
    fields = [
        "id",
        "actor_id",
        "action",
        "object_type",
        "object_id",
        "before_value",
        "after_value",
        "result",
        "reason",
        "created_at",
    ]
    with Path(destination).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        "'" + str(value) if str(value).startswith(("=", "+", "-", "@")) else value
                    )
                    for key, value in row.items()
                }
            )
    with transaction() as connection:
        admin(connection, actor)
        audit(connection, actor, "export_audit", "audit", None, reason=f"导出 {len(rows)} 条记录")


def create_backup(actor):
    """Back up a consistent SQLite snapshot plus its image directory."""
    with closing(connect_database()) as connection:
        admin(connection, actor)
    root = database.DATABASE_PATH.parent
    directory = root.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"backup_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}.zip"
    try:
        with TemporaryDirectory(dir=database.DATABASE_PATH.parent) as folder:
            snapshot = Path(folder) / "trading.db"
            # Hold a writer reservation while collecting DB and referenced file copies.
            with transaction() as lock:
                admin(lock, actor)
                with closing(connect_database()) as source:
                    with closing(sqlite3.connect(snapshot)) as target:
                        source.backup(target)
                with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(snapshot, "trading.db")
                    for image in (root / "images").glob("*"):
                        if image.is_file():
                            archive.write(image, f"images/{image.name}")
        with transaction() as connection:
            connection.execute(
                "INSERT INTO backup_runs(file_name,result,created_at) VALUES(?,'success',?)",
                (destination.name, now()),
            )
            audit(connection, actor, "backup", "backup", None, after=destination.name)
    except Exception:
        destination.unlink(missing_ok=True)
        with transaction() as connection:
            connection.execute(
                "INSERT INTO backup_runs(file_name,result,created_at) VALUES(?,'failure',?)",
                (destination.name, now()),
            )
        raise
    return destination


def backup_status(actor):
    """Read recent backup outcomes for the maintenance page."""
    with closing(connect_database()) as connection:
        admin(connection, actor)
        return [
            dict(row)
            for row in connection.execute("SELECT * FROM backup_runs ORDER BY id DESC LIMIT 30")
        ]


def verify_backup(archive_path):
    """Validate integrity in a temporary directory without overwriting live data."""
    with TemporaryDirectory(dir=database.DATABASE_PATH.parent) as folder:
        root = Path(folder)
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                target = (root / name).resolve()
                if not target.is_relative_to(root.resolve()):
                    raise ValueError("备份含非法路径。")
            archive.extractall(root)
        with closing(sqlite3.connect(root / "trading.db")) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("数据库完整性检查失败。")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("数据库关联检查失败。")
            paths = connection.execute("SELECT file_path FROM product_images").fetchall()
            for (relative,) in paths:
                path = (root / relative).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():
                    raise ValueError("备份缺少商品图片或图片路径无效。")
        return {"数据库完整性": "通过", "关联检查": "通过", "图片数量": len(paths)}


def restore_backup(archive_path, destination):
    """Restore into a new directory only, never overwrite a running database."""
    result = verify_backup(archive_path)
    target = Path(destination).resolve()
    if target.exists():
        raise ValueError("恢复目标必须是尚不存在的新目录，避免覆盖现有数据。")
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            path = (target / name).resolve()
            if not path.is_relative_to(target):
                raise ValueError("备份含非法路径。")
        archive.extractall(target)
    return result
