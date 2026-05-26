# CivicMirror API — Phased Build Plan

**Repo:** `tokendad/CivicMirror-API` (`/data/Projects/API-CivicMirror`)
**Companion app:** `/data/Projects/CivicMirror` (the frontend; its backend is our primary reference)
**Status:** Phase 5 complete — OpenStates, FEC, and orchestrator integrations live.

| Phase | Status | Commit |
|---|---|---|
| 1 — Project Foundation | ✅ Complete | initial scaffold |
| 2 — Google Civic API Integration | ✅ Complete | `9a87cf1` |
| 3 — REST API | ✅ Complete | `b13826b` |
| 4 — State Results Adapters | ✅ Complete | — |
| 5 — Additional Data Sources | ✅ Complete | — |
| 6 — Production Readiness | ✅ Complete (6.7 pending access) | `219a623`→ |

---

## Problem Statement

CivicMirror API is a standalone Django/Celery backend that aggregates election data from multiple public sources and serves it via a unified REST API. It is an **internal API only** — the sole consumer is the CivicMirror web app. No public API, no front-end code needed here.

The CivicMirror frontend project (`/data/Projects/CivicMirror/backend`) already has a working elections backend with elections models, a complete Civic API client, caching, mappers, and integrations for OpenStates/FEC/Congress. This plan ports and evolves that work into the dedicated API service, designed for Google Cloud Run from day one.

---

## Architecture Decisions

### What we're building
- **Monolith Django app** with separate internal apps — right-sized for a single developer, avoids microservices overhead
- **Internal REST API only** — ADR-001 endpoint structure applies; no public documentation needed
- **No user auth** — the API uses a service-to-service API key (no Knox, no user accounts)
- **Cloud Scheduler → HTTP → Celery** pattern (ADR-002 already accepted)
- **drf-spectacular** for auto-generated OpenAPI schema (used by CivicMirror frontend for SDK generation)

### Scope boundary (vs. CivicMirror frontend backend)
| Include | Exclude |
|---|---|
| Election, Race, Candidate, MeasureOption, DistrictRecord models | Community race submission |
| OfficialResult model + state adapter pattern | User accounts / Knox auth |
| CivicAPIClient (full port) | Voting app |
| Sync tasks (adapted for Cloud Scheduler) | Legal / template apps |
| OpenStates, FEC, Congress integrations | CivicMirror-specific ops views |
| Orchestrator (dedup/matching) | |
| Internal task endpoints (ADR-002) | |
| SyncLog observability model | |

### ADRs
- **ADR-001**: API endpoint structure — ✅ Accepted
- **ADR-002**: Cloud Scheduler → HTTP → Celery — ✅ Accepted
- **ADR-003**: API auth (X-Api-Key) — ✅ Written & accepted (Phase 3)
- **ADR-004**: Worker topology (Celery service vs. Cloud Run Jobs) — 🔲 Defer until Phase 4 runtime data
- **ADR-005**: VIP email monitoring — ✅ Accepted

---

## Reference Files

| File | Purpose |
|---|---|
| `Adaptors/models.py` | OfficialResult model to implement |
| `Adaptors/adapters/base.py` | StateResultsAdapter ABC + ResultRow/AdapterResult dataclasses |
| `Adaptors/adapters/registry.py` | `@register` decorator pattern |
| `Adaptors/adapters/co.py` | CO adapter stub to flesh out |
| `Adaptors/tasks.py` | ingest_official_results + _process_race_results logic |
| `Adaptors/views.py` | OfficialResultViewSet + RaceOfficialResultsAPIView |
| `/data/Projects/CivicMirror/backend/elections/models.py` | Election, Race, Candidate, MeasureOption, DistrictRecord |
| `/data/Projects/CivicMirror/backend/integrations/civic/client.py` | CivicAPIClient (full port) |
| `/data/Projects/CivicMirror/backend/integrations/civic/tasks.py` | sync_elections + sync_election_races (port + adapt) |
| `/data/Projects/CivicMirror/backend/integrations/civic/mappers.py` | map_election_payload, map_contest_to_race_defaults, etc. |
| `/data/Projects/CivicMirror/backend/integrations/civic/addresses.py` | REPRESENTATIVE_ADDRESSES |
| `/data/Projects/CivicMirror/backend/integrations/civic/cache.py` | Voter info Redis cache |
| `Docs/ADRs/ADR-001-API-Endpoint-Structure.md` | Endpoint layout |
| `Docs/ADRs/ADR-002-Scheduler-Architecture.md` | Scheduler + OIDC auth |

