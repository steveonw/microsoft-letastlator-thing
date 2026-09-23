import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "frontend" / "demo"


class FrontendDemoContractTests(unittest.TestCase):
    def test_demo_files_have_no_merge_conflict_markers(self) -> None:
        for name in ("app.js", "index.html", "README.md"):
            text = (DEMO / name).read_text(encoding="utf-8")
            self.assertNotIn("<<<<<<<", text, name)
            self.assertNotIn("=======", text, name)
            self.assertNotIn(">>>>>>>", text, name)

    def test_demo_uses_fastapi_analysis_route_and_guided_controls(self) -> None:
        app = (DEMO / "app.js").read_text(encoding="utf-8")
        page = (DEMO / "index.html").read_text(encoding="utf-8")

        self.assertIn('api("/api/analysis")', app)
        self.assertIn('api("/api/provider")', app)
        self.assertNotIn("localStorage", app)

        for source in ("id", "url", "text", "file"):
            self.assertIn(f'id="tab-{source}"', page)

        for element_id in (
            "reset-btn",
            "clarify-btn",
            "edit-btn",
            "verify-btn",
            "flag-btn",
            "next-btn",
        ):
            self.assertIn(f'id="{element_id}"', page)


if __name__ == "__main__":
    unittest.main()
