import json
import unittest
from pathlib import Path

from app.triage import DiffParseError, analyze_file, parse_unified_diff, rank_reports, triage_diff


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

    def test_parser_unquotes_paths_with_spaces(self) -> None:
        diff = (
            'diff --git "a/src/space name.py" "b/src/space name.py"\n'
            '--- "a/src/space name.py"\n'
            '+++ "b/src/space name.py"\n'
            '@@ -1 +1 @@\n'
            '-return 1\n'
            '+return 2\n'
        )

        records = parse_unified_diff(diff)

        self.assertEqual(records[0].path, "src/space name.py")
        self.assertEqual(records[0].old_path, "src/space name.py")
        self.assertEqual(records[0].new_path, "src/space name.py")

    def test_binary_and_rename_records_keep_changed_file_coverage(self) -> None:
        diff = (
            "diff --git a/assets/logo.png b/assets/logo.png\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "Binary files /dev/null and b/assets/logo.png differ\n"
            'diff --git "a/old name.txt" "b/new name.txt"\n'
            "similarity index 100%\n"
            'rename from "old name.txt"\n'
            'rename to "new name.txt"\n'
        )

        result = triage_diff(diff)
        records = parse_unified_diff(diff)

        self.assertEqual(records[0].status, "binary")
        self.assertEqual(records[0].path, "assets/logo.png")
        self.assertEqual(records[1].status, "renamed")
        self.assertEqual(records[1].old_path, "old name.txt")
        self.assertEqual(records[1].new_path, "new name.txt")
        self.assertEqual(result["changed_files"], ["assets/logo.png", "new name.txt"])
        self.assertTrue(result["coverage"]["complete"])

    def test_suspicious_removal_and_addition_get_explicit_signals(self) -> None:
        diff = (
            "diff --git a/src/auth/routes.py b/src/auth/routes.py\n"
            "--- a/src/auth/routes.py\n"
            "+++ b/src/auth/routes.py\n"
            "@@ -1,2 +1,3 @@\n"
            '-    require_role(auth, "billing:write")\n'
            "+    verify = False\n"
            '+    API_KEY = "not-a-real-secret"\n'
            "     return process()\n"
        )

        report = analyze_file(parse_unified_diff(diff)[0])

        self.assertEqual(report["risk_score"], 5)
        self.assertIn("removed security check", report["risk_factors"])
        self.assertIn("dangerous added flag or bypass", report["risk_factors"])
        self.assertIn("secrets or credential material", report["risk_factors"])

    def test_deletion_persistence_and_side_effect_retry_signals(self) -> None:
        diff = (
            "diff --git a/src/db/migration.py b/src/db/migration.py\n"
            "--- a/src/db/migration.py\n"
            "+++ b/src/db/migration.py\n"
            "@@ -1,4 +1 @@\n"
            "-drop_old_column()\n"
            "-delete_legacy_rows()\n"
            "-remove_old_index()\n"
            "-cleanup_old_table()\n"
            "+persist_new_schema()\n"
            "diff --git a/src/workers/charges.py b/src/workers/charges.py\n"
            "--- a/src/workers/charges.py\n"
            "+++ b/src/workers/charges.py\n"
            "@@ -1 +1,2 @@\n"
            " try:\n"
            "+    return retry(job, allow_duplicate=True)\n"
        )

        reports = {report["files"][0]: report for report in triage_diff(diff)["reports"]}

        self.assertIn("deletion-heavy change", reports["src/db/migration.py"]["risk_factors"])
        self.assertIn("data migration or persistence boundary", reports["src/db/migration.py"]["risk_factors"])
        self.assertIn("side-effect retry behavior", reports["src/workers/charges.py"]["risk_factors"])

    def test_copied_domain_words_in_tests_do_not_outrank_production(self) -> None:
        diff = (
            "diff --git a/src/worker.py b/src/worker.py\n"
            "--- a/src/worker.py\n"
            "+++ b/src/worker.py\n"
            "@@ -1 +1 @@\n"
            "-return value\n"
            "+return value + 1\n"
            "diff --git a/test_worker.py b/test_worker.py\n"
            "--- a/test_worker.py\n"
            "+++ b/test_worker.py\n"
            "@@ -1 +1,2 @@\n"
            " def test_worker():\n"
            "+    # authorization, refund, and migration boundaries\n"
        )

        order = [report["files"][0] for report in triage_diff(diff)["review_order"]]

        self.assertEqual(order[0], "src/worker.py")

    def test_equal_reports_have_path_order_tie_break(self) -> None:
        reports = [
            {"unit": "z", "files": ["src/z.py"], "risk_score": 3, "confidence": "medium", "behavioral_surface": 4},
            {"unit": "a", "files": ["src/a.py"], "risk_score": 3, "confidence": "medium", "behavioral_surface": 4},
        ]

        ranked = rank_reports(reports)

        self.assertEqual([report["files"][0] for report in ranked], ["src/a.py", "src/z.py"])


if __name__ == "__main__":
    unittest.main()
