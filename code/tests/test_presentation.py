"""Presentation checks for localization and structured user-facing details."""

import unittest

from ui_common import display_value


class PresentationTests(unittest.TestCase):
    """Protect display semantics without changing storage or business rules."""

    def test_money_is_shown_in_yuan(self):
        self.assertEqual(display_value(1990, "price_cents"), "¥ 19.90")

    def test_utc_timestamp_crosses_into_next_local_date(self):
        self.assertEqual(
            display_value("2026-11-15T20:30:00.000Z", "created_at"), "2026-11-16 04:30:00"
        )

    def test_roles_and_state_are_localized(self):
        self.assertEqual(display_value("buyer,seller", "roles"), "买家、卖家")
        self.assertEqual(display_value("pending_review"), "待审核")

    def test_missing_information_is_explicit(self):
        self.assertEqual(display_value(None), "未记录")
        self.assertEqual(display_value(""), "未记录")

    def test_password_material_is_not_displayed(self):
        self.assertEqual(display_value("secret", "password_hash"), "不展示密码信息")


if __name__ == "__main__":
    unittest.main()
