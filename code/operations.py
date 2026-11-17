"""Messages, statistics, audit export and portable backup operations."""

import csv
import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from uuid import uuid4

import database
from core import active, admin, audit, now, transaction
from database import connect_database
from images import validate_image


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


def mark_all_messages_read(actor):
    """Mark only this account's incoming notifications and private messages read."""
    with transaction() as connection:
        active(connection, actor)
        for table in ("messages", "direct_messages"):
            connection.execute(
                f"UPDATE {table} SET is_read=1 WHERE receiver_id=? AND is_read=0", (actor,)
            )


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


def audit_filter(keyword, start, end, upper_id):
    """Share parameterized filters between page queries and complete exports."""
    lower, upper = date_range(start, end)
    if not isinstance(keyword, str):
        raise ValueError("日志关键词必须为文本。")
    if upper_id is not None and (
        (not isinstance(upper_id, int) or isinstance(upper_id, bool)) or upper_id < 0
    ):
        raise ValueError("日志查询边界无效。")
    where = (
        "created_at>=? AND created_at<? AND id<=? AND "
        "(instr(action,?)>0 OR instr(object_type,?)>0 OR instr(reason,?)>0 "
        "OR CAST(actor_id AS TEXT)=? OR CAST(object_id AS TEXT)=?)"
    )
    return where, (lower, upper, upper_id, keyword, keyword, keyword, keyword, keyword)


def audit_page(
    actor, keyword="", start="2000-01-01", end="2099-12-31", page=1, page_size=100, upper_id=None
):
    """Page a fixed ID snapshot so new audit events do not shift older pages."""
    for value in (page, page_size):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("日志分页参数无效。")
    if page < 1 or not 1 <= page_size <= 2000:
        raise ValueError("日志分页参数无效。")
    audit_filter(keyword, start, end, upper_id)
    with transaction() as connection:
        admin(connection, actor)
        if upper_id is None:
            upper_id = connection.execute("SELECT COALESCE(MAX(id),0) FROM audit_logs").fetchone()[
                0
            ]
        where, args = audit_filter(keyword, start, end, upper_id)
        total = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE " + where, args
        ).fetchone()[0]
        page = min(page, max(1, (total + page_size - 1) // page_size))
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM audit_logs WHERE " + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                args + (page_size, (page - 1) * page_size),
            )
        ]
        audit(
            connection,
            actor,
            "query_audit",
            "audit",
            None,
            reason=f"{start} 至 {end}；关键词={keyword}；第{page}页；边界={upper_id}",
        )
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "upper_id": upper_id,
    }


def query_audit(actor, keyword="", start="2000-01-01", end="2099-12-31"):
    """Compatibility first-page query; the UI uses audit_page with visible totals."""
    return audit_page(actor, keyword, start, end, page_size=2000)["rows"]


def export_audit(
    actor, destination, keyword="", start="2000-01-01", end="2099-12-31", upper_id=None
):
    """Stream every matching snapshot row, then publish a completed CSV atomically."""
    audit_filter(keyword, start, end, upper_id)
    destination = Path(destination)
    temporary = None
    count = 0
    try:
        with closing(connect_database()) as connection:
            connection.execute("BEGIN")
            admin(connection, actor)
            if upper_id is None:
                upper_id = connection.execute(
                    "SELECT COALESCE(MAX(id),0) FROM audit_logs"
                ).fetchone()[0]
            where, args = audit_filter(keyword, start, end, upper_id)
            cursor = connection.execute(
                "SELECT * FROM audit_logs WHERE " + where + " ORDER BY id DESC", args
            )
            fields = [item[0] for item in cursor.description]
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8-sig",
                newline="",
                dir=destination.parent,
                prefix="audit_",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                while batch := cursor.fetchmany(500):
                    for row in batch:
                        writer.writerow(
                            {
                                key: (
                                    "'" + str(value)
                                    if str(value).lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                                    else value
                                )
                                for key, value in dict(row).items()
                            }
                        )
                        count += 1
        with transaction() as connection:
            admin(connection, actor)
            audit(
                connection,
                actor,
                "export_audit",
                "audit",
                None,
                reason=f"导出 {count} 条记录；{start} 至 {end}；关键词={keyword}；边界={upper_id}",
            )
            temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return count


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
                with closing(sqlite3.connect(snapshot)) as validation:
                    check_backup_images(validation, root)
                with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(snapshot, "trading.db")
                    for image in (root / "images").rglob("*"):
                        if image.is_file() and image.resolve().is_relative_to(root.resolve()):
                            archive.write(image, image.relative_to(root).as_posix())
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


