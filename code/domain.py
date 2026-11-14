"""Domain states used by the trading system."""

from enum import Enum


class ProductStatus(str, Enum):
    """Valid product states from the UML state diagram."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    RESERVED = "reserved"
    SOLD = "sold"
    DELISTED = "delisted"
    VIOLATION = "violation"


PRODUCT_STATUS_LABELS = {
    ProductStatus.DRAFT: "草稿",
    ProductStatus.PENDING_REVIEW: "待审核",
    ProductStatus.PUBLISHED: "已发布",
    ProductStatus.RESERVED: "已预约",
    ProductStatus.SOLD: "已成交",
    ProductStatus.DELISTED: "已下架",
    ProductStatus.VIOLATION: "违规下架",
}
