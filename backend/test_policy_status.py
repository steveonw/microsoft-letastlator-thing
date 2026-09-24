import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone

from federal_register import NormalizedPolicyDocument
from policy_status import (
    _latest_pub_id,
    fetch_federal_register_rin_documents,
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

    def test_latest_pub_id_does_not_depend_on_query_parameter_order(self) -> None:
        html = """
        <a href="/public/do/eAgendaViewRule?pubId=202510&amp;RIN=0694-AJ55">current</a>
        """
        self.assertEqual(_latest_pub_id(html, "0694-AJ55"), "202510")

    def test_federal_register_rin_pull_normalizes_documents(self) -> None:
        payload = {
            "results": [
                {
                    "document_number": "2024-20529",
                    "title": "AI reporting proposal",
                    "type": "Proposed Rule",
                    "action": "Proposed rule; request for comment",
                    "publication_date": "2024-09-11",
                    "html_url": "https://www.federalregister.gov/d/2024-20529",
                },
                {
                    "document_number": "2025-99999",
                    "title": "Later related action",
                    "type": "Rule",
                    "action": "Final rule",
                    "publication_date": "2025-12-01",
                    "html_url": "https://www.federalregister.gov/d/2025-99999",
                },
            ]
        }

        with patch("policy_status._get_json", return_value=payload):
            documents = fetch_federal_register_rin_documents("0694-AJ55")

        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0].document_number, "2024-20529")
        self.assertEqual(documents[1].publication_date.isoformat(), "2025-12-01")

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
