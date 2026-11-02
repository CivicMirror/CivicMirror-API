# CivicMirror 2.0 Reproducible Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a Python 3.13-only, non-root, independently configured CivicMirror 2.0 development and test runtime that cannot load legacy domain apps or accidentally use a legacy database or Celery queue.

**Architecture:** Keep the existing production/legacy settings intact while adding a separate `config.settings.v2` runtime and a collision-free `cm2_core` Django app namespace. Local verification runs through a dedicated Compose project with its own Postgres database, Redis databases, named volumes, API port, and task queue; CI runs the same verification script with the same dependency inputs under Python 3.13. Postgres and Redis stay private to the Compose network, while the API is published on a configurable collision-checked port for loopback and LAN access.

**Tech Stack:** Python 3.13, Django 5.2, Django REST Framework, pytest-django, Ruff, Docker Compose, PostgreSQL 16, Redis 7, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-13-civicmirror-2.0-nc-pilot-design.md`

## Global Constraints

- Python must be `>=3.13,<3.14`; host Python 3.14 and mixed user-site packages are unsupported.
- CivicMirror 2.0 code uses collision-free `cm2_*` Django app names and labels; it does not add models or migrations to legacy `elections` or `results` apps.
- The 2.0 settings module must not install any legacy CivicMirror domain, API, account, community, operations, result, aggregation, or state-integration app.
- The development database name, Docker Compose project, volumes, Redis databases, and Celery task queue must be explicitly 2.0-specific.
- Only North Carolina is enabled in the pilot settings.
- Normal verification must not require production credentials, live NCSBE access, live Civic-Data access, or pre-existing database contents.
- Existing production settings, deployment workflows, services, databases, queues, and credentials remain untouched.
- The development API defaults to `0.0.0.0:58000`, a port checked against `/data/DockerConfigs/docker-compose.yaml` and the live Docker stack on 2026-08-13. Override it with `CIVICMIRROR_V2_API_PORT` if the host allocation changes.
- Postgres and Redis have no host port mappings. The API accepts the host LAN address from `CIVICMIRROR_V2_LAN_HOST`, defaulting to the currently verified `192.168.1.102`.
- The user-owned `docs/state-research/Full Core/NC/results_pct_20260303.txt` sample remains unmodified.

---

### Task 1: Enforce the Python 3.13 Runtime Contract

**Files:**
- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `backend/config/python_version.py`
- Create: `backend/config/tests/__init__.py`
- Create: `backend/config/tests/test_python_version.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**
- Produces: `config.python_version.require_supported_python(version_info: tuple[int, int] | sys.version_info = sys.version_info) -> None`
- Raises: `UnsupportedPythonError` for every interpreter outside `>=3.13,<3.14`
- Consumed by: all Django settings imports through `config.settings.base`

- [x] **Step 1: Write the failing version-contract tests**

```python
import unittest

from config.python_version import UnsupportedPythonError, require_supported_python


class PythonVersionTests(unittest.TestCase):
    def test_python_313_is_supported(self):
        require_supported_python((3, 13))

    def test_python_312_is_rejected(self):
        with self.assertRaisesRegex(UnsupportedPythonError, ">=3.13,<3.14"):
            require_supported_python((3, 12))

    def test_python_314_is_rejected(self):
        with self.assertRaisesRegex(UnsupportedPythonError, ">=3.13,<3.14"):
            require_supported_python((3, 14))
```

- [x] **Step 2: Run the tests with the local Python 3.13 container and verify RED**

Run from the repository root:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app python:3.13-slim \
  python -m unittest config.tests.test_python_version -v
```

Expected: FAIL because `config.python_version` does not exist.

- [x] **Step 3: Implement the version guard**

```python
from __future__ import annotations

import sys
from collections.abc import Sequence


class UnsupportedPythonError(RuntimeError):
    pass


def require_supported_python(version_info: Sequence[int] = sys.version_info) -> None:
    major_minor = tuple(version_info[:2])
    if major_minor != (3, 13):
        actual = ".".join(str(part) for part in version_info[:3])
        raise UnsupportedPythonError(
            f"CivicMirror requires Python >=3.13,<3.14; detected {actual}. "
            "Use the repository Python 3.13 environment or the 2.0 development container."
        )
