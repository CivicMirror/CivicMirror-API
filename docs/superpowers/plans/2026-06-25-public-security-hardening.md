# Public Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare CivicMirror API for a safe public GitHub release and a harder internet-facing deployment.

**Architecture:** Split the work into publication hygiene, application hardening, deployment hardening, and operating policy. History cleanup is handled as a release gate because it is irreversible and should be reviewed separately from ordinary code changes. Runtime changes use existing Django, DRF, Cloud Run, and gitleaks patterns already present in this repository.

**Tech Stack:** Django 5.2, Django REST Framework, drf-spectacular, django-cors-headers, Cloud Run, Cloud Scheduler OIDC, gitleaks, pytest, ruff.

## Global Constraints

- Run backend commands from `backend/`.
- Do not commit secrets, HAR captures, `.env` files, database dumps, or local scratch artifacts.
- Preserve existing public frontend behavior unless the task explicitly changes API exposure.
- Keep the current dirty worktree safe: do not stage or revert unrelated user changes.
- Prefer failing tests before code changes for Django/DRF behavior.
- For history rewrite tasks, create a backup branch and coordinate with every clone before force-pushing.

---

## Current Findings This Plan Addresses

- `gitleaks detect --source . --redact` found 21 historical findings.
- Tracked HAR files exist under `docs/state-research/**/*.har` despite `.gitignore` now blocking `*.har`.
- An untracked `docs/Secrets/` directory exists locally and contains Google client-secret material.
- `.github/workflows/deploy.yml` deploys the API with `--allow-unauthenticated --ingress=all`, while `docs/design/DEPLOYMENT.md` still describes `--no-allow-unauthenticated`.
- The API relies on a shared `X-Api-Key` guard for most read endpoints.
- Global DRF defaults are fail-open: empty authentication classes and `AllowAny` permission.
- No DRF throttling or per-view throttling is configured.
- Production settings do not enable HTTPS redirect by default, HSTS, secure cookies, or referrer policy.
- `/api/schema/` is always exposed.
- `backend/requirements/base.txt` is mostly unpinned.
- `pip-audit` could not run in the reviewed shell because the installed shim points at a missing pipx venv.

---

## File Structure

- Delete from Git: `docs/state-research/**/*.har`
  - Tracked browser captures must not be present in the public tree.
- Create: `docs/security/public-release-runbook.md`
  - Human-reviewed checklist for history cleanup, rotation, and public visibility change.
- Create: `SECURITY.md`
  - Public security contact and vulnerability reporting policy.
- Modify: `.pre-commit-config.yaml`
  - Keep gitleaks and add cheap local blockers for HAR/env/secret files.
- Modify: `backend/config/settings/base.py`
  - Add fail-closed DRF defaults and throttle rates.
- Modify: `backend/config/settings/prod.py`
  - Add production security headers/cookie settings.
- Modify: `backend/config/urls.py`
  - Make schema exposure configurable.
- Modify: `backend/accounts/views.py`
  - Add authentication throttles and tighten permission declarations.
- Modify: `backend/api/permissions.py`
  - Keep existing `HasAPIKey`; optionally add composable public/internal permission classes if needed by later tasks.
- Create: `backend/api/throttles.py`
  - Named throttle classes for auth, API key, write, and internal task endpoints.
- Modify: `backend/internal/views.py`
  - Apply throttle classes to scheduler-trigger endpoints.
- Modify: `.github/workflows/deploy.yml`
  - Align deployment exposure with the chosen model.
- Modify: `docs/design/DEPLOYMENT.md`
  - Document the real deployment model and public-release gates.
- Create: `requirements/constraints.txt` or `backend/requirements/constraints.txt`
  - Pin dependency resolution once audited.
- Modify: `backend/requirements/*.txt`
  - Adopt the constraints file without changing command ergonomics.

---

### Task 1: Remove Secret-Bearing Artifacts From the Current Tree

**Files:**
- Delete: `docs/state-research/**/*.har`
- Verify absent locally: `docs/Secrets/`
- Modify: `.gitignore`
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Consumes: current Git tree and `.gitignore`.
- Produces: a working tree that cannot add HAR/env/secret-path files accidentally.

