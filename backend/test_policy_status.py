import unittest
from datetime import date, datetime, timezone

from federal_register import NormalizedPolicyDocument
from policy_status import (
    _latest_pub_id,
    parse_reginfo_status,
    unavailable_policy_status,
)


SEARCH_HTML = """
<a href="/public/do/eAgendaViewRule?RIN=0694-AJ55&amp;pubId=202404">old</a>
<a href="/public/do/eAgendaViewRule?RIN=0694-AJ55&amp;pubId=202510">current</a>
"""

RULE_HTML = """
<html><body>
<div>RIN Status: Completed</div>
<div>Agenda Stage of Rulemaking: Completed Actions</div>
<div>Major: No</div>
<div>Timetable:</div>
<table>
<tr><th>Action</th><th>Date</th><th>FR Cite</th></tr>
<tr><td>NPRM</td><td>09/11/2024</td><td>89 FR 73612</td></tr>
<tr><td>Withdrawn</td><td>12/16/2025</td><td></td></tr>
</table>
<div>Regulatory Flexibility Analysis Required: No</div>
</body></html>
"""


class PolicyStatusTests(unittest.TestCase):
    def test_latest_pub_id_uses_newest_unified_agenda_publication(self) -> None:
        self.assertEqual(_latest_pub_id(SEARCH_HTML, "0694-AJ55"), "202510")

    def test_later_withdrawal_is_reported_as_material_freshness_change(self) -> None:
        checked = datetime(2026, 9, 23, tzinfo=timezone.utc)
        status = parse_reginfo_status(
            RULE_HTML,
            rin="0694-AJ55",
            publication_id="202510",
            source_url="https://example.invalid/status",
            document_publication_date=date(2024, 9, 11),
            checked_at=checked,
        )

        self.assertTrue(status.available)
        self.assertEqual(status.agenda_stage, "Completed Actions")
        self.assertEqual(status.rin_status, "Completed")
        self.assertTrue(status.later_material_action_found)
        self.assertIsNotNone(status.latest_completed_action)
        self.assertEqual(status.latest_completed_action.name, "Withdrawn")
        self.assertEqual(
            status.latest_completed_action.action_date.isoformat(),
            "2025-12-16",
        )
        self.assertIn("historical context", status.freshness_message)

    def test_unavailable_status_does_not_claim_current_state(self) -> None:
        status = unavailable_policy_status(
            "network unavailable",
            rin="0694-AJ55",
        )
        self.assertFalse(status.available)
        self.assertEqual(status.status_label, "Status check unavailable")
        self.assertIn("checked manually", status.freshness_message)
        self.assertEqual(status.error, "network unavailable")


if __name__ == "__main__":
    unittest.main()
