"""Deployment CLI: explicit administrator initialization and backup verification."""

import argparse
from getpass import getpass
from pathlib import Path

import database
from governance import bootstrap_admin
from operations import restore_backup, verify_backup


def main():
    """Run one explicit local maintenance action."""
    parser = argparse.ArgumentParser(description="二手交易系统部署工具")
    parser.add_argument("--data-dir", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-admin", help="创建首位管理员，密码交互输入")
    verify = commands.add_parser("verify-backup", help="在临时目录验证恢复")
    verify.add_argument("archive", type=Path)
    restore = commands.add_parser("restore-backup", help="恢复到新目录，禁止覆盖")
    restore.add_argument("archive", type=Path)
    restore.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.data_dir:
        database.DATABASE_PATH = args.data_dir.resolve() / "trading.db"
    database.initialize_database()
    if args.command == "init-admin":
        username = input("管理员登录名：").strip()
        phone = input("管理员手机号（教学环境可用演示号码）：").strip()
        password = getpass("密码：")
        if password != getpass("确认密码："):
            raise SystemExit("两次密码不一致，未创建账号。")
        try:
            print("管理员创建成功，账号编号：", bootstrap_admin(username, phone, password))
        except ValueError as error:
            raise SystemExit(str(error)) from error
    elif args.command == "restore-backup":
        print(restore_backup(args.archive, args.destination))
        print("可用 main.py --data-dir 指定恢复目录启动。")
    else:
        print(verify_backup(args.archive))


if __name__ == "__main__":
    main()