```

At the beginning of `config/settings/base.py`, call `require_supported_python()` before importing optional Django integrations. Add `.python-version` containing `3.13` and root package metadata:

```toml
[project]
name = "civicmirror-api"
version = "2.0.0a0"
requires-python = ">=3.13,<3.14"
dependencies = []
```

- [x] **Step 4: Run the version tests and verify GREEN**

Run the Step 2 command again.

Expected: 3 tests pass under Python 3.13.

- [x] **Step 5: Verify unsupported host Python fails clearly**

Run:

```bash
cd backend && python3 -c "import config.settings.base"
```

Expected: exit non-zero with `CivicMirror requires Python >=3.13,<3.14; detected 3.14`.

### Task 2: Add a Reusable Non-root Development Image and Isolated Compose Project

**Files:**
- Modify: `backend/Dockerfile`
- Create: `backend/.dockerignore`
- Create: `docker-compose.v2.yaml`

**Interfaces:**
- Produces: Docker target `development`
- Produces: Compose services `db`, `redis`, `api`, and `test` under project name `civicmirror-2-0`
- Produces: database `civicmirror_2_0`, queue `civicmirror_2_0`, Redis broker database 2, and Redis result database 3
- Consumed by: Task 3 tests and Task 4 canonical verification

- [x] **Step 1: Add the development target to `backend/Dockerfile`**

The target must derive from `python:3.13-slim`, install both `requirements/base.txt` and `requirements/dev.txt`, create `appuser`, run as `appuser`, expose port 8000, and default to:

```dockerfile
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

Keep the existing `runtime` target as the final production stage and do not install development requirements in it.

Add `backend/.dockerignore` entries for `.venv`, Python/test/lint caches,
`db.sqlite3`, `.env`, and `staticfiles` so neither development nor production
build contexts include host environments or generated state.

- [x] **Step 2: Create `docker-compose.v2.yaml`**

Use the following isolation contract:

```yaml
name: civicmirror-2-0

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: civicmirror_2_0
      POSTGRES_USER: civicmirror_v2
      POSTGRES_PASSWORD: civicmirror_v2
    volumes:
      - civicmirror_2_0_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U civicmirror_v2 -d civicmirror_2_0"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    volumes:
      - civicmirror_2_0_redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

  api:
    build:
      context: ./backend
      target: development
    working_dir: /app
    user: appuser
    command: python manage.py runserver 0.0.0.0:8000
    environment: &v2-environment
      DJANGO_SETTINGS_MODULE: config.settings.v2
      DJANGO_SECRET_KEY: civicmirror-v2-development-only
      DJANGO_ALLOWED_HOSTS: "localhost,127.0.0.1,${CIVICMIRROR_V2_LAN_HOST:-192.168.1.102}"
      DATABASE_URL: postgres://civicmirror_v2:civicmirror_v2@db:5432/civicmirror_2_0
      CIVICMIRROR_V2_DATABASE_NAME: civicmirror_2_0
      REDIS_URL: redis://redis:6379/2
      CELERY_BROKER_URL: redis://redis:6379/2
      CELERY_RESULT_BACKEND: redis://redis:6379/3
      CIVICMIRROR_V2_TASK_QUEUE: civicmirror_2_0
    ports:
      - "0.0.0.0:${CIVICMIRROR_V2_API_PORT:-58000}:8000"
    volumes:
      - ./backend:/app
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=2).read()"]
      interval: 5s
      timeout: 5s
      retries: 10

  test:
    build:
      context: ./backend
      target: development
    working_dir: /app
    user: appuser
    command: ./scripts/verify_v2.sh
    environment:
      <<: *v2-environment
      CIVICMIRROR_V2_TEST_DATABASE_NAME: civicmirror_2_0_test
      CELERY_TASK_ALWAYS_EAGER: "True"
    volumes:
      - ./backend:/app
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

volumes:
  civicmirror_2_0_postgres_data:
  civicmirror_2_0_redis_data:
```

- [x] **Step 3: Validate the Compose graph**

Run:

```bash
docker compose -f docker-compose.v2.yaml config --quiet
docker compose -f docker-compose.v2.yaml config --services
```

Expected: validation succeeds and lists exactly `db`, `redis`, `api`, and `test`.
The rendered configuration must publish only API port `58000` by default; database
and Redis ports must remain internal to the Compose project.

- [x] **Step 4: Build and inspect the development target**

Run:

```bash
docker build --target development -t civicmirror-2-0-development backend
docker run --rm --entrypoint sh civicmirror-2-0-development -c \
  'python --version && python -m pytest --version && test "$(id -u)" != "0"'
```

Expected: Python 3.13, pytest available, and non-root execution.

### Task 3: Create the Isolated 2.0 Django Runtime