def snapshot_image_paths(serialized, label):
    """Read only attachment fields from immutable historical JSON."""
    try:
        data = json.loads(serialized)
        if not isinstance(data, dict):
            raise ValueError("快照必须为对象。")
        images = data.get("images", [])
        if not isinstance(images, list):
            raise ValueError("图片列表格式无效。")
        paths = [item.get("file_path") if isinstance(item, dict) else item for item in images]
        if data.get("image") is not None:
            paths.append(data["image"])
        if any(not isinstance(item, str) or not item.strip() for item in paths):
            raise ValueError("图片引用格式无效。")
        return paths
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} 的历史图片信息无效。") from error


def backup_image_references(connection):
    """Collect current products, custom avatars and all supported historical references."""
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    required = {
        "accounts",
        "products",
        "product_images",
        "reservations",
        "product_history",
        "audit_logs",
    }
    if required - tables:
        raise ValueError("备份缺少必要数据表：" + "、".join(sorted(required - tables)))
    groups = {
        name: set()
        for name in ("商品图片", "用户头像", "预约快照图片", "商品历史图片", "商品消息图片")
    }
    groups["商品图片"].update(
        row[0] for row in connection.execute("SELECT file_path FROM product_images")
    )
    if "public_profiles" in tables:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(public_profiles)")}
        if "avatar_path" in columns:
            groups["用户头像"].update(
                row[0]
                for row in connection.execute(
                    "SELECT avatar_path FROM public_profiles WHERE avatar_path<>''"
                )
            )
    for table, column, group in (
        ("reservations", "snapshot", "预约快照图片"),
        ("product_history", "content", "商品历史图片"),
        ("direct_messages", "product_snapshot", "商品消息图片"),
    ):
        if table not in tables:
            continue
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            continue
        for key, value in connection.execute(
            f"SELECT id,{column} FROM {table} WHERE {column} IS NOT NULL"
        ):
            groups[group].update(snapshot_image_paths(value, f"{group} #{key}"))
    return groups


def check_backup_images(connection, root):
    """Reject missing, escaping or unreadable referenced images, with useful filenames."""
    groups = backup_image_references(connection)
    references = {}
    for group, paths in groups.items():
        for relative in paths:
            if not isinstance(relative, str) or not relative.strip():
                raise ValueError(f"{group}存在空白或无效的图片路径。")
            references.setdefault(relative, []).append(group)
    errors = []
    root = root.resolve()
    for relative, sources in references.items():
        path = root / relative
        if Path(relative).anchor or not path.resolve().is_relative_to(root):
            problem = "图片路径越界或不是相对路径"
        elif not path.is_file():
            problem = "文件缺失"
        else:
            try:
                validate_image(path)
                continue
            except ValueError:
                problem = "文件损坏或不是受支持的图片"
        errors.append(f"{relative}（{'、'.join(sources)}）：{problem}")
    if errors:
        raise ValueError(f"备份图片检查失败，共{len(errors)}项：\n" + "\n".join(errors))
    return {
        "图片数量": len(references),
        "图片分类数量": {name: len(paths) for name, paths in groups.items()},
    }


def verify_backup(archive_path):
    """Validate database and every referenced image without overwriting live data."""
    with TemporaryDirectory(dir=database.DATABASE_PATH.parent) as folder:
        root = Path(folder)
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                target = (root / name).resolve()
                if not target.is_relative_to(root.resolve()):
                    raise ValueError("备份含非法路径。")
            archive.extractall(root)
        if not (root / "trading.db").is_file():
            raise ValueError("备份缺少 trading.db 数据库。")
        with closing(sqlite3.connect(root / "trading.db")) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("数据库完整性检查失败。")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("数据库关联检查失败。")
            result = check_backup_images(connection, root)
        return {
            "数据库完整性": "通过",
            "关联检查": "通过",
            "图片检查": "全部引用存在且可读取",
            "计数说明": "图片数量按文件去重；不同分类可能引用同一文件。",
            **result,
        }


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
