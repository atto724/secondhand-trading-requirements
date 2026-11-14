"""Validation helpers for product images."""
import shutil
from uuid import uuid4

import database
import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
ALLOWED_FORMATS = {"JPEG", "PNG"}


def validate_image(file_path: str | Path) -> str:
    """Validate an image and return its actual format."""
    path = Path(file_path)

    try:
        if not path.is_file():
            raise ValueError("请选择存在的图片文件。")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("每张图片不能超过 10 MiB。")

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            with Image.open(path) as image:
                image_format = image.format
                if image_format not in ALLOWED_FORMATS:
                    raise ValueError("目前仅支持 JPEG 和 PNG 图片。")
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("图片不能超过 2000 万像素。")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("目前仅支持静态图片。")
                image.verify()

            with Image.open(path) as image:
                image.load()

    except (
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as error:
        raise ValueError("图片像素过大，无法处理。") from error
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ValueError("图片无法读取或文件已损坏。") from error

    return image_format

def copy_image(file_path: str | Path) -> str:
    """Copy a validated image into application storage."""
    image_format = validate_image(file_path)
    extension = {"JPEG": ".jpg", "PNG": ".png"}[image_format]

    data_directory = database.DATABASE_PATH.parent
    image_directory = data_directory / "images"
    image_directory.mkdir(parents=True, exist_ok=True)

    destination = image_directory / f"{uuid4().hex}{extension}"

    try:
        shutil.copyfile(file_path, destination)
        validate_image(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return destination.relative_to(data_directory).as_posix()
