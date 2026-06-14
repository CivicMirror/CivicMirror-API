# Repository Guidelines

## Project Structure & Module Organization

This repository is the CivicMirror Django/Celery API. The main application lives in `backend/`: `config/` holds settings, routing, Celery, ASGI/WSGI; domain apps such as `accounts/`, `api/`, `aggregation/`, `community/`, `internal/`, and `results/` hold models, serializers, views, tasks, adapters, migrations, and tests. `backend/results/adapters/` contains state/source result integrations. `Adaptors/` is an older adapter module; avoid expanding it unless existing code requires it. Documentation, ADRs, API specs, and state research live under `docs/`. Cloudflare worker code is under `cloudflare/`.

## Build, Test, and Development Commands

Run backend commands from `backend/`.

- `python -m venv .venv && source .venv/bin/activate`: create and activate a local environment.
- `pip install -r requirements/base.txt -r requirements/dev.txt`: install runtime and development dependencies.
- `cp .env.example .env`: create local configuration, then fill any required secrets.
- `docker compose -f ../docker-compose.dev.yaml up -d`: start local Postgres and Redis.
- `python manage.py migrate`: apply database migrations.
- `python manage.py runserver`: run the API locally.
- `python -m pytest -v --tb=short`: run the test suite.
- `ruff check .`: run lint checks used by CI.
- `python manage.py check`: run Django system checks.

## Coding Style & Naming Conventions

Use Python 3.13-compatible Django code. Ruff is configured in `backend/ruff.toml` with a 120-character line length and rules `E`, `F`, `W`, and import sorting (`I`). Keep imports ordered, avoid unused imports outside allowed `__init__.py` re-exports, and do not lint generated migrations. Use `snake_case` for functions, variables, tasks, and modules; `PascalCase` for models, serializers, views, and adapter classes.

## Testing Guidelines

Tests use `pytest` and `pytest-django` with `DJANGO_SETTINGS_MODULE=config.settings.dev`. Name test files `test_*.py`, `*_tests.py`, or `tests.py`. Place app-specific tests next to the app, for example `backend/results/tests/test_ca_adapter.py` or `backend/api/tests/test_views.py`. Add focused tests for model constraints, serializers, API behavior, tasks, and adapter normalization when changing those areas.

## Commit & Pull Request Guidelines

History generally follows Conventional Commit style, for example `fix(results): enforce OfficialResult natural-key uniqueness` and `docs(design): add race name normalization ADR`. Prefer `fix(scope): ...`, `feat(scope): ...`, `docs(scope): ...`, or `test(scope): ...`. Pull requests should include a short summary, linked issue or design doc, migration notes, configuration changes, and test output. Include screenshots only for user-visible API docs or frontend-adjacent changes.

## Security & Configuration Tips

Never commit secrets. `.pre-commit-config.yaml` runs `gitleaks`; install hooks with `pre-commit install`. Use environment variables for API keys and tokens, matching `backend/.env.example`. Production deploys use Cloud Run, Cloud SQL, Redis, and GitHub Actions secrets.
