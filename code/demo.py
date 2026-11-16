"""Seed an offline, versioned product gallery from user-provided photographs."""

import sys
from contextlib import closing
from pathlib import Path

import database
import demo_assets
from accounts import create_account
from catalog import review_product, save_product, submit_review
from governance import bootstrap_admin
from products import list_categories

DEMO_PASSWORD = "DemoPass123!"
SAMPLE_PRODUCTS = (
    (
        "backpack",
        "深蓝色通勤双肩包",
        "服饰鞋包",
        15000,
        "深蓝色双肩背包，棕色提手，适合日常通勤搭配。",
    ),
    ("chair", "黑色折叠椅", "家居生活", 6000, "黑色靠背折叠椅，适合书桌或小空间摆放。"),
    (
        "textbook",
        "数据结构 C 语言版教材",
        "图书文教",
        2500,
        "数据结构课程教材，可用于演示图书筛选和预约流程。",
    ),
    ("desk_lamp", "白色桌面台灯", "数码电器", 3500, "白色长臂桌面台灯，适合书桌照明场景展示。"),
    ("shoes", "灰色运动休闲鞋", "运动户外", 12000, "灰色网面运动休闲鞋，图片展示鞋面和鞋底细节。"),
    ("jacket", "浅灰色休闲夹克", "服饰鞋包", 9000, "浅灰色拉链夹克，适合日常穿搭。"),
    (
        "laptop",
        "16 英寸游戏笔记本",
        "数码电器",
        420000,
        "黑色游戏笔记本电脑，具体配置和使用状况以交易前核实为准。",
    ),
    (
        "bear_light",
        "小熊造型便携灯",
        "数码电器",
        1800,
        "带挂绳的小熊造型便携灯，可用于床边或帐篷照明场景展示。",
    ),
    ("handbag", "黑色链条手提包", "服饰鞋包", 8500, "黑色菱格纹手提包，配银色链条。"),
    (
        "foundation",
        "粉底液展示样品",
        "其他闲置",
        6000,
        "美妆展示样品归入其他闲置；容量、有效期和实际状态须另行核实。",
    ),
    (
        "stroller",
        "米色婴儿推车",
        "母婴用品",
        32000,
        "米色带遮阳篷的婴儿推车，用于母婴用品分类展示。",
    ),
    (
        "badminton",
        "羽毛球拍套装",
        "运动户外",
        8000,
        "羽毛球拍套装图片，具体配件以双方确认的清单为准。",
    ),
    ("pet_carrier", "两用宠物窝", "宠物用品", 6500, "箱式宠物窝，用于宠物出行和家居用品场景展示。"),
    (
        "scooter",
        "白色电动两轮车",
        "交通出行",
        160000,
        "白色电动两轮车，电池、手续和车况以线下核实为准。",
    ),
    (
        "board_game",
        "三国主题桌游卡牌",
        "兴趣娱乐",
        2500,
        "多人桌游卡牌套装，具体卡牌数量以双方清点为准。",
    ),
)
DEMO_NOTICE = (
    "\n\n【教学演示】图片由用户提供，价格、成色及描述为样例设定，不代表真实报价或品质鉴定。"
)


def demo_accounts():
    """Create missing fixture accounts without resetting existing passwords or roles."""
    with closing(database.connect_database()) as connection:
        accounts = {
            row["username"]: row["id"]
            for row in connection.execute("SELECT id,username FROM accounts")
        }
    for index, name in enumerate(("demo_admin", "demo_seller", "demo_buyer", "demo_other"), 1):
        if name not in accounts:
            create = bootstrap_admin if name == "demo_admin" else create_account
            accounts[name] = create(name, f"1380000000{index}", DEMO_PASSWORD)
    return accounts


def seed_product(
    accounts, categories, key, title, category, cents, description, image, status="published"
):
    """Seed a stable sample once; never recreate items a reviewer edited or deleted."""
    with closing(database.connect_database()) as connection:
        existing = connection.execute(
            "SELECT product_id FROM demo_items WHERE sample_key=?", (key,)
        ).fetchone()
        if existing:
            return existing[0]
        # Recover a previous interrupted seed between product creation and registry insertion.
        previous = connection.execute(
            "SELECT id FROM products WHERE seller_id=? AND title=? AND description=? ORDER BY id LIMIT 1",
            (accounts["demo_seller"], title, description + DEMO_NOTICE),
        ).fetchone()
    product_id = (
        previous[0]
        if previous
        else save_product(
            accounts["demo_seller"],
            title,
            description + DEMO_NOTICE,
            categories[category],
            cents,
            [str(image)],
            condition="未注明",
            shipping="线下自提",
            negotiable=True,
        )
    )
    with closing(database.connect_database()) as connection:
        state = connection.execute(
            "SELECT status,version FROM products WHERE id=?", (product_id,)
        ).fetchone()
    if status in ("published", "pending_review") and state["status"] == "draft":
        submit_review(accounts["demo_seller"], product_id, state["version"])
    if status == "published":
        with closing(database.connect_database()) as connection:
            state = connection.execute(
                "SELECT status,version FROM products WHERE id=?", (product_id,)
            ).fetchone()
        if state["status"] == "pending_review":
            review_product(accounts["demo_admin"], product_id, state["version"], True)
    with closing(database.connect_database()) as connection:
        with connection:
            connection.execute(
                "INSERT INTO demo_items(sample_key,product_id) VALUES(?,?)", (key, product_id)
            )
    return product_id


def seed_demo(directory):
    """Populate a separate gallery database idempotently using original supplied images."""
    database.DATABASE_PATH = Path(directory).resolve() / "trading.db"
    database.initialize_database()
    with closing(database.connect_database()) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS demo_items (sample_key TEXT PRIMARY KEY, "
            "product_id INTEGER NOT NULL UNIQUE REFERENCES products(id))"
        )
        connection.commit()
    accounts = demo_accounts()
    categories = {row["name"]: row["id"] for row in list_categories()}
    assets = Path(demo_assets.__file__).parent
    for key, title, category, cents, description in SAMPLE_PRODUCTS:
        image = assets / f"{key}.jpg"
        if not image.is_file():
            raise ValueError(f"演示图片缺失：{image.name}，请检查完整安装包。")
        seed_product(accounts, categories, key, title, category, cents, description, image)
    seed_product(
        accounts,
        categories,
        "pending_example",
        "待审核示例 · 桌面台灯",
        "数码电器",
        3800,
        "用于体验管理员审核通过或驳回流程。",
        assets / "desk_lamp.jpg",
        "pending_review",
    )
    seed_product(
        accounts,
        categories,
        "draft_example",
        "草稿示例 · 课程教材",
        "图书文教",
        2000,
        "仅本人可见，可以编辑图片、补充信息或删除。",
        assets / "textbook.jpg",
        "draft",
    )


def main():
    """Open the new photo gallery while preserving the previous demo database."""
    from main import main as launch  # pylint: disable=import-outside-toplevel

    directory = Path(__file__).resolve().parent / "data" / "demo_gallery"
    seed_demo(directory)
    sys.argv = [sys.argv[0], "--data-dir", str(directory)]
    launch()


if __name__ == "__main__":
    main()