**Files:**
- Create: `backend/cm2_core/__init__.py`
- Create: `backend/cm2_core/apps.py`
- Create: `backend/cm2_core/isolation.py`
- Create: `backend/cm2_core/views.py`
- Create: `backend/cm2_core/tests/__init__.py`
- Create: `backend/cm2_core/tests/test_foundation.py`
- Create: `backend/cm2_core/tests/test_isolation.py`
- Create: `backend/config/settings/v2.py`
- Create: `backend/config/urls_v2.py`
- Create: `backend/config/asgi_v2.py`
- Create: `backend/config/wsgi_v2.py`
- Create: `backend/config/celery_v2.py`
- Modify: `backend/config/__init__.py`
- Modify: `backend/conftest.py`

**Interfaces:**
- Produces: Django app `cm2_core` with app label `cm2_core`
- Produces: `cm2_core.isolation.require_database_name(configured: str, expected: str) -> None`
- Produces: `cm2_core.isolation.require_task_queue(configured: str, expected: str = "civicmirror_2_0") -> None`
- Produces: `GET /health/` and `GET /api/v2/health/` returning `{"status": "ok", "version": "2.0", "enabled_states": ["NC"]}` after a successful database probe
- Produces: `config.settings.v2`, `config.asgi_v2`, `config.wsgi_v2`, and `config.celery_v2`

- [x] **Step 1: Write failing isolation and runtime tests**

`test_isolation.py` must verify exact accepted names and rejection of blank, legacy, or unexpected database/queue names. `test_foundation.py` must verify:

```python
import sys

import pytest
from django.conf import settings
from django.db import connection
from django.test import Client


LEGACY_APPS = {
    "accounts", "aggregation", "api", "community", "elections", "internal",
    "ops", "results", "integrations.nc_sbe",
}


def test_runtime_uses_python_313():
    assert sys.version_info[:2] == (3, 13)


def test_v2_settings_exclude_legacy_apps():
    assert LEGACY_APPS.isdisjoint(settings.INSTALLED_APPS)
    assert "cm2_core" in settings.INSTALLED_APPS
    assert settings.CIVICMIRROR_V2_ENABLED_STATES == ("NC",)


@pytest.mark.django_db
def test_health_checks_database_and_reports_v2_runtime():
    response = Client().get("/api/v2/health/")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "version": "2.0", "enabled_states": ["NC"]
    }


@pytest.mark.django_db
def test_v2_database_has_no_legacy_domain_tables():
    tables = set(connection.introspection.table_names())
    forbidden_prefixes = ("accounts_", "aggregation_", "community_", "elections_", "ops_", "results_")
    assert not [table for table in tables if table.startswith(forbidden_prefixes)]
```

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app \
  -e DJANGO_SETTINGS_MODULE=config.settings.v2 \
  -e DATABASE_URL=sqlite:////tmp/civicmirror_2_0_test.sqlite3 \
  -e CIVICMIRROR_V2_DATABASE_NAME=/tmp/civicmirror_2_0_test.sqlite3 \
  -e CIVICMIRROR_V2_TASK_QUEUE=civicmirror_2_0 \
  civicmirror-2-0-development \
  python -m pytest cm2_core/tests -v --tb=short