- [ ] **Step 1: Inventory tracked HAR files**

Run:

```bash
git ls-files 'docs/state-research/**/*.har'
```

Expected: prints the tracked HAR files that must be removed from Git.

- [ ] **Step 2: Remove tracked HAR files from Git**

Run:

```bash
git rm docs/state-research/**/*.har
```

Expected: all tracked HAR files are staged for deletion. If the shell does not expand `**`, use:

```bash
git ls-files 'docs/state-research/**/*.har' | xargs -r git rm
```

- [ ] **Step 3: Ensure local secrets remain ignored**

Confirm `.gitignore` contains these exact entries:

```gitignore
docs/secrets/
docs/Secrets/

# Env files
.env

# HAR captures (may contain session cookies / tokens)
*.har
```

- [ ] **Step 4: Add local pre-commit blockers**

Modify `.pre-commit-config.yaml` to include local checks:

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
  - repo: local
    hooks:
      - id: block-har-captures
        name: Block HAR captures
        entry: HAR captures must not be committed
        language: fail
        files: '\.har$'
      - id: block-env-files
        name: Block env files
        entry: Environment files must not be committed
        language: fail
        files: '(^|/)\.env(\..*)?$'
      - id: block-secret-docs
        name: Block secret docs
        entry: docs/Secrets and docs/secrets must not be committed
        language: fail
        files: '^docs/[Ss]ecrets/'
```

- [ ] **Step 5: Verify scanner state for current tree**

Run:

```bash
gitleaks detect --source . --no-banner --redact
```

Expected: no current-tree leaks. Historical leaks may still appear until Task 2 is complete.

- [ ] **Step 6: Commit**

Run:

```bash
git add .gitignore .pre-commit-config.yaml
git add -u docs/state-research
git commit -m "chore(security): remove tracked capture artifacts"
```

Expected: commit contains only ignored-artifact removals and hook updates.

---

### Task 2: Purge Historical Leaks Before Making GitHub Public

**Files:**
- Create: `docs/security/public-release-runbook.md`
- Rewrite Git history outside normal feature branches.

**Interfaces:**
- Consumes: gitleaks fingerprints and tracked artifact list from Task 1.
- Produces: a reviewed public-release runbook and a clean history candidate.

- [ ] **Step 1: Create the runbook**

Create `docs/security/public-release-runbook.md`:

```markdown
# Public Release Security Runbook

## Release Gate

Do not make the repository public until all gates in this document pass.

## Required Cleanup

- Remove tracked HAR captures from the current tree.
- Purge historical HAR captures and old `Docs/State Research` capture paths from Git history.
- Confirm `docs/Secrets/` and `docs/secrets/` are untracked and ignored.
- Rotate every project-owned secret that may have appeared in Git history or local captures.
- Confirm `gitleaks detect --source . --redact` exits cleanly.
- Confirm a fresh clone of the release branch has no secret-bearing files.

## Known Rotation List

- `DJANGO_SECRET_KEY`
- `CIVICMIRROR_API_KEY`
- `INTERNAL_TASK_TOKEN`
- `CIVIC_API_KEY`
- `FEC_API_KEY`
- `OPENSTATES_API_KEY`
- `CIVICMIRROR_PROXY_SECRET`
- `IA_SOS_PROXY_SECRET` if still deployed
- Google OAuth client credentials from local `docs/Secrets/`
- Any GitHub Actions, GCP, Cloudflare, Firebase, or Google credentials that were copied into local docs or HAR captures

## Recommended History Rewrite

Use a fresh backup branch before rewriting:

```bash
git branch backup/pre-public-security-history
```

Use `git filter-repo` or BFG to remove these paths:

```text
docs/state-research/**/*.har
Docs/State Research/**/*.har
docs/Secrets/**
docs/secrets/**
Docs/Secrets/**
Docs/secrets/**
```

After rewriting, run:

```bash
gitleaks detect --source . --no-banner --redact
python -m pytest -v --tb=short
ruff check .
```

