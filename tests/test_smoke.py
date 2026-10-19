import io
import unittest
from contextlib import redirect_stdout

from app.__main__ import main


class SmokeTest(unittest.TestCase):
    def test_application_starts(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            main()
        self.assertIn("ready", output.getvalue())


if __name__ == "__main__":
    unittest.main()
