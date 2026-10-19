import json
import unittest
from pathlib import Path

from app.triage import DiffParseError, parse_unified_diff, triage_diff


FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TriagePipelineTest(unittest.TestCase):
    def test_parser_preserves_files_and_hunk_evidence(self) -> None:
        records = parse_unified_diff(read_fixture("fixture-a.diff"))

        self.assertEqual([record.path for record in records], ["src/api/routes.py", "docs/review.md", "tests/test_routes.py"])
        self.assertEqual(records[0].additions, 1)
        self.assertEqual(records[0].deletions, 1)
        self.assertEqual(records[0].hunks[0].line_range, "10-11")

    def test_buggy_file_is_in_top_two_for_all_evaluation_fixtures(self) -> None:
        cases = {
            "fixture-a.diff": "src/api/routes.py",
            "fixture-b.diff": "src/transform/rows.py",
            "fixture-c.diff": "src/workers/charges.py",
        }

        for fixture, buggy_path in cases.items():
            with self.subTest(fixture=fixture):
                result = triage_diff(read_fixture(fixture))
                ranked_paths = [report["files"][0] for report in result["review_order"]]
                self.assertLessEqual(ranked_paths.index(buggy_path), 1)
                self.assertEqual(result["input_status"], "ok")
                self.assertTrue(result["coverage"]["complete"])
                self.assertCountEqual(result["changed_files"], ranked_paths)

    def test_reports_are_traceable_and_never_claim_approval(self) -> None:
        result = triage_diff(read_fixture("fixture-c.diff"), reviewer_focus="security")

        self.assertIn("Human review is required", result["disclaimer"])
        self.assertNotIn("approved", json.dumps(result).lower())
        for report in result["reports"]:
            self.assertEqual(report["coverage"]["files"], report["files"])
            self.assertTrue(report["what_changed"])
            self.assertTrue(report["why_it_might_be_risky"])
            self.assertTrue(report["questions_for_human"])
            self.assertTrue(report["evidence"])

    def test_malformed_input_is_reported_without_partial_results(self) -> None:
        result = triage_diff(
            "diff --git a/broken.py b/broken.py\n"
            "--- a/broken.py\n"
            "+++ b/broken.py\n"
            "@@ -1 +1 @@\n"
        )

        self.assertEqual(result["input_status"], "malformed")
        self.assertEqual(result["reports"], [])
        self.assertTrue(result["errors"])
        self.assertEqual(result["changed_files"], [])

    def test_empty_input_is_explicit(self) -> None:
        result = triage_diff("\n")

        self.assertEqual(result["input_status"], "empty")
        self.assertEqual(result["review_order"], [])
        self.assertTrue(result["notices"])

    def test_parser_rejects_non_diff_text(self) -> None:
        with self.assertRaises(DiffParseError):
            parse_unified_diff("this is not a unified diff")


if __name__ == "__main__":
    unittest.main()