Force-push only after every active clone owner is warned:

```bash
git push --force-with-lease origin main
```

## Safer Alternative

If coordinated history rewrite is too disruptive, create a new public repository from a clean export:

```bash
git archive --format=tar HEAD | tar -x -C /tmp/civicmirror-public
```

Initialize a new repository from the sanitized export after scanner checks pass.
```

- [ ] **Step 2: Verify the runbook has no unresolved markers**

Run:

```bash
python -c "from pathlib import Path; text = Path('docs/security/public-release-runbook.md').read_text(); bad = ['TB' + 'D', 'TO' + 'DO', 'fill' + ' in']; found = [item for item in bad if item in text]; print(found); raise SystemExit(bool(found))"
```

Expected: no output.

- [ ] **Step 3: Commit**

Run:

```bash
git add docs/security/public-release-runbook.md
git commit -m "docs(security): add public release runbook"
```

Expected: runbook committed separately from history rewrite.

---

### Task 3: Add Public Security Policy

**Files:**
- Create: `SECURITY.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: repository visibility plan.
- Produces: public instructions for responsible disclosure.

- [ ] **Step 1: Create `SECURITY.md`**

Create:

```markdown
# Security Policy

## Reporting a Vulnerability

Please do not open a public issue for suspected vulnerabilities.

Report security concerns by email to the project maintainer or through GitHub private vulnerability reporting if it is enabled for this repository.

Include:

- Affected endpoint, file, or workflow
- Steps to reproduce
- Impact assessment
- Any logs or proof of concept needed to verify the issue

We will acknowledge reports within 5 business days and prioritize fixes based on severity and exploitability.

## Supported Versions

The public `main` branch is the only supported branch unless a release branch is explicitly documented.

## Secrets

Do not submit secrets, HAR captures, `.env` files, database dumps, service account JSON, OAuth client-secret JSON, or screenshots containing credentials.
```

- [ ] **Step 2: Link it from `README.md`**

Add this short section near the contributor or operations section:

```markdown
## Security

Report vulnerabilities using the process in [SECURITY.md](SECURITY.md). Do not open public issues with credentials, HAR captures, `.env` files, or exploit details.
```

- [ ] **Step 3: Commit**

Run:

```bash
git add SECURITY.md README.md
git commit -m "docs(security): add vulnerability reporting policy"
```

Expected: security policy discoverable at repository root.

---

### Task 4: Make DRF Defaults Fail Closed

**Files:**
- Modify: `backend/config/settings/base.py`
- Test: `backend/api/tests/test_auth.py`

**Interfaces:**
- Consumes: existing `HasAPIKey` permission class.
- Produces: default DRF protection for new views.

- [ ] **Step 1: Add failing test for default permission posture**

Add to `backend/api/tests/test_auth.py`:

```python
from django.test import override_settings
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView


def test_drf_default_permission_rejects_unconfigured_view():
    class UnconfiguredView(APIView):
        def get(self, request):
            return Response({"ok": True})

    request = APIRequestFactory().get("/unconfigured/")
    response = UnconfiguredView.as_view()(request)

    assert response.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`:

```bash
python -m pytest api/tests/test_auth.py::test_drf_default_permission_rejects_unconfigured_view -v
```

Expected before implementation: FAIL because default permissions allow the view.

- [ ] **Step 3: Change DRF defaults**

In `backend/config/settings/base.py`, replace:

```python
'DEFAULT_AUTHENTICATION_CLASSES': [],
'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
```

with:

```python
'DEFAULT_AUTHENTICATION_CLASSES': [
    'rest_framework.authentication.TokenAuthentication',
],
'DEFAULT_PERMISSION_CLASSES': [
    'api.permissions.HasAPIKey',
],
```

This keeps the existing API-key model as the default and still allows explicit `AllowAny` auth endpoints.

- [ ] **Step 4: Run focused auth tests**

Run from `backend/`:

```bash
python -m pytest api/tests/test_auth.py accounts/tests.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add backend/config/settings/base.py backend/api/tests/test_auth.py
git commit -m "fix(api): make default permissions fail closed"
```

