"""Deterministic diff parsing and review-priority triage.

The module deliberately uses no repository execution or network calls.  It turns a
unified diff into traceable file records, applies conservative heuristics, and
returns a suggested review order.  The result is a review aid, never an approval
or correctness decision.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence, TypedDict

from .report import format_markdown


DISCLAIMER = (
    "This is a suggested review order. Human review is required; "
    "no approval decision was made."
)


class DiffParseError(ValueError):
    """Raised when a supplied unified diff cannot be parsed without data loss."""


@dataclass(frozen=True)
class DiffHunk:
    """A single unified-diff hunk and its normalized line ranges."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: tuple[str, ...]

    @property
    def old_end(self) -> int:
        """Return the inclusive final old-file line represented by the hunk."""

        return self.old_start + max(self.old_count, 1) - 1

    @property
    def new_end(self) -> int:
        """Return the inclusive final new-file line represented by the hunk."""

        return self.new_start + max(self.new_count, 1) - 1

    @property
    def line_range(self) -> str:
        """Return the most useful traceability range for this hunk."""

        if self.new_count:
            end = self.new_start + self.new_count - 1
            return f"{self.new_start}-{end}"
        end = self.old_start + max(self.old_count, 1) - 1
        return f"{self.old_start}-{end}"


@dataclass(frozen=True)
class DiffFile:
    """Normalized changes for one path in a unified diff."""

    path: str
    status: str
    additions: int
    deletions: int
    hunks: tuple[DiffHunk, ...]
    old_path: str | None = None
    new_path: str | None = None
    raw: tuple[str, ...] = ()


class ReviewReport(TypedDict):
    """JSON-compatible schema returned for one changed file."""

    unit: str
    files: list[str]
    what_changed: str
    risk_factors: list[str]
    why_it_might_be_risky: str
    questions_for_human: list[str]
    confidence: str
    evidence: list[str]
    risk_score: int
    behavioral_surface: int
    coverage: dict[str, Any]


_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: ?(.*))?$"
)


def _path_from_header(value: str, prefix: str | None = None) -> str:
    """Normalize a `---`/`+++` path, including the `/dev/null` marker."""

    marker_lengths = {
        "--- ": 4,
        "+++ ": 4,
        "rename from ": 12,
        "rename to ": 10,
    }
    path = next(
        (value[length:] for marker, length in marker_lengths.items() if value.startswith(marker)),
        value,
    )
    path = path.split("\t", 1)[0]
    if path.startswith('"'):
        try:
            fields = shlex.split(path, posix=True)
        except ValueError as exc:
            raise DiffParseError("malformed quoted file path") from exc
        if len(fields) != 1:
            raise DiffParseError("quoted file path must contain one path")
        path = fields[0]
    if path == "/dev/null":
        return path
    if prefix and path.startswith(prefix + "/"):
        return path[len(prefix) + 1 :]
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _git_paths(header: str, line_number: int) -> tuple[str, str]:
    """Read the two paths from a `diff --git` header."""

    try:
        fields = shlex.split(header[len("diff --git ") :], posix=True)
    except ValueError as exc:
        raise DiffParseError(f"line {line_number}: malformed diff header") from exc
    if len(fields) != 2:
        raise DiffParseError(f"line {line_number}: diff header must contain two paths")
    return _path_from_header(fields[0]), _path_from_header(fields[1])


