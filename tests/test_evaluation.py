import unittest

from scripts.evaluate import evaluate


class EvaluationScorecardTest(unittest.TestCase):
    def test_fixed_fixtures_hit_the_top_two_target(self) -> None:
        scorecard = evaluate()

        self.assertEqual(scorecard["passed"], 3)
        self.assertEqual(scorecard["total"], 3)
        self.assertEqual(scorecard["recall"], 1.0)
        self.assertTrue(scorecard["coverage_complete"])
        self.assertTrue(all(case["top_two"] for case in scorecard["cases"]))


if __name__ == "__main__":
    unittest.main()