Expected: new unconfigured DRF views require the API key by default.

---

### Task 5: Add API Throttling

**Files:**
- Create: `backend/api/throttles.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/accounts/views.py`
- Modify: `backend/community/views.py`
- Modify: `backend/internal/views.py`
- Test: `backend/api/tests/test_throttling.py`

**Interfaces:**
- Produces:
  - `AuthRateThrottle`
  - `ApiKeyRateThrottle`
  - `CommunityWriteRateThrottle`
  - `InternalTaskRateThrottle`

- [ ] **Step 1: Write throttle classes**

Create `backend/api/throttles.py`:

```python
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    scope = "auth"


class ApiKeyRateThrottle(SimpleRateThrottle):
    scope = "api_key"

    def get_cache_key(self, request, view):
        api_key = request.META.get("HTTP_X_API_KEY", "")
        if api_key:
            return self.cache_format % {"scope": self.scope, "ident": api_key[-12:]}
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class CommunityWriteRateThrottle(SimpleRateThrottle):
    scope = "community_write"

    def get_cache_key(self, request, view):
        uid = None
        if isinstance(request.auth, dict):
            uid = request.auth.get("uid")
        if request.user and request.user.is_authenticated:
            uid = f"user:{request.user.pk}"
        return self.cache_format % {"scope": self.scope, "ident": uid or self.get_ident(request)}


class InternalTaskRateThrottle(SimpleRateThrottle):
    scope = "internal_task"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
```

- [ ] **Step 2: Add failing tests**

Create `backend/api/tests/test_throttling.py`:

```python
from django.core.cache import cache
from django.test import override_settings


@override_settings(
    CIVICMIRROR_API_KEY="test-key",
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["api.permissions.HasAPIKey"],
        "DEFAULT_THROTTLE_CLASSES": ["api.throttles.ApiKeyRateThrottle"],
        "DEFAULT_THROTTLE_RATES": {"api_key": "2/minute"},
        "DEFAULT_PAGINATION_CLASS": "api.pagination.StandardPagination",
        "PAGE_SIZE": 25,
        "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
        "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    },
)
def test_api_key_throttle_limits_repeated_requests(client):
    cache.clear()
    headers = {"HTTP_X_API_KEY": "test-key"}

    assert client.get("/api/v1/elections/", **headers).status_code == 200
    assert client.get("/api/v1/elections/", **headers).status_code == 200
    assert client.get("/api/v1/elections/", **headers).status_code == 429
```

- [ ] **Step 3: Run test to verify it fails**

Run from `backend/`:

```bash
python -m pytest api/tests/test_throttling.py::test_api_key_throttle_limits_repeated_requests -v
```

Expected before settings update: FAIL because no throttle applies.

- [ ] **Step 4: Add default throttle settings**

In `backend/config/settings/base.py`, add to `REST_FRAMEWORK`:

```python
'DEFAULT_THROTTLE_CLASSES': [
    'api.throttles.ApiKeyRateThrottle',
],
'DEFAULT_THROTTLE_RATES': {
    'api_key': env('DRF_API_KEY_THROTTLE_RATE', default='120/minute'),
    'auth': env('DRF_AUTH_THROTTLE_RATE', default='10/minute'),
    'community_write': env('DRF_COMMUNITY_WRITE_THROTTLE_RATE', default='30/hour'),
    'internal_task': env('DRF_INTERNAL_TASK_THROTTLE_RATE', default='30/minute'),
},
```

- [ ] **Step 5: Apply specific throttles to auth views**

In `backend/accounts/views.py`, import:

```python
from api.throttles import AuthRateThrottle
```

Set on `RegisterView` and `LoginView`:

```python
throttle_classes = [AuthRateThrottle]
```

- [ ] **Step 6: Apply write throttles to community write views**

In `backend/community/views.py`, import:

```python
from api.throttles import CommunityWriteRateThrottle
```

Set `throttle_classes = [CommunityWriteRateThrottle]` on:

```python
PkVoteView
ExtVoteView
CommunityRaceListCreateView
CommunityRaceDetailView
UserProfileView
```