---

## Phase 1 — Project Foundation ✅ Complete

**Goal:** Working Django project with models, admin, migrations, and local dev environment.

### 1.1 Project Scaffold
- Create `backend/` directory structure:
  ```
  backend/
    config/
      __init__.py
      settings/
        base.py      # shared settings
        dev.py       # DEBUG=True, sqlite or local postgres
        prod.py      # Cloud Run settings
      celery.py      # Celery app init
      urls.py        # root URL conf
      wsgi.py
      asgi.py
    manage.py
    requirements/
      base.txt
      dev.txt
      prod.txt
  ```
- Base requirements: `Django>=4.2,<5.0`, `djangorestframework`, `django-environ`, `django-cors-headers`, `drf-spectacular`, `celery[redis]`, `redis`, `requests`, `gunicorn`, `whitenoise[brotli]`, `psycopg2-binary`, `django-filter`, `zipcodes`

### 1.2 Elections App
- Port `Election`, `Race`, `Candidate`, `MeasureOption`, `DistrictRecord` models from CivicMirror
- Remove `CommunityRace` proxy model (community submission is not this API's concern)
- Remove `submitter` FK and community-related fields from `Race` (clean break)
- Add `results_url` field to `Election` (needed by Clarity adapter — set manually in admin)
- Django admin for all models with sensible list_display, list_filter, search_fields
- Migrations

### 1.3 Results App
- Port `OfficialResult` model from `Adaptors/models.py`
- Port `OfficialResultViewSet` + `RaceOfficialResultsAPIView` from `Adaptors/views.py`
- Port `OfficialResultSerializer` from `Adaptors/serializers.py`
- Adapter infrastructure: `results/adapters/base.py`, `registry.py`, `__init__.py`

### 1.4 Ops App (Observability)
- Port `SyncLog` model from CivicMirror (tracks all sync job invocations: source, status, counts, errors)
- Django admin for SyncLog

### 1.5 Local Dev Environment
- `docker-compose.dev.yaml`: postgres + redis + django + celery worker
- `.env.example` with all required env vars
- `pytest.ini` + `conftest.py`
- Baseline smoke tests (settings load, models importable, DB migrations apply)

---

## Phase 2 — Google Civic API Integration ✅ Complete (`9a87cf1`)

**Goal:** Elections and races syncing from Google Civic API on a schedule.

### 2.1 Civic Client
- Port `CivicAPIClient` from CivicMirror (`integrations/civic/client.py`) — it is fully production-ready
- Port `CivicAPIError`, `CivicAPIForbidden`, `CivicAPIRetryableError` exceptions
- Location: `backend/integrations/civic/client.py`

### 2.2 Mappers & Addresses
- Port `map_election_payload`, `map_contest_to_race_defaults`, `map_candidate_defaults`, `measure_option_labels` from CivicMirror mappers
- Port `REPRESENTATIVE_ADDRESSES` dict
- Port `get_cached_voter_info`, `set_cached_voter_info`, `races_are_fresh` cache helpers

### 2.3 Sync Tasks
- Port `sync_elections` + `sync_election_races` Celery tasks from CivicMirror
- Adapt to use `SyncLog` model
- Skip VIP test election (`source_id == "2000"`)

### 2.4 Internal Task Endpoints (ADR-002)
- `POST /internal/tasks/sync-elections/` → enqueues `sync_elections.delay()`
- `POST /internal/tasks/poll-results/` → enqueues `poll_pending_results.delay()`
- Auth middleware: OIDC in prod, `INTERNAL_TASK_TOKEN` shared secret in dev/CI
- Redis idempotency lock (key: `task_name:schedule_window`)
- Returns `202 {"task_id": "<uuid>"}` or `202 {"status": "already_running"}`
- Structured log entries per ADR-002 observability spec

### 2.5 Management Commands
- `python manage.py sync_elections` — run sync task synchronously (local dev)
- `python manage.py poll_results` — run poll task synchronously

### 2.6 Tests
- Unit tests for CivicAPIClient (mock requests)
- Unit tests for mappers
- Integration test for sync_elections task (mock client)
- Test internal endpoints: valid token → 202, invalid token → 401, duplicate → already_running

---

## Phase 3 — REST API (ADR-001) ✅ Complete (`b13826b`)

**Goal:** Full read API serving CivicMirror frontend. All endpoints under `/api/v1/`.

**Delivered:**
- `GET /api/v1/elections/`, `/races/`, `/candidates/`, `/ballot-measures/`, `/districts/`, `/lookup/`
- `HasAPIKey` DRF permission (`X-Api-Key` header) on all viewsets; `GET /health/` unauthenticated
- django-filter filtersets on all resources; page-number pagination
- OpenAPI schema at `/api/schema/`; Swagger UI at `/api/docs/` (DEBUG only)
- `ADR-003-API-Auth.md` — X-Api-Key over OIDC for single-consumer internal API
- 51 tests passing (27 Phase 2 + 24 Phase 3)

### 3.1 API Key Authentication
- Write ADR-003
- `X-Api-Key` header middleware — checks against `CIVICMIRROR_API_KEY` env var
- All `/api/v1/` endpoints require the header (except health check)
- Health check: `GET /health/` → 200 (no auth required, used by Cloud Run)

### 3.2 Viewsets & Routing
Following ADR-001 hybrid flat+nested structure:
```
GET  /api/v1/elections/
GET  /api/v1/elections/{id}/
GET  /api/v1/elections/{id}/races/
GET  /api/v1/races/
GET  /api/v1/races/{id}/
GET  /api/v1/races/{id}/candidates/
GET  /api/v1/races/{id}/results/         ← from Adaptors/views.py
GET  /api/v1/candidates/
GET  /api/v1/candidates/{id}/
GET  /api/v1/ballot-measures/
GET  /api/v1/ballot-measures/{id}/
GET  /api/v1/districts/
GET  /api/v1/districts/{id}/
GET  /api/v1/lookup/?zip=&election_id=   ← ZIP-based ballot lookup
GET  /health/                            ← no auth, Cloud Run health check
```

### 3.3 Serializers
- `ElectionSerializer` (with `race_count` annotation)
- `RaceSerializer` / `RaceDetailSerializer` (with candidates + measure_options)
- `CandidateSerializer`
- `MeasureOptionSerializer`
- `OfficialResultSerializer`
- `LookupResponseSerializer` (wraps election + races for ZIP lookup)

### 3.4 Filtering & Pagination
- Port filterset_fields, search_fields, ordering_fields from CivicMirror views
- ZIP scope query (`?scope=zip&zip=12345`) — uses `zip_utils.resolve_state_from_zip`
- Cursor pagination for large collections

### 3.5 OpenAPI Schema
- `drf-spectacular` configured
- Schema at `GET /api/schema/` (internal only)
- Swagger UI at `GET /api/docs/` (dev only, disabled in prod)

### 3.6 Tests
- Test each viewset: list, retrieve, filter by state/zip/scope
- Test lookup endpoint with mock civic data
- Test auth: missing key → 403, valid key → 200

---

## Phase 4 — State Results Adapters ✅ Complete

**Goal:** Official election results ingested from Clarity Elections for CO and WV.

### 4.1 Adapter Infrastructure
- Confirm and finalize `results/adapters/base.py` (ResultRow, AdapterResult, StateResultsAdapter)
- `results/adapters/registry.py` (@register decorator)
- `results/adapters/__init__.py`

### 4.2 Clarity Elections Adapter (Generic)
- `results/adapters/clarity.py` — `ClarityAdapter` base class
  - `GET /{state}/{electionId}/current_ver.txt` → version ID
  - `GET /{state}/{electionId}/{version}/json/en/summary.json` → contest results
  - Cache version; skip re-fetch if unchanged
  - Parse `C`, `CH`, `V`, `W`, `PR/TP`, `CATKEY` fields from summary.json contests
  - Return `ResultRow` list with `UNOFFICIAL` result_type

### 4.3 State Adapters
- `results/adapters/wv.py` — `WestVirginiaAdapter(ClarityAdapter)` with `state = "WV"`
- `results/adapters/co.py` — `ColoradoAdapter(ClarityAdapter)` with `state = "CO"` (replace stub)

### 4.4 Results Tasks
- Port `ingest_official_results` + `_process_race_results` from `Adaptors/tasks.py`
- `poll_pending_results` Celery task — queries Elections where `election_date < today`, `status = RESULTS_PENDING`, `state in list_supported_states()`, fires `ingest_official_results.delay(state, pk)` for each
- Internal endpoint: `POST /internal/tasks/poll-results/` (Phase 2 stub → wire real task here)

### 4.5 Tests
- Unit tests for Clarity JSON parser (mock HTTP responses)
- Unit tests for WV + CO adapters
- Unit test for `_process_race_results` with fixture races
- Test poll_pending_results task selection logic

---

## Phase 5 — Additional Data Sources ✅ Complete

**Goal:** Enrich election data with OpenStates (state legislative) and OpenFEC (federal candidates).

### 5.1 OpenStates Integration
- `integrations/openstates/` — client, mappers, tasks
- Port from CivicMirror `integrations/openstates/` as reference
- Sync state legislators → enrich `Candidate` rows with `openstates_person_id`

### 5.2 OpenFEC Integration
- `integrations/fec/` — client, mappers, tasks
- Sync federal candidate metadata → enrich `Candidate` rows with `fec_candidate_id`
- Campaign finance summary per candidate

### 5.3 Orchestrator (Deduplication)
- `integrations/orchestrator/` — candidate_matcher, race_matcher
- Port from CivicMirror orchestrator as reference
- Deduplicate candidates appearing across multiple sources (name + district + party)
- Set `match_confidence` on Race rows

### 5.4 Source Enrichment Pipeline
- After civic sync, trigger orchestrator enrichment tasks
- Enrichment runs: civic → openstates/fec cross-reference → dedup → persist

---

## Phase 6 — Production Readiness ✅ Complete (6.7 pending VIP group access)

**Note:** ADR-003 (API auth) was completed in Phase 3. ADR-004 (worker topology) is pending Phase 4 runtime data.

**Goal:** Deploy to Google Cloud Run. CivicMirror frontend can point to new API.

### 6.1 Dockerfile
- Multi-stage build (builder → runtime)
- Port from CivicMirror's Dockerfile as reference
- Separate entrypoint for Celery workers (`CMD celery -A config worker`)

### 6.2 Write ADR-003 (Auth)
- Document API key choice, middleware implementation, Secret Manager storage
- Document how CivicMirror frontend sets the header

### 6.3 Write ADR-004 (Worker Topology)
- Evaluate Celery service vs. Cloud Run Jobs based on Phase 4 adapter runtimes
- Document decision with measured task durations

### 6.4 Cloud Run Configuration
- Django API service: `min-instances=0`, `DJANGO_SETTINGS_MODULE=config.settings.prod`
- Celery worker service: `min-instances=1`, `--cpu-boost`
- Cloud SQL (PostgreSQL) via Cloud SQL Auth Proxy sidecar
- Cloud Memorystore (Redis) for Celery broker
- Secret Manager entries: `CIVIC_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `CIVICMIRROR_API_KEY`, `SECRET_KEY`

### 6.5 Cloud Scheduler Jobs
- `sync-elections`: POST to `/internal/tasks/sync-elections/` every 6 hours, OIDC auth
- `poll-results`: POST to `/internal/tasks/poll-results/` daily 06:00 UTC, OIDC auth
- GCP service account: `civicmirror-scheduler@<project>.iam.gserviceaccount.com`
- Grant `roles/run.invoker` on API Cloud Run service

### 6.6 CI/CD
- GitHub Actions workflow: lint → test → build Docker → push to Artifact Registry → deploy to Cloud Run
- Separate jobs for API service and Celery worker

### 6.7 VIP Email Monitoring (Fast-Path Sync Trigger)

**Decision:** ADR-005 (Accepted). Supplements — does not replace — scheduled polling.

**How it works:** Subscribe `civicmirror-vip@gmail.com` to the VIP Community Google Group (`groups.google.com/g/vip-community`). The Gmail API pushes new message notifications to a Cloud Pub/Sub topic, which triggers `POST /internal/tasks/sync-from-email/`. The endpoint parses the EID from the email body (`EID\s+(\d+)`) and immediately enqueues `sync_election_races.delay(eid)`.

**Why:** VIP community emails are posted when election data goes live in the Civic API. This reduces detection latency from up to 6 hours (scheduled poll) to ~2–10 minutes.

**Implementation tasks:**
- Create dedicated Gmail account; subscribe to `vip-community@googlegroups.com`
- Create Cloud Pub/Sub topic `civicmirror-vip-email` and push subscription
- Implement `SyncFromEmailView` at `POST /internal/tasks/sync-from-email/` (ADR-002 auth)
- Implement `extract_eid_from_gmail_message()` parser with `re.compile(r"\bEID\s+(\d+)\b")`
- Store `GMAIL_SERVICE_ACCOUNT_JSON` + `VIP_GMAIL_WATCH_TOPIC` + `GMAIL_WATCH_USER_ID` in Secret Manager
- Cloud Scheduler job: `POST /internal/tasks/renew-gmail-watch/` daily at 00:00 UTC (watch expires every 7 days)
- Add to CI/CD: alert if no EIDs extracted over a rolling 14-day window (catches format changes)

**Env vars added:**
```
GMAIL_SERVICE_ACCOUNT_JSON   # Secret Manager
VIP_GMAIL_WATCH_TOPIC        # projects/{project}/topics/civicmirror-vip-email
GMAIL_WATCH_USER_ID          # civicmirror-vip@gmail.com
```

See `Docs/ADRs/ADR-005-VIP-Email-Monitoring.md` for full architecture, parser code, and risk mitigation.

---

## Phased Delivery Summary

| Phase | Deliverable | Unblocks |
|---|---|---|
| 1 | Django scaffold + models + local dev | Everything |
| 2 | Civic sync + internal endpoints | Phase 3 (live data for API) |
| 3 | REST API + auth | CivicMirror frontend integration |
| 4 | Clarity adapters + results | Official result display |
| 5 | OpenStates + FEC + orchestrator | Candidate enrichment |
| 6 | Docker + Cloud Run + CI/CD + VIP email fast-path | Production launch |

**Minimum viable integration point:** After Phase 3, the CivicMirror frontend can switch from its embedded backend to this API.

---

## Notes

- The `Adaptors/` folder is **reference-only** — do not modify any files in it.
- Community race submission lives in the CivicMirror frontend, not here.
- `Race.source` should include `CIVIC_API`, `OPENELECTIONS`, `MEDSL` choices; remove `COMMUNITY` from this project's model.
- The `source_id` uniqueness constraint on `Election` is critical for idempotent sync.
- `results_url` on `Election` is set **manually in Django admin** for Clarity states — no auto-discovery.
