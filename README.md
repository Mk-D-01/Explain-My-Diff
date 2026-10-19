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

JSON is the default output format and prints:

- `review_order`: ranked reports, highest risk first;
- `what_changed`, `why_it_might_be_risky`, and `questions_for_human`;
- `evidence`: the changed path and new-file hunk range;
- `coverage`: proof that every parsed changed file was included;
- `disclaimer`: an explicit statement that human review is required.

For a reviewer-facing Markdown report, select the Markdown formatter:

```bash
python -m app --format markdown changes.diff
```

The report includes the input status, ranked review order, risk labels and
scores, change explanations, evidence, questions for a human reviewer, a
coverage summary, and the explicit non-approval disclaimer. Write the rendered
report to a file with `--output`:

```bash
python -m app --format markdown --output review-report.md changes.diff
```

`--output` replaces standard output for that invocation; JSON remains the
default when `--format` is omitted.

## Browser interface

Run the local browser interface with:

```bash
python -m app.web
```

It binds to `0.0.0.0` and listens on port `8080` by default. Set `PORT` to
choose another port, for example `PORT=9000 python -m app.web`, then open
`http://localhost:9000/`. The interface accepts a pasted unified diff and an
optional reviewer focus, and displays the same JSON triage result plus its
rendered Markdown report. Requests are handled locally; the server does not
execute reviewed code or make network calls. Request bodies are limited to 1 MiB
and malformed or missing fields receive JSON client errors.

The API endpoints are:

- `GET /health` — returns `{"status": "ok"}`;
- `POST /api/triage` — accepts `{"diff": "...", "reviewer_focus": "..."}` and
  returns the triage fields with an additional `markdown` field.

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
docker run --rm --publish 8080:8080 explain-my-diff
```

Open `http://localhost:8080/` after the container starts. Check the service
without opening the UI:

```bash
curl http://localhost:8080/health
```

Expected response:

```json
{"status": "ok"}
```

## Deploy

The repository includes a Render Blueprint in `render.yaml`. To create a live
deployment URL:

1. Push this repository to GitHub.
2. Sign in to [Render](https://render.com) and choose **New → Blueprint**.
3. Select the GitHub repository and confirm the `render.yaml` configuration.
4. Deploy the service. Render supplies the public HTTPS URL.
5. Verify `https://YOUR-SERVICE.onrender.com/health` returns `{"status":"ok"}`.
6. Open `https://YOUR-SERVICE.onrender.com/` and paste a unified diff.

The server binds to `0.0.0.0` and reads the platform-provided `PORT` value, so
it works both locally and on Render. No secrets or environment variables are
required for this version. The live URL cannot be created from this repository
without your hosting account authorization.

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

For a judge-friendly scorecard with both a readable summary and machine-readable
JSON, run:

```bash
make evaluate
```

The current target is 3/3 planted bugs ranked in the top two, with complete
changed-file coverage. The scorecard is a ranking check only; human review is
still required.
