"""Build a separate, repeatable demonstration database without touching real data."""

import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont

import database
from accounts import create_account
from catalog import review_product, save_product, submit_review
from governance import bootstrap_admin
from products import list_categories
from trades import reserve

DEMO_PASSWORD = "DemoPass123!"


def seed_demo(directory):
    """Create review accounts and sample products only in an empty demo database."""
    database.DATABASE_PATH = Path(directory).resolve() / "trading.db"
    database.initialize_database()

    with closing(database.connect_database()) as connection:
        if connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
            return
    administrator = bootstrap_admin("demo_admin", "13800000001", DEMO_PASSWORD)
    seller = create_account("demo_seller", "13800000002", DEMO_PASSWORD)
    buyer = create_account("demo_buyer", "13800000003", DEMO_PASSWORD)
    create_account("demo_other", "13800000004", DEMO_PASSWORD)

    categories = list_categories()
    definitions = [
        (
            "台灯",
            3500,
            "暖光台灯，适合书桌照明。灯光和开关正常，底座有轻微使用痕迹。",
            "#d9c9ac",
            "LAMP",
        ),
        ("数据结构教材", 2500, "C 语言版教材，内页有少量笔记，适合课程复习。", "#7294a2", "BOOK"),
        ("折叠椅", 6000, "折叠方便，椅面完好，适合宿舍使用。", "#bca78e", "CHAIR"),
        ("双肩背包", 4500, "容量充足，拉链顺畅，清洗后闲置。", "#8b9c86", "BAG"),
    ]
    with TemporaryDirectory() as folder:
        for index, (title, cents, description, color, label) in enumerate(definitions):
            source = Path(folder) / f"demo{index}.png"
            image = Image.new("RGB", (600, 600), color)
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                (140, 110, 460, 450), radius=35, fill="#fbf3e6", outline="#80634f", width=8
            )
            draw.text(
                (210, 270),
                label,
                fill="#ad4326",
                font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 42),
            )
            draw.text(
                (165, 500),
                "DEMO / PLACEHOLDER",
                fill="#3e2d23",
                font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22),
            )
            image.save(source)
            image.close()
            key = save_product(
                seller,
                title,
                description,
                categories[index % len(categories)]["id"],
                cents,
                [str(source)],
                condition="九成新",
                shipping="线下自提",
                negotiable=True,
            )
            submit_review(seller, key, 1)
            review_product(administrator, key, 1, True)
            if index == 0:
                reserve(buyer, key)
    save_product(
        seller, "待审核示例", "用于体验管理员审核通过或驳回流程。", categories[0]["id"], 8800
    )
    submit_review(seller, 5, 1)
    save_product(seller, "草稿示例", "仅卖家本人可见，可以编辑和删除。", categories[1]["id"], 1200)


def main():
    """Prepare demo storage and launch the regular application against it."""

    from main import main as launch  # pylint: disable=import-outside-toplevel

    directory = Path(__file__).resolve().parent / "data" / "demo"
    seed_demo(directory)
    sys.argv = [sys.argv[0], "--data-dir", str(directory)]
    launch()


if __name__ == "__main__":
    main()
