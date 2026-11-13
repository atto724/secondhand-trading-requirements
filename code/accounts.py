"""Account registration and authentication services."""

import sqlite3
from contextlib import closing

from database import connect_database
from security import hash_password, verify_password
def validate_registration(
    username: str,
    phone: str,
    password: str,
) -> tuple[str, str]:

    """Validate registration input and return normalized account fields."""
    username = username.strip()
    phone = phone.strip()

    if not 3 <= len(username) <= 30:
        raise ValueError("登录名长度必须为 3～30 个字符。")

    if (
        len(phone) != 11
        or not phone.isascii()
        or not phone.isdigit()
        or not phone.startswith("1")
    ):
        raise ValueError("手机号必须为以 1 开头的 11 位数字。")

    if not 8 <= len(password) <= 128:
        raise ValueError("密码长度必须为 8～128 个字符。")

    return username, phone

def create_account(username: str, phone: str, password: str) -> int:
    """Create an ordinary account with buyer and seller roles."""
    username, phone = validate_registration(username, phone, password)
    password_hash = hash_password(password)

    with closing(connect_database()) as connection:
        try:
            with connection:
                role_rows = connection.execute(
                    "SELECT id FROM roles WHERE name IN ('buyer', 'seller')"
                ).fetchall()
                if len(role_rows) != 2:
                    raise RuntimeError("默认角色缺失，请先初始化数据库。")

                cursor = connection.execute(
                    "INSERT INTO accounts (username, phone, password_hash) "
                    "VALUES (?, ?, ?)",
                    (username, phone, password_hash),
                )
                account_id = cursor.lastrowid

                connection.executemany(
                    "INSERT INTO account_roles (account_id, role_id) "
                    "VALUES (?, ?)",
                    [(account_id, row["id"]) for row in role_rows],
                )
        except sqlite3.IntegrityError as error:
            if "accounts.username" in str(error):
                raise ValueError("登录名已被使用。") from error
            if "accounts.phone" in str(error):
                raise ValueError("手机号已被使用。") from error
            raise

    return account_id

def authenticate(username: str, password: str) -> int:
    """Verify login credentials and return the active account ID."""
    username = username.strip()

    with closing(connect_database()) as connection:
        account = connection.execute(
            "SELECT id, password_hash, status FROM accounts "
            "WHERE username = ?",
            (username,),
        ).fetchone()

    if account is None:
        raise ValueError("登录名或密码错误。")

    if not verify_password(password, account["password_hash"]):
        raise ValueError("登录名或密码错误。")

    if account["status"] != "active":
        raise ValueError("账号已被禁用，请联系管理员。")

    return account["id"]
