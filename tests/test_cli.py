import json
import subprocess
import sys
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


if __name__ == "__main__":
    unittest.main()
