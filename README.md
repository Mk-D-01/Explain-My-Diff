# Explain My Diff

Initial reproducible baseline for the buildathon project.

## Prerequisites

- Python 3.12.4 (see `.python-version`)
- Docker, for the container workflow

The baseline uses only the Python standard library, so dependency installation is not required yet. `requirements.lock` is kept as the dependency lockfile and is intentionally empty until runtime dependencies are added.

## Setup

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --requirement requirements.lock
```

Copy `.env.example` to `.env` when local configuration is needed. Do not commit `.env` or secrets.

## Run

```bash
python -m app
```

## Test

Run the single project check command:

```bash
make test
```

The check is offline and uses Python's built-in `unittest` runner.

## Docker

```bash
docker build --tag explain-my-diff .
docker run --rm explain-my-diff
```

## Deploy

Build the image in a CI or container registry, then deploy the tagged image using the target platform's standard container deployment flow. No cloud provider is configured in this initial baseline.

## Project status

The application behavior and first user flow are not defined yet. The next step is to choose the input/output contract for explaining a diff, then implement that smallest useful slice with tests.