def _parse_block(lines: Sequence[str], start_line: int) -> DiffFile:
    """Parse one file block, raising instead of silently dropping malformed data."""

    if not lines:
        raise DiffParseError(f"line {start_line}: empty diff block")

    git_old: str | None = None
    git_new: str | None = None
    cursor = 0
    if lines[0].startswith("diff --git "):
        git_old, git_new = _git_paths(lines[0], start_line)
        cursor = 1

    old_index = next((i for i in range(cursor, len(lines)) if lines[i].startswith("--- ")), None)
    new_index = (
        old_index + 1
        if old_index is not None and old_index + 1 < len(lines) and lines[old_index + 1].startswith("+++ ")
        else None
    )

    # Binary and rename-only changes have no unified hunks but are still files.
    binary = any(line.startswith("Binary files ") for line in lines)
    rename_to = next((line for line in lines if line.startswith("rename to ")), None)
    rename_from = next((line for line in lines if line.startswith("rename from ")), None)
    if binary:
        old_path = _path_from_header(lines[old_index], "a") if old_index is not None else (
            _path_from_header(rename_from) if rename_from else git_old
        )
        new_path = _path_from_header(lines[new_index], "b") if new_index is not None else (
            _path_from_header(rename_to) if rename_to else git_new
        )
        path = new_path if new_path and new_path != "/dev/null" else old_path
        if not path or path == "/dev/null":
            raise DiffParseError(f"line {start_line}: binary change has no path")
        return DiffFile(path, "binary", 0, 0, (), old_path, new_path, tuple(lines))
    if old_index is None or new_index is None:
        if rename_to or rename_from:
            old_path = _path_from_header(rename_from) if rename_from else git_old
            new_path = _path_from_header(rename_to) if rename_to else git_new
            path = new_path or old_path
            if not path:
                raise DiffParseError(f"line {start_line}: rename has no path")
            return DiffFile(path, "renamed", 0, 0, (), old_path, new_path, tuple(lines))
        # Git can represent mode-only changes without ---/+++ headers.  Keep
        # them in the review plan instead of dropping the changed path.
        if git_new or git_old:
            metadata_only = all(
                line.startswith(("diff --git ", "index ", "old mode ", "new mode "))
                for line in lines
            )
            if metadata_only:
                path = git_new or git_old
                return DiffFile(path, "modified", 0, 0, (), git_old, git_new, tuple(lines))
        raise DiffParseError(f"line {start_line}: file block is missing ---/+++ headers")

    old_path = _path_from_header(lines[old_index], "a")
    new_path = _path_from_header(lines[new_index], "b")
    path = new_path if new_path != "/dev/null" else old_path
    if path == "/dev/null":
        raise DiffParseError(f"line {start_line + old_index}: file path is /dev/null on both sides")

    hunk_start = new_index + 1
    hunks: list[DiffHunk] = []
    additions = 0
    deletions = 0
    cursor = hunk_start
    while cursor < len(lines):
        line = lines[cursor]
        if line.startswith("\\ No newline at end of file"):
            cursor += 1
            continue
        match = _HUNK_RE.match(line)
        if not match:
            # Index/mode/similarity metadata is valid before the first hunk.
            if not hunks and line.startswith(("index ", "old mode ", "new mode ", "similarity index ", "dissimilarity index ")):
                cursor += 1
                continue
            raise DiffParseError(
                f"line {start_line + cursor}: expected a hunk header, got {line!r}"
            )

        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        expected_old = old_count
        expected_new = new_count
        body: list[str] = []
        cursor += 1
        while expected_old or expected_new:
            if cursor >= len(lines):
                raise DiffParseError(
                    f"line {start_line + cursor}: hunk is shorter than its declared ranges"
                )
            body_line = lines[cursor]
            if body_line.startswith("\\ No newline at end of file"):
                body.append(body_line)
                cursor += 1
                continue
            if not body_line or body_line[0] not in " +-":
                raise DiffParseError(
                    f"line {start_line + cursor}: invalid hunk line {body_line!r}"
                )
            marker = body_line[0]
            if marker in " -":
                expected_old -= 1
            if marker in " +":
                expected_new -= 1
            if expected_old < 0 or expected_new < 0:
                raise DiffParseError(
                    f"line {start_line + cursor}: hunk contains more lines than declared"
                )
            additions += marker == "+"
            deletions += marker == "-"
            body.append(body_line)
            cursor += 1
        hunks.append(DiffHunk(old_start, old_count, new_start, new_count, line, tuple(body)))

    status = "added" if old_path == "/dev/null" else "deleted" if new_path == "/dev/null" else "modified"
    if rename_to or rename_from:
        status = "renamed"
    return DiffFile(path, status, additions, deletions, tuple(hunks), old_path, new_path, tuple(lines))


