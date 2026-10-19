"""Command-line entry point for the PR review triage pipeline."""

from collections.abc import Sequence
import sys

from .triage import main as _triage_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the triage CLI."""

    # An omitted argument list is the friendly programmatic entry point used by
    # the smoke check; the executable path passes real command-line arguments.
    return _triage_main([] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
