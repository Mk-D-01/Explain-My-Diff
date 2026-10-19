"""Human-readable renderers for PR review triage results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _inline(value: Any) -> str:
    """Keep arbitrary report values safe and readable in Markdown prose."""

    text = " ".join(str(value).splitlines())
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _risk_label(score: Any) -> str:
    """Return a stable human-readable label for the five-point risk score."""

    try:
        normalized = int(score)
    except (TypeError, ValueError):
        normalized = 1
    if normalized >= 5:
        return "Critical"
    if normalized == 4:
        return "High"
    if normalized == 3:
        return "Moderate"
    if normalized == 2:
        return "Low"
    return "Minimal"


def _as_list(value: Any) -> list[Any]:
    """Normalize optional sequence fields without making formatting fragile."""

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _bullet_list(values: Sequence[Any], empty: str = "None recorded.") -> list[str]:
    if not values:
        return [f"- {empty}"]
    return [f"- {_inline(value)}" for value in values]


def format_markdown(result: Mapping[str, Any]) -> str:
    """Render a complete triage result as a review-friendly Markdown report."""

    status = result.get("input_status", "unknown")
    changed_files = _as_list(result.get("changed_files"))
    reports = _as_list(result.get("review_order"))
    errors = _as_list(result.get("errors"))
    notices = _as_list(result.get("notices"))
    coverage = result.get("coverage")
    coverage_map = coverage if isinstance(coverage, Mapping) else {}
    covered_files = _as_list(coverage_map.get("covered_files"))
    complete = coverage_map.get("complete", False)

    lines = [
        "# PR Review Triage Report",
        "",
        "## Input status",
        "",
        f"- **Status:** `{_inline(status)}`",
        f"- **Changed files:** {len(changed_files)}",
    ]
    if errors:
        lines.extend(["- **Errors:**", *_bullet_list(errors)])
    if notices:
        lines.extend(["- **Notices:**", *_bullet_list(notices)])

    lines.extend(["", "## Ranked review order", ""])
    if reports:
        lines.extend(
            [
                "| Rank | Changed file(s) | Risk | Score | Confidence |",
                "| ---: | --- | --- | ---: | --- |",
            ]
        )
        for rank, report in enumerate(reports, 1):
            report_map = report if isinstance(report, Mapping) else {}
            files = _as_list(report_map.get("files"))
            file_text = ", ".join(f"`{_inline(path)}`" for path in files) or "(unspecified)"
            score = report_map.get("risk_score", 1)
            lines.append(
                f"| {rank} | {file_text} | {_risk_label(score)} | {_inline(score)}/5 | "
                f"{_inline(report_map.get('confidence', 'unknown'))} |"
            )

        lines.append("")
        for rank, report in enumerate(reports, 1):
            report_map = report if isinstance(report, Mapping) else {}
            files = _as_list(report_map.get("files"))
            title = ", ".join(_inline(path) for path in files) or _inline(report_map.get("unit", "review unit"))
            score = report_map.get("risk_score", 1)
            lines.extend(
                [
                    f"### {rank}. `{title}` — {_risk_label(score)} risk ({_inline(score)}/5)",
                    "",
                    f"- **Confidence:** {_inline(report_map.get('confidence', 'unknown'))}",
                    f"- **What changed:** {_inline(report_map.get('what_changed', 'Not specified.'))}",
                    f"- **Why risky:** {_inline(report_map.get('why_it_might_be_risky', 'Not specified.'))}",
                    "- **Evidence:**",
                    *_bullet_list(_as_list(report_map.get("evidence"))),
                    "- **Questions for human:**",
                    *_bullet_list(_as_list(report_map.get("questions_for_human"))),
                    "",
                ]
            )
    else:
        lines.append("No review units were produced.")

    changed_paths = ", ".join(f"`{_inline(path)}`" for path in changed_files) or "None"
    covered_paths = ", ".join(f"`{_inline(path)}`" for path in covered_files) or "None"
    lines.extend(
        [
            "## Coverage summary",
            "",
            f"- **Changed files:** {len(changed_files)}",
            f"- **Covered files:** {len(covered_files)}",
            f"- **Complete:** {'yes' if complete else 'no'}",
            f"- **Changed paths:** {changed_paths}",
            f"- **Covered paths:** {covered_paths}",
            "",
            "## Review disclaimer",
            "",
            f"> **Disclaimer:** {_inline(result.get('disclaimer', 'Human review is required; no approval decision was made.'))}",
            "",
        ]
    )
    return "\n".join(lines)