def parse_unified_diff(diff_text: str) -> list[DiffFile]:
    """Parse *diff_text* into one lossless, per-file record per changed path.

    Empty or whitespace-only input returns an empty list.  Non-empty malformed
    input raises :class:`DiffParseError`, including the approximate source line,
    so callers can report an input problem rather than producing an incomplete
    review plan.
    """

    if not isinstance(diff_text, str):
        raise TypeError("diff_text must be a string")
    if not diff_text.strip():
        return []
    lines = diff_text.splitlines()
    # A final blank separator is common when diff text is copied through a
    # shell or editor.  A blank context line is represented by " " and is not
    # removed here.
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return []
    git_starts = [i for i, line in enumerate(lines) if line.startswith("diff --git ")]
    blocks: list[tuple[int, int]] = []
    if git_starts:
        if any(line.strip() for line in lines[: git_starts[0]]):
            raise DiffParseError("diff contains non-empty text before its first file header")
        for index, start in enumerate(git_starts):
            end = git_starts[index + 1] if index + 1 < len(git_starts) else len(lines)
            blocks.append((start, end))
    else:
        file_starts = [
            i
            for i, line in enumerate(lines[:-1])
            if line.startswith("--- ") and lines[i + 1].startswith("+++ ")
        ]
        if not file_starts:
            raise DiffParseError("diff contains no file headers")
        if any(line.strip() for line in lines[: file_starts[0]]):
            raise DiffParseError("diff contains non-empty text before its first file header")
        for index, start in enumerate(file_starts):
            end = file_starts[index + 1] if index + 1 < len(file_starts) else len(lines)
            blocks.append((start, end))

    records = [_parse_block(lines[start:end], start + 1) for start, end in blocks]
    if not records:
        raise DiffParseError("diff did not contain any file records")
    return records


# A short alias is convenient for callers that do not need the full function name.
parse_diff = parse_unified_diff


def _changed_lines(record: DiffFile) -> list[str]:
    """Return added and deleted source lines, excluding diff metadata."""

    return [line[1:] for hunk in record.hunks for line in hunk.lines if line[:1] in "+-"]


def _added_lines(record: DiffFile) -> list[str]:
    """Return only source lines introduced by the change."""

    return [line[1:] for hunk in record.hunks for line in hunk.lines if line.startswith("+")]


def _deleted_lines(record: DiffFile) -> list[str]:
    """Return only source lines removed by the change."""

    return [line[1:] for hunk in record.hunks for line in hunk.lines if line.startswith("-")]


_SECURITY_CHECK_RE = re.compile(
    r"\b(?:auth(?:enticate|orization)?|authorize|check[_ -]?(?:auth|permission|access)|"
    r"require[_ -]?(?:auth|role|permission|login)|permission|privilege|acl|csrf|"
    r"verify[_ -]?(?:token|signature|auth)|validate[_ -]?(?:token|session)|"
    r"is[_ -]?authenticated|access[_ -]?check|security[_ -]?check)\w*\b",
    re.IGNORECASE,
)
_DANGEROUS_ADDITION_RE = re.compile(
    r"(?:\b(?:allow[_ -]?duplicate|allow[_ -]?(?:unverified|insecure|any)|"
    r"bypass(?:ed|ing)?(?:[_ -]?(?:auth|authorization|validation|check))?|"
    r"skip[_ -]?(?:auth|authorization|validation|verify|checks?)|"
    r"disable[_ -]?(?:auth|authorization|csrf|verify|checks?)|"
    r"ignore[_ -]?(?:auth|authorization|validation|verify)|"
    r"permit[_ -]?all|admin[_ -]?override|trust[_ -]?all|unsafe|insecure|"
    r"force[_ -]?(?:allow|send|delete|write))\b|"
     r"\bverify\s*=\s*false\b|--(?:skip|no)[-_](?:auth|verify|checks?))",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[_ -]?key|access[_ -]?key|secret(?:[_ -]?key)?|password|passwd|"
    r"private[_ -]?key|client[_ -]?secret|access[_ -]?token)\b\s*[\"']?\s*[:=]",
    re.IGNORECASE,
)
_SIDE_EFFECT_RE = re.compile(
    r"\b(?:retry|backoff|idempot(?:ent|ency)|allow[_ -]?duplicate|"
    r"(?:send|charge|refund|publish|enqueue|write|save|delete|create|update)\s*\(|"
    r"side[_ -]?effect)\b",
    re.IGNORECASE,
)


def _unit_name(path: str) -> str:
    """Create a stable, readable unit identifier from a POSIX path."""

    stem = str(PurePosixPath(path)).replace("/", "-")
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-") or "changed-file"