- [ ] **Step 7: Apply internal trigger throttles**

In `backend/internal/views.py`, import:

```python
from rest_framework.decorators import throttle_classes
from api.throttles import InternalTaskRateThrottle
```

Add above each internal trigger view:

```python
@throttle_classes([InternalTaskRateThrottle])
```

If DRF decorators do not apply cleanly to plain Django views, replace this step with a small Django middleware or decorator in `backend/internal/throttling.py` that uses `django.core.cache.cache.add()` keyed by client IP and path.

- [ ] **Step 8: Run focused tests**

Run from `backend/`:

```bash
python -m pytest api/tests/test_throttling.py accounts/tests.py community/tests/test_voting.py internal/tests/test_views.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add backend/api/throttles.py backend/config/settings/base.py backend/accounts/views.py backend/community/views.py backend/internal/views.py backend/api/tests/test_throttling.py
git commit -m "fix(api): add public endpoint throttling"
```

Expected: public and sensitive endpoints have rate limits.

---

### Task 6: Harden Production Django Settings

**Files:**
- Modify: `backend/config/settings/prod.py`
- Test: `backend/config/tests/test_prod_settings.py`

**Interfaces:**
- Consumes: Cloud Run proxy headers.
- Produces: secure production defaults.

- [ ] **Step 1: Create settings test**

Create `backend/config/tests/test_prod_settings.py`:

```python
import importlib


def test_prod_security_settings_are_hardened(monkeypatch):
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    prod = importlib.import_module("config.settings.prod")

    assert prod.DEBUG is False
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SECURE_HSTS_SECONDS >= 31536000
    assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
    assert prod.SECURE_HSTS_PRELOAD is True
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert prod.X_FRAME_OPTIONS == "DENY"
    assert prod.REFERRER_POLICY == "strict-origin-when-cross-origin"
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`:

```bash
python -m pytest config/tests/test_prod_settings.py -v
```

Expected before implementation: FAIL on missing or false settings.

- [ ] **Step 3: Add secure production settings**

In `backend/config/settings/prod.py`, set:

```python
SECURE_SSL_REDIRECT = env.bool('DJANGO_SECURE_SSL_REDIRECT', default=True)
SECURE_HSTS_SECONDS = env.int('DJANGO_SECURE_HSTS_SECONDS', default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = 'DENY'
REFERRER_POLICY = 'strict-origin-when-cross-origin'
```

- [ ] **Step 4: Run focused settings check**

Run from `backend/`:

```bash
python manage.py check --deploy --settings=config.settings.prod
python -m pytest config/tests/test_prod_settings.py -v
```

Expected: `pytest` passes. `manage.py check --deploy` may warn about environment-specific host/secret settings in local shell; any warning must be documented before commit.

- [ ] **Step 5: Commit**

Run:

```bash
git add backend/config/settings/prod.py backend/config/tests/test_prod_settings.py
git commit -m "fix(config): harden production security settings"
```

Expected: production defaults are secure unless explicitly relaxed.

---

### Task 7: Make API Schema Exposure Configurable

**Files:**
- Modify: `backend/config/settings/base.py`
- Modify: `backend/config/urls.py`
- Test: `backend/api/tests/test_schema_exposure.py`

**Interfaces:**
- Produces: `EXPOSE_API_SCHEMA` setting.

- [ ] **Step 1: Add failing tests**

Create `backend/api/tests/test_schema_exposure.py`:

```python
from django.test import override_settings


@override_settings(EXPOSE_API_SCHEMA=False)
def test_schema_endpoint_can_be_disabled(client):
    response = client.get("/api/schema/")

    assert response.status_code == 404


@override_settings(EXPOSE_API_SCHEMA=True)
def test_schema_endpoint_can_be_enabled(client):
    response = client.get("/api/schema/")

    assert response.status_code in {200, 401, 403}
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`:

```bash
python -m pytest api/tests/test_schema_exposure.py -v
```

Expected before implementation: disabled test fails because schema is always registered.

- [ ] **Step 3: Add setting**

In `backend/config/settings/base.py`, add:

