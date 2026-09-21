import json
from pathlib import Path

from models import AnalysisRun


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "shared" / "sample-analysis.json"


def main() -> None:
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    analysis = AnalysisRun.model_validate(data)

    print(
        f"Validated {analysis.id}: "
        f"{analysis.policy.title} "
        f"({len(analysis.steps)} steps, {len(analysis.evidence)} evidence items)"
    )


if __name__ == "__main__":
    main()
