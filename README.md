# Explain My Diff — PR Review Triage Agent

Explain My Diff turns a unified Git diff into a deterministic, risk-first review
plan. It helps a reviewer decide where to look first without approving, merging,
or declaring the change safe. Every report preserves the changed file and hunk
range that produced it.

## Prerequisites

- Python 3.12.4 (see `.python-version`)
- Docker, for the container workflow

The application uses only the Python standard library. `requirements.lock` is
kept as the dependency lockfile and is intentionally empty for this version.

## Setup

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --requirement requirements.lock
```

Copy `.env.example` to `.env` when local configuration is needed. Do not commit `.env` or secrets.

## Run the triage flow

Pass a saved unified diff:

```bash
python -m app tests/fixtures/fixture-a.diff
```

Or pipe a diff from Git:

```bash
git diff main...HEAD | python -m app --stdin
```

Use an optional reviewer focus to add a matching review signal:

```bash
python -m app --reviewer-focus security changes.diff
```

The command prints JSON containing:

- `review_order`: ranked reports, highest risk first;
- `what_changed`, `why_it_might_be_risky`, and `questions_for_human`;
- `evidence`: the changed path and new-file hunk range;
- `coverage`: proof that every parsed changed file was included;
- `disclaimer`: an explicit statement that human review is required.

Malformed input returns a structured error and exit code `2`; empty input is
reported as `input_status: "empty"` rather than silently treated as a pass.

## Test

Run the single project check command:

```bash
make test
```

The check is offline and uses Python's built-in `unittest` runner. It covers
diff parsing, malformed input, traceability, safety language, and the three
fixed planted-bug evaluation fixtures.

## Docker

```bash
docker build --tag explain-my-diff .
docker run --rm explain-my-diff
```

## Deploy

Build the image in a CI or container registry, then deploy the tagged image
using the target platform's standard container deployment flow. No cloud
provider is configured in this version.

## Safety and limitations

- This is a suggested review order, not an approval or correctness decision.
- Ranking is deterministic and uses local path/content heuristics; it does not
  execute the reviewed repository or call a hosted model.
- Missing repository context can make a report low-confidence. The human
  reviewer must inspect the cited diff and decide what is acceptable.
- The initial version supports local unified diffs, not hosted pull-request
  providers.

## Evaluation fixtures

The fixed fixtures under `tests/fixtures/` contain one planted bug each:

| Fixture | Signal | Expected result |
| --- | --- | --- |
| `fixture-a.diff` | Authorization removed from an API route | Buggy route in the top two |
| `fixture-b.diff` | Inclusive boundary change in a transformation | Buggy transform in the top two |
| `fixture-c.diff` | Retry can duplicate a charge | Buggy worker in the top two |

Run `make test` to execute the complete offline evaluation.