def _evidence(record: DiffFile) -> list[str]:
    """Build evidence references that point only to parsed hunks."""

    return [f"{record.path}:{hunk.line_range}" for hunk in record.hunks] or [f"{record.path}:file-header"]


def analyze_file(record: DiffFile, reviewer_focus: str | None = None) -> ReviewReport:
    """Analyze one file with deterministic, explainable review heuristics."""

    path_lower = record.path.lower()
    added_text = "\n".join(_added_lines(record)).lower()
    deleted_text = "\n".join(_deleted_lines(record)).lower()
    text = "\n".join(_changed_lines(record)).lower()
    signal_text = path_lower + " " + text
    factors: list[str] = []

    def add_factor(label: str) -> None:
        if label not in factors:
            factors.append(label)

    is_docs = bool(re.search(r"(^|/)(docs?|readme|changelog)(/|$)|\.(md|rst|txt)$", path_lower))
    is_test = bool(re.search(r"(^|/)(test|tests|spec)(/|$)|(^|[_.-])(test|spec)\.", path_lower))
    if record.status == "binary":
        add_factor("binary or generated content is difficult to inspect")
    if is_docs:
        add_factor("documentation-only change")
    if is_test:
        add_factor("test-only change")
    if record.status in {"added", "deleted", "renamed"}:
        add_factor(f"{record.status} file boundary")
    if re.search(r"auth|authoriz|permission|\bacl\b|credential|secret|token|session|csrf", signal_text):
        add_factor("authorization or security boundary")
    if re.search(r"payment|billing|refund|financial|charge|money|balance", signal_text):
        add_factor("financial or high-integrity state")
    if re.search(r"migration|migrate|schema|database|\bdb\b|persist|storage|drop table|delete from|truncate", signal_text):
        add_factor("data migration or persistence boundary")
    if re.search(r"api|route|endpoint|http|graphql|openapi|public", signal_text):
        add_factor("externally visible contract")
    if re.search(r"transaction|retry|idempot|duplicate|queue|concurr|async|thread|lock|side effect", signal_text):
        add_factor("state transition or failure-mode behavior")
    if re.search(r"error|exception|timeout|fallback|rollback", signal_text):
        add_factor("error handling or recovery path")
    if re.search(r"boundary|off.by.one|index|slice|offset|range\(|<=|>=|loop", signal_text):
        add_factor("boundary-sensitive transformation")

    # Direction matters: a security term in a deleted line is stronger than a
    # copied mention in surrounding context, and a newly added bypass is an
    # explicit hazard even when the path itself is generic.
    if deleted_text and _SECURITY_CHECK_RE.search(deleted_text):
        add_factor("removed security check")
    if added_text and _DANGEROUS_ADDITION_RE.search(added_text):
        add_factor("dangerous added flag or bypass")
    if record.deletions >= 3 and record.deletions >= max(record.additions * 2, 1):
        add_factor("deletion-heavy change")
    if re.search(r"secret|credential|password|passwd|private[_ -]?key|api[_ -]?key|access[_ -]?token|\.env", path_lower):
        add_factor("secrets or credential material")
    elif added_text and _SECRET_ASSIGNMENT_RE.search(added_text):
        add_factor("secrets or credential material")
    has_retry = re.search(r"\bretr(?:y|ies|ied)\b|backoff", signal_text)
    has_side_effect = _SIDE_EFFECT_RE.search(signal_text)
    if (has_retry and has_side_effect) or re.search(r"allow[_ -]?duplicate|idempot", signal_text):
        add_factor("side-effect retry behavior")
    if reviewer_focus and reviewer_focus.lower() in path_lower + " " + text:
        add_factor(f"reviewer focus: {reviewer_focus}")

    critical = {
        "authorization or security boundary",
        "financial or high-integrity state",
        "data migration or persistence boundary",
        "externally visible contract",
        "removed security check",
        "dangerous added flag or bypass",
        "secrets or credential material",
    }
    if critical.intersection(factors):
        risk_score = 5
    elif "side-effect retry behavior" in factors:
        risk_score = 5
    elif "state transition or failure-mode behavior" in factors:
        risk_score = 4
    elif "deletion-heavy change" in factors:
        risk_score = 4
    elif "boundary-sensitive transformation" in factors or "error handling or recovery path" in factors:
        risk_score = 4
    elif is_docs and not record.hunks:
        risk_score = 1
    elif is_docs or is_test or record.status == "renamed":
        risk_score = 2
    elif record.hunks:
        risk_score = 3
    else:
        risk_score = 2

    # Test files can mention the production concern they cover.  That context is
    # useful evidence, but the test change itself should not outrank the
    # production behavior merely because it contains words such as "refund" or
    # "charge".
    if is_test and risk_score > 2:
        risk_score = 2

    if record.status == "binary" and risk_score < 3:
        risk_score = 3

    # Tests are useful evidence, but they should not outrank production
    # behavior because they repeat its domain vocabulary.  Apply this after
    # binary/status adjustments so every test file remains consistently low
    # priority regardless of its representation.
    if is_test:
        risk_score = min(risk_score, 2)

    if record.status == "added":
        action = "Added"
    elif record.status == "deleted":
        action = "Deleted"
    elif record.status == "renamed":
        action = "Renamed"
    elif record.status == "binary":
        action = "Changed binary"
    else:
        action = "Modified"
    if record.hunks:
        what_changed = f"{action} {record.path} with {record.additions} additions and {record.deletions} deletions across {len(record.hunks)} hunk(s)."
    else:
        what_changed = f"{action} {record.path}; no textual hunks were available."

    questions: list[str] = []
    if "authorization or security boundary" in factors:
        questions.append("Are authentication, authorization, and least-privilege checks preserved on every path?")
    if "removed security check" in factors:
        questions.append("What security control was removed, and what equivalent protection now covers this path?")
    if "dangerous added flag or bypass" in factors:
        questions.append("Can the new flag or bypass disable validation, authorization, or duplicate protection in production?")
    if "secrets or credential material" in factors:
        questions.append("Are credentials absent from source control, logs, examples, and generated artifacts?")
    if "financial or high-integrity state" in factors:
        questions.append("Can invalid, repeated, or partial inputs alter financial or other high-integrity state?")
    if "data migration or persistence boundary" in factors:
        questions.append("Is the migration or persistence change reversible and compatible with existing data?")
    if "externally visible contract" in factors:
        questions.append("Do callers, validation, compatibility, and error responses still match the public contract?")
    if "state transition or failure-mode behavior" in factors:
        questions.append("What happens after a timeout, retry, crash, or concurrent invocation?")
    if "side-effect retry behavior" in factors:
        questions.append("Is the side effect idempotent, or can a retry repeat it after an ambiguous failure?")
    if "deletion-heavy change" in factors:
        questions.append("Which removed behavior is intentionally obsolete, and is rollback or compatibility still possible?")
    if "boundary-sensitive transformation" in factors:
        questions.append("What are the empty, first, last, and just-outside-the-range cases?")
    if record.hunks and not is_test:
        questions.append("Which focused tests demonstrate the changed behavior and its failure boundaries?")
    if not questions:
        questions.append("Is the observed change intentional, and is its scope covered by an appropriate check?")

    if not record.hunks:
        confidence = "low"
    elif factors and not (is_docs or is_test):
        confidence = "high"
    else:
        confidence = "medium"

    why = (
        "Observed signals indicate "
        + (", ".join(factors) if factors else "a localized implementation change")
        + ". These signals may warrant focused human review; the diff alone is insufficient to establish correctness."
    )
    surface_weights = {
        "authorization or security boundary": 10,
        "financial or high-integrity state": 10,
        "data migration or persistence boundary": 10,
        "externally visible contract": 8,
        "state transition or failure-mode behavior": 8,
        "removed security check": 12,
        "dangerous added flag or bypass": 12,
        "secrets or credential material": 12,
        "deletion-heavy change": 6,
        "side-effect retry behavior": 10,
        "error handling or recovery path": 4,
        "boundary-sensitive transformation": 4,
    }
    behavioral_surface = max(1, record.additions + record.deletions)
    if not is_test:
        behavioral_surface += sum(surface_weights.get(factor, 0) for factor in factors)

    return {
        "unit": _unit_name(record.path),
        "files": [record.path],
        "what_changed": what_changed,
        "risk_factors": factors,
        "why_it_might_be_risky": why,
        "questions_for_human": questions,
        "confidence": confidence,
        "evidence": _evidence(record),
        "risk_score": risk_score,
        "behavioral_surface": behavioral_surface,
        "coverage": {
            "files": [record.path],
            "hunks": _evidence(record) if record.hunks else [],
            "complete": True,
        },
    }