```python
EXPOSE_API_SCHEMA = env.bool('EXPOSE_API_SCHEMA', default=False)
```

- [ ] **Step 4: Gate schema URL**

In `backend/config/urls.py`, remove `path('api/schema/', SpectacularAPIView.as_view(), name='schema')` from the base `urlpatterns` list and add:

```python
if getattr(settings, 'EXPOSE_API_SCHEMA', False):
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    ]
```

Keep Swagger UI under `settings.DEBUG`.

- [ ] **Step 5: Run focused tests**

Run from `backend/`:

```bash
python -m pytest api/tests/test_schema_exposure.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/config/settings/base.py backend/config/urls.py backend/api/tests/test_schema_exposure.py
git commit -m "fix(api): gate schema exposure"
```

Expected: schema is not exposed unless explicitly enabled.

---

### Task 8: Resolve Cloud Run Exposure Model

**Files:**
- Modify: `.github/workflows/deploy.yml`
- Modify: `docs/design/DEPLOYMENT.md`
- Optional create: `docs/adr/ADR-010-Public-API-Exposure.md`

**Interfaces:**
- Consumes: frontend architecture decision.
- Produces: one documented deployment model.

- [ ] **Step 1: Choose the deployment model**

Pick exactly one:

```text
Option A: Private API
- Cloud Run API uses --no-allow-unauthenticated.
- Frontend cannot call API directly from browser.
- Frontend uses a server-side proxy, worker, or backend-for-frontend that holds CIVICMIRROR_API_KEY.

Option B: Public API
- Cloud Run API uses --allow-unauthenticated.
- Browser-facing endpoints require per-user auth or public-safe throttling.
- X-Api-Key is treated as traffic attribution only, not a secret.
```

Recommendation for public GitHub: Option B is acceptable only after Tasks 4-7 and after replacing shared browser secrets with public-safe auth. Option A is safer if the API is still internal.

- [ ] **Step 2: Update deploy workflow**

If Option A, change `.github/workflows/deploy.yml`:

```yaml
--no-allow-unauthenticated \
--ingress=internal-and-cloud-load-balancing \
```

If Option B, keep:

```yaml
--allow-unauthenticated \
--ingress=all \
```

and add env vars:

```yaml
DRF_API_KEY_THROTTLE_RATE=120/minute
DRF_AUTH_THROTTLE_RATE=10/minute
DRF_COMMUNITY_WRITE_THROTTLE_RATE=30/hour
EXPOSE_API_SCHEMA=False
```

- [ ] **Step 3: Update deployment docs**

In `docs/design/DEPLOYMENT.md`, make the Cloud Run command match the workflow exactly. Include this note:

```markdown
The deployment model must be reviewed before making the repository public. If the API is internet-facing, `X-Api-Key` is not considered a secret when it is shipped to browser clients. Public endpoints must rely on per-user authentication, throttling, and least-privilege authorization.
```

- [ ] **Step 4: Verify workflow syntax**

Run:

```bash
rg -n -- '--allow-unauthenticated|--no-allow-unauthenticated|--ingress=' .github/workflows/deploy.yml docs/design/DEPLOYMENT.md
```

Expected: workflow and docs no longer contradict each other.

- [ ] **Step 5: Commit**

Run:

```bash
git add .github/workflows/deploy.yml docs/design/DEPLOYMENT.md
git commit -m "docs(deploy): align API exposure model"
```

Expected: deployment exposure has one documented source of truth.

---

### Task 9: Add Dependency Audit and Constraints

**Files:**
- Create: `backend/requirements/constraints.txt`
- Modify: `backend/requirements/base.txt`
- Modify: `backend/requirements/dev.txt`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: reproducible Python dependency resolution and CI vulnerability scan.

- [ ] **Step 1: Repair local audit tool or use ephemeral runner**

Run:

```bash
python3 -m pip install --user --upgrade pip-audit
python3 -m pip_audit -r backend/requirements/base.txt
```

Expected: audit command runs. If install is not allowed locally, run the same command in CI.

- [ ] **Step 2: Generate constraints**

