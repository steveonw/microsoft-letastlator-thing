import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from models import AnalysisRun


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "shared" / "sample-analysis.json"


def load_sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


class ContractTests(unittest.TestCase):
    def test_sample_is_valid(self) -> None:
        AnalysisRun.model_validate(load_sample())

    def test_missing_evidence_reference_is_rejected(self) -> None:
        data = load_sample()
        data["steps"][0]["claims"][0]["evidence_ids"].append("evidence-missing")
        with self.assertRaises(ValidationError):
            AnalysisRun.model_validate(data)

    def test_broken_source_offset_is_rejected(self) -> None:
        data = load_sample()
        data["evidence"][0]["start_offset"] = 0
        data["evidence"][0]["end_offset"] = 10
        with self.assertRaises(ValidationError):
            AnalysisRun.model_validate(data)

    def test_missing_step_dependency_is_rejected(self) -> None:
        data = load_sample()
        data["steps"][1]["depends_on"] = ["step-missing"]
        with self.assertRaises(ValidationError):
            AnalysisRun.model_validate(data)

    def test_supported_claim_requires_evidence(self) -> None:
        data = load_sample()
        data["steps"][1]["claims"][0]["evidence_ids"] = []
        with self.assertRaises(ValidationError):
            AnalysisRun.model_validate(data)

    def test_non_supported_claim_requires_note(self) -> None:
        data = load_sample()
        data["steps"][1]["claims"][1]["verification_note"] = None
        with self.assertRaises(ValidationError):
            AnalysisRun.model_validate(data)


if __name__ == "__main__":
    unittest.main()
