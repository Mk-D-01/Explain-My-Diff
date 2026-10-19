"""Run the fixed buildathon evaluation fixtures and print an inspectable scorecard."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures"

CASES = (
    ("fixture-a.diff", "src/api/routes.py"),
    ("fixture-b.diff", "src/transform/rows.py"),
    ("fixture-c.diff", "src/workers/charges.py"),
)


def evaluate() -> dict[str, Any]:
    """Return the deterministic scorecard used by the buildathon demo."""

    sys.path.insert(0, str(ROOT))
    from app.triage import triage_diff

    cases: list[dict[str, Any]] = []
    for fixture_name, expected_path in CASES:
        fixture_path = FIXTURE_DIR / fixture_name
        result = triage_diff(fixture_path.read_text(encoding="utf-8"))
        ranked_paths = [report["files"][0] for report in result["review_order"]]
        rank = ranked_paths.index(expected_path) + 1 if expected_path in ranked_paths else None
        cases.append(
            {
                "fixture": fixture_name,
                "buggy_file": expected_path,
                "rank": rank,
                "top_two": rank is not None and rank <= 2,
                "input_status": result["input_status"],
                "coverage_complete": result.get("coverage", {}).get("complete", False),
                "error_count": len(result.get("errors", [])),
            }
        )

    passed = sum(case["top_two"] for case in cases)
    coverage_passed = all(case["coverage_complete"] for case in cases)
    return {
        "metric": "top-2 bug recall",
        "passed": passed,
        "total": len(cases),
        "recall": passed / len(cases) if cases else 0.0,
        "coverage_complete": coverage_passed,
        "cases": cases,
        "human_review_required": True,
    }


def main() -> int:
    scorecard = evaluate()
    print("Explain My Diff - buildathon evaluation")
    print(f"Top-2 bug recall: {scorecard['passed']}/{scorecard['total']} ({scorecard['recall']:.0%})")
    for case in scorecard["cases"]:
        status = "PASS" if case["top_two"] else "FAIL"
        print(f"  {status}  {case['fixture']}: {case['buggy_file']} ranked {case['rank']}")
    print(f"Coverage complete: {'yes' if scorecard['coverage_complete'] else 'no'}")
    print("Human review required: yes; this scorecard makes no approval decision.")
    print("\nMachine-readable scorecard:")
    print(json.dumps(scorecard, indent=2, sort_keys=True))
    return 0 if scorecard["passed"] == scorecard["total"] and scorecard["coverage_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