```

Expected: FAIL because `cm2_core` and `config.settings.v2` do not exist.

- [x] **Step 3: Implement isolation guards and `cm2_core`**

`require_database_name` and `require_task_queue` compare non-empty values exactly and raise `django.core.exceptions.ImproperlyConfigured` with the configured and expected names on mismatch. `health` executes `SELECT 1` through `django.db.connection` before returning the fixed JSON payload.

- [x] **Step 4: Implement `config.settings.v2`**

Import shared values from `config.settings.base`, then replace `INSTALLED_APPS` with Django core apps, installed optional framework apps, DRF, and `cm2_core`. Set:

```python
ROOT_URLCONF = "config.urls_v2"
WSGI_APPLICATION = "config.wsgi_v2.application"
ASGI_APPLICATION = "config.asgi_v2.application"
CIVICMIRROR_V2_ENABLED_STATES = ("NC",)
CELERY_TASK_DEFAULT_QUEUE = env("CIVICMIRROR_V2_TASK_QUEUE", default="civicmirror_2_0")
```

Validate `DATABASES["default"]["NAME"]` against `CIVICMIRROR_V2_DATABASE_NAME` and the queue against `civicmirror_2_0`. Override DRF pagination so no setting imports the excluded legacy `api` app. Set the OpenAPI title to `CivicMirror API 2.0`, version to `2.0.0`, and prefix to `/api/v2/`.
Set `DATABASES["default"]["TEST"]["NAME"]` from
`CIVICMIRROR_V2_TEST_DATABASE_NAME`, defaulting to `civicmirror_2_0_test`, so
pytest never writes to the API development database.

- [x] **Step 5: Implement v2 entrypoints and URLs**

Both `/health/` and `/api/v2/health/` route to `cm2_core.views.health`. ASGI, WSGI, and Celery entrypoints default to `config.settings.v2`; the Celery application name is `civicmirror_2_0` and autodiscovery is limited by the v2 installed-app list. Update `config.__init__` to export the v2 Celery app only when `DJANGO_SETTINGS_MODULE=config.settings.v2`, preserving the existing Celery app for all legacy settings.

- [x] **Step 6: Keep the legacy test fixture out of the v2 app registry**

Update `backend/conftest.py` so `_clear_seeded_source_precedence` returns before importing `aggregation.models` when `aggregation` is absent from `settings.INSTALLED_APPS`. Existing legacy behavior remains unchanged when that app is installed.

- [x] **Step 7: Run the focused tests and verify GREEN**

Run the Step 2 command again.

Expected: all `cm2_core` tests pass under Python 3.13.

- [x] **Step 8: Verify the legacy settings still load under Python 3.13**

Run:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app \
  -e DJANGO_SETTINGS_MODULE=config.settings.dev \
  civicmirror-2-0-development python manage.py check
```

Expected: Django system check reports no issues.

### Task 4: Add the Canonical Verification Command and CI Gate

**Files:**
- Create: `backend/pytest-v2.ini`
- Create: `backend/scripts/verify_v2.sh`
- Create: `Makefile`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `backend/.env.example`

**Interfaces:**
- Produces: host command `make verify-v2`
- Produces: container command `./scripts/verify_v2.sh`
- Produces: CI job `v2-foundation`

- [x] **Step 1: Add the v2 pytest configuration**

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.v2
python_files = tests.py test_*.py *_tests.py
testpaths = cm2_core
addopts = -q --tb=short
```

- [x] **Step 2: Add the canonical verification script**

The executable script runs exactly this order and stops on the first failure:

```sh
#!/bin/sh
set -eu

python -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version'
python manage.py check --settings=config.settings.v2
python manage.py makemigrations --check --dry-run --settings=config.settings.v2
ruff check . --extend-exclude sqlcheck.py
python -m pytest -c pytest-v2.ini
```

`sqlcheck.py` is a repository-ignored, user-owned ad hoc database inspection
snippet. It is excluded from both the image context and local Ruff invocation;
tracked application and 2.0 files remain fully linted.

- [x] **Step 3: Add the host wrapper**

```make
.PHONY: verify-v2

verify-v2:
	docker compose -f docker-compose.v2.yaml run --rm --build test
```

- [x] **Step 4: Add the CI job**

Add a `v2-foundation` job using PostgreSQL 16, Redis 7, `actions/setup-python@v5` with Python `3.13`, and the same `requirements/base.txt` plus `requirements/dev.txt`. Set the v2 settings, base database name `civicmirror_2_0`, test database name `civicmirror_2_0_test`, Redis databases, queue, and test-only secret environment variables, then run `./scripts/verify_v2.sh` from `backend/`. Pytest creates and destroys only `civicmirror_2_0_test`.

- [x] **Step 5: Document the supported commands and environment**

Document that host Python 3.14 is unsupported, `make verify-v2` is canonical, `docker compose -f docker-compose.v2.yaml up api` starts the isolated API, and the legacy `docker-compose.dev.yaml` remains separate. Add all v2 environment names and safe development defaults to `.env.example` without adding secrets.

- [x] **Step 6: Run the canonical Compose verification**

Run:

```bash
make verify-v2
```

Expected order and result: Python assertion succeeds, Django reports no issues, no migration changes are detected, Ruff reports no errors, and all v2 tests pass.

- [x] **Step 7: Start the API and verify health**

Run:

```bash
docker compose -f docker-compose.v2.yaml up -d db redis api
curl -fsS http://127.0.0.1:58000/api/v2/health/
```

Expected:

```json
{"status":"ok","version":"2.0","enabled_states":["NC"]}
```

- [x] **Step 8: Inspect final scope without committing**

Run:

```bash
git status --short
git diff --check
```

Expected: only the 2.0 spec, this foundation plan, Phase 1 implementation files, and the pre-existing protected NC sample are present. Do not stage, commit, push, deploy, or modify production infrastructure without a separate user request.