From `backend/`, run inside a fresh virtualenv:

```bash
pip install -r requirements/base.txt -r requirements/dev.txt
pip freeze --exclude-editable > requirements/constraints.txt
```

Expected: `backend/requirements/constraints.txt` contains exact versions.

- [ ] **Step 3: Update install commands**

In `backend/requirements/dev.txt`, keep the current includes and do not duplicate constraints. In CI install steps, use:

```bash
pip install -r requirements/dev.txt -c requirements/constraints.txt
```

- [ ] **Step 4: Add CI audit step**

In `.github/workflows/ci.yml`, add after dependency install:

```yaml
- name: Audit Python dependencies
  run: python -m pip_audit -r requirements/base.txt
```

- [ ] **Step 5: Run verification**

Run from `backend/`:

```bash
python -m pip_audit -r requirements/base.txt
python -m pytest -v --tb=short
ruff check .
```

Expected: audit is clean or documented with explicit ignored CVE IDs and justification. Tests and lint pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/requirements/base.txt backend/requirements/dev.txt backend/requirements/constraints.txt .github/workflows/ci.yml
git commit -m "chore(deps): add dependency audit and constraints"
```

Expected: public repo has reproducible dependency installation and audit coverage.

---

### Task 10: Final Public Release Gate

**Files:**
- Modify: `docs/security/public-release-runbook.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: signed-off checklist before GitHub visibility change.

- [ ] **Step 1: Fresh clone verification**

Run outside the working repository:

```bash
git clone <sanitized-private-repo-url> /tmp/civicmirror-public-check
cd /tmp/civicmirror-public-check
gitleaks detect --source . --no-banner --redact
find . -iname '*.har' -o -path './docs/Secrets/*' -o -path './docs/secrets/*'
```

Expected: gitleaks clean and `find` prints no secret-bearing files.

- [ ] **Step 2: Backend verification**

Run:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt -c requirements/constraints.txt
python manage.py check --settings=config.settings.prod
python -m pytest -v --tb=short
ruff check .
```

Expected: all checks pass or only documented deploy-time warnings remain.

- [ ] **Step 3: Update runbook sign-off section**

Append to `docs/security/public-release-runbook.md`:

```markdown
## Public Release Sign-Off

- [ ] Current tree has no HAR captures, env files, or secret folders.
- [ ] Git history has been rewritten or a clean public repository has been created.
- [ ] All potentially exposed project-owned secrets have been rotated.
- [ ] `gitleaks detect --source . --redact` passes in a fresh clone.
- [ ] Production deployment exposure model is documented and matches CI.
- [ ] API throttling is enabled.
- [ ] Production security settings are enabled.
- [ ] Dependency audit passes or exceptions are documented.
- [ ] `SECURITY.md` exists and is linked from `README.md`.
```

- [ ] **Step 4: Commit**

Run:

```bash
git add docs/security/public-release-runbook.md
git commit -m "docs(security): add public release sign-off checklist"
```

Expected: public release gate is explicit and reviewable.

---

## Execution Order

1. Task 1: Remove current-tree artifacts.
2. Task 2: Create runbook and plan history rewrite.
3. Task 3: Add public security policy.
4. Task 4: Fail-close DRF defaults.
5. Task 5: Add throttling.
6. Task 6: Harden production settings.
7. Task 7: Gate API schema.
8. Task 8: Resolve deployment exposure.
9. Task 9: Add dependency audit and constraints.
10. Task 10: Fresh clone release gate.

Tasks 1-3 can be completed before any runtime behavior changes. Tasks 4-9 should be tested together before deployment. Task 10 must be done immediately before changing GitHub visibility.

## Review Notes

- The history rewrite in Task 2 is intentionally not folded into a normal code task. It can invalidate existing clones and should be coordinated.
- If the frontend currently calls the API directly from browser code with `X-Api-Key`, that key is not secret. Treat it as a traffic label until a server-side proxy or per-user auth model replaces it.
- If you choose a fresh public repository instead of history rewrite, keep the private repository as the operational source until deployment secrets and workflows are confirmed against the public repo.