def rank_reports(reports: Iterable[Mapping[str, Any]]) -> list[ReviewReport]:
    """Sort reports by risk, uncertainty, behavioral surface, then stable path."""

    confidence_order = {"low": 0, "medium": 1, "high": 2}

    def sort_key(report: Mapping[str, Any]) -> tuple[int, int, int, str, str]:
        files = report.get("files", [])
        path = str(files[0]) if files else str(report.get("unit", ""))
        unit = str(report.get("unit", ""))
        confidence = str(report.get("confidence", "low")).lower()
        return (
            -int(report.get("risk_score", 1)),
            confidence_order.get(confidence, 0),
            -int(report.get("behavioral_surface", 0)),
            path,
            unit,
        )

    return [dict(report) for report in sorted(reports, key=sort_key)]  # type: ignore[misc]


def analyze_diff(diff_text: str, reviewer_focus: str | None = None) -> list[ReviewReport]:
    """Parse and heuristically analyze every file in a unified diff."""

    return [analyze_file(record, reviewer_focus) for record in parse_unified_diff(diff_text)]


def triage_diff(diff_text: str, reviewer_focus: str | None = None) -> dict[str, Any]:
    """Return a complete, JSON-ready review plan with graceful input failures."""

    try:
        records = parse_unified_diff(diff_text)
    except (DiffParseError, TypeError) as exc:
        return {
            "review_order": [],
            "reports": [],
            "changed_files": [],
            "errors": [str(exc)],
            "notices": [],
            "disclaimer": DISCLAIMER,
            "input_status": "malformed",
        }

    reports = rank_reports(analyze_file(record, reviewer_focus) for record in records)
    files = [record.path for record in records]
    result: dict[str, Any] = {
        "review_order": reports,
        "reports": reports,
        "changed_files": files,
        "errors": [],
        "notices": ["No changes supplied; no review units were produced."] if not records else [],
        "disclaimer": DISCLAIMER,
        "input_status": "empty" if not records else "ok",
        "coverage": {"changed_files": files, "covered_files": files, "complete": True},
    }
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a deterministic risk-first plan from a unified diff.")
    parser.add_argument("diff", nargs="?", help="path to a unified diff file; use --stdin for standard input")
    parser.add_argument("--stdin", action="store_true", help="read the unified diff from standard input")
    parser.add_argument("--reviewer-focus", help="optional focus keyword, such as security or compatibility")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="output format (default: json)")
    parser.add_argument("--output", metavar="PATH", help="write the rendered report to PATH instead of standard output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point that prints a JSON review plan and returns an exit code."""

    args = _build_parser().parse_args(argv)
    if args.stdin:
        diff_text = sys.stdin.read()
    elif args.diff:
        try:
            with open(args.diff, "r", encoding="utf-8") as diff_file:
                diff_text = diff_file.read()
        except OSError as exc:
            print(json.dumps({"errors": [str(exc)], "disclaimer": DISCLAIMER}, indent=2))
            return 2
    elif argv is None and sys.stdin is not None and not sys.stdin.isatty():
        # Piped input is convenient, while an interactive no-argument launch stays friendly.
        try:
            diff_text = sys.stdin.read()
        except OSError:
            print("Explain My Diff: ready for a diff. Use --stdin or provide a diff path.")
            return 0
    else:
        print("Explain My Diff: ready for a diff. Use --stdin or provide a diff path.")
        return 0

    result = triage_diff(diff_text, args.reviewer_focus)
    rendered = format_markdown(result) if args.format == "markdown" else json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8", newline="\n") as output_file:
                output_file.write(rendered)
                output_file.write("\n")
        except OSError as exc:
            print(json.dumps({"errors": [str(exc)], "disclaimer": DISCLAIMER}, indent=2))
            return 2
    else:
        print(rendered)
    return 2 if result["input_status"] == "malformed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
