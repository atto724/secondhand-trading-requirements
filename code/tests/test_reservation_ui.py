"""State classification and role-sensitive reservation controls."""

import gc
import json
import tkinter as tk
import unittest
from unittest.mock import patch

from trades import LABELS
from trades_ui import RESERVATION_GROUPS, ReservationsPage, reservation_actions
from ui_common import configure_style


def fixture(key, state, cancel_by=None):
    """Build service-shaped rows for isolated presentation checks."""
    return {
        "id": key,
        "status": state,
        "buyer_id": 1,
        "seller_id": 2,
        "cancel_by": cancel_by,
        "product_status": "published" if state == "waiting" else "reserved",
        "blocked": 0,
        "snapshot": json.dumps({"title": f"商品{key}"}),
        "buyer_name": "买家",
        "created_at": "2026-11-16T00:00:00Z",
    }


class ReservationActionTests(unittest.TestCase):
    """Verify the operation matrix and cancellation initiator distinction."""

    def test_each_state_has_only_meaningful_buyer_and_seller_actions(self):
        expected = {
            "waiting": (["cancel"], ["confirm", "reject"]),
            "confirmed": (["cancel"], ["deliver", "cancel"]),
            "delivered": (["complete", "cancel"], ["cancel"]),
            "cancel_requested": ([], ["agree", "disagree"]),
        }
        for state in LABELS:
            row = fixture(1, state, 1)
            for index, (scope, actor) in enumerate((("buyer", 1), ("seller", 2))):
                with self.subTest(state=state, scope=scope):
                    self.assertEqual(
                        [key for _, key in reservation_actions(scope, actor, row)],
                        expected.get(state, ([], []))[index],
                    )
        row = fixture(1, "cancel_requested", 2)
        self.assertEqual(
            [key for _, key in reservation_actions("buyer", 1, row)], ["agree", "disagree"]
        )
        self.assertEqual(reservation_actions("seller", 2, row), [])
        self.assertEqual(reservation_actions("buyer", 99, fixture(1, "waiting")), [])
        self.assertEqual(reservation_actions("buyer", 1, None), [])

    def test_categories_partition_all_states_and_blocked_product_hides_confirmation(self):
        groups = [states for key, _, states in RESERVATION_GROUPS if key != "all"]
        self.assertEqual(set.union(*groups), set(LABELS))
        self.assertEqual(sum(len(group) for group in groups), len(LABELS))
        row = fixture(1, "waiting")
        row["blocked"] = 1
        self.assertEqual(reservation_actions("seller", 2, row), [])


class ReservationPageTests(unittest.TestCase):
    """Exercise real widgets when changing classification, selection and status."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        configure_style(self.root)
        self.records = [
            fixture(1, "waiting"),
            fixture(2, "cancel_requested", 1),
            fixture(3, "cancel_requested", 2),
            fixture(4, "completed"),
            fixture(5, "expired"),
        ]
        self.service = patch(
            "trades_ui.list_reservations", side_effect=lambda actor, scope: list(self.records)
        )
        self.service.start()
        self.addCleanup(self.service.stop)
        self.page = ReservationsPage(self.root, 2, "seller")
        self.addCleanup(self.cleanup_widgets)

    def cleanup_widgets(self):
        """Keep Tcl object finalization on the main thread."""
        self.root.destroy()
        self.page = None
        self.root = None
        gc.collect()

    def select_group(self, key):
        self.page.group_text.set(
            next(text for text, value in self.page.group_options.items() if value == key)
        )
        self.page.choose_group()

    def buttons(self):
        return [button.cget("text") for button in self.page.action_bar.winfo_children()]

    def select(self, key):
        self.page.table.tree.selection_set(str(key))
        self.page.show_actions()

    def test_group_selection_and_cancellation_direction_control_visible_buttons(self):
        self.assertEqual(self.page.table.tree.get_children(), ("1",))
        self.assertEqual(self.buttons(), [])
        self.select(1)
        self.assertEqual(self.buttons(), ["确认预约", "拒绝预约"])
        self.select_group("cancel_requested")
        self.assertEqual(set(self.page.table.tree.get_children()), {"2", "3"})
        self.assertEqual(self.buttons(), [])
        self.select(2)
        self.assertEqual(self.buttons(), ["同意取消", "不同意，转人工"])
        self.select(3)
        self.assertEqual(self.buttons(), [])
        self.assertIn("等待对方处理", self.page.action_hint.cget("text"))
        self.select_group("ended")
        self.select(5)
        self.assertEqual(self.buttons(), [])
        self.assertTrue(self.page.detail_button.instate(["!disabled"]))

    def test_refresh_removes_changed_record_and_stale_actions_without_resetting_category(self):
        self.select(1)
        self.records[0] = fixture(1, "confirmed")
        self.page.refresh()
        self.assertEqual(self.page.group_key, "waiting")
        self.assertEqual(self.page.table.tree.get_children(), ())
        self.assertEqual(self.buttons(), [])
        self.assertTrue(self.page.detail_button.instate(["disabled"]))
        self.assertIn("暂无预约", self.page.action_hint.cget("text"))
        self.select_group("confirmed")
        self.select(1)
        self.assertEqual(self.buttons(), ["登记交付", "申请取消"])


if __name__ == "__main__":
    unittest.main()
