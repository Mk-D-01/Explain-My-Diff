import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "fixture-a.diff"


class CliFlowTest(unittest.TestCase):
    def test_cli_reads_diff_file_and_emits_ranked_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "app", str(FIXTURE)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        result = json.loads(completed.stdout)
        self.assertEqual(result["input_status"], "ok")
        self.assertEqual(result["review_order"][0]["files"][0], "src/api/routes.py")
        self.assertIn("Human review is required", result["disclaimer"])

    def test_cli_accepts_stdin(self) -> None:
        diff_text = FIXTURE.read_text(encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-m", "app", "--stdin"],
            cwd=ROOT,
            input=diff_text,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(json.loads(completed.stdout)["input_status"], "ok")

    def test_cli_emits_human_readable_markdown(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "app", "--format", "markdown", str(FIXTURE)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        markdown = completed.stdout
        self.assertIn("# PR Review Triage Report", markdown)
        self.assertIn("**Status:** `ok`", markdown)
        self.assertIn("## Ranked review order", markdown)
        self.assertIn("src/api/routes.py", markdown)
        self.assertIn("Critical", markdown)
        self.assertIn("**What changed:**", markdown)
        self.assertIn("**Why risky:**", markdown)
        self.assertIn("**Evidence:**", markdown)
        self.assertIn("**Questions for human:**", markdown)
        self.assertIn("## Coverage summary", markdown)
        self.assertIn("Human review is required; no approval decision was made.", markdown)

    def test_cli_writes_selected_format_to_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "review.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "--format",
                    "markdown",
                    "--output",
                    str(output_path),
                    str(FIXTURE),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.stdout, "")
            self.assertTrue(output_path.exists())
            self.assertIn("# PR Review Triage Report", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
