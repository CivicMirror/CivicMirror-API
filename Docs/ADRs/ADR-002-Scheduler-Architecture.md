# ADR-002: Scheduler Architecture — Cloud Scheduler over Celery Beat

## Status
Accepted — Revised 2026-05-27 to reflect live production configuration

### Revision History
- **2026-05-24 (Rev 1):** Original ADR documented two jobs and a proposed OIDC service account (`civicmirror-scheduler`). Revised to reflect actual deployment: `cloudrun-runtime` used for all services; grown to five jobs; `sync_elections` implemented as Cloud Run Job (Path B).
- **2026-05-27 (Rev 2):** Grown to eleven scheduled jobs with addition of IA SOS, CO SOS, VA ELECT, MA SOS, and SC ENR auto-discovery integrations. Updated full job registry and endpoint table.

---

## Context

CivicMirror API requires periodic background ingestion from multiple data sources. All jobs are managed by Google Cloud Scheduler in `us-central1`.

### Current Scheduled Jobs (as of 2026-05-27)

| GCP Job Name | Schedule (UTC) | Mechanism | Source / Purpose |
|---|---|---|---|
| `sync-elections-hourly` | `0 * * * *` | **Path B** — Cloud Run Job `civicmirror-sync-elections` | Google Civic API — election list sync |
| `poll-sc-enr` | `5 * * * *` | **Path A** — `POST /internal/tasks/poll-sc-enr/` | SC ENR — election discovery + URL resolution |
| `sync-sc-enr-results` | `20 * * * *` | **Path A** — `POST /internal/tasks/sync-sc-enr-results/` | SC ENR — Clarity results ingestion |
| `sync-fec` | `0 */6 * * *` | **Path A** — `POST /internal/tasks/sync-fec/` | OpenFEC API — campaign finance |
| `sync-sc-vrems` | `0 1 * * *` | **Path A** — `POST /internal/tasks/sync-sc-vrems/` | SC VREMS — candidate/race filings |
| `sync-openstates` | `0 2 * * *` | **Path A** — `POST /internal/tasks/sync-openstates/` | OpenStates API — state legislative |
| `sync-ia-sos` | `0 2 * * *` | **Path A** — `POST /internal/tasks/sync-ia-sos/` | Iowa SOS — election + race data |
| `sync-co-sos` | `0 2 * * *` | **Path A** — `POST /internal/tasks/sync-co-sos/` | Colorado SOS — election + race data |
| `sync-ma-sos` | `0 3 * * *` | **Path A** — `POST /internal/tasks/sync-ma-sos/` | Massachusetts SOS — election + race data |
| `sync-va-elect` | `30 3 * * *` | **Path A** — `POST /internal/tasks/sync-va-elections/` | Virginia ELECT — election + race data |
| `sync-ca-sos` | `0 4 * * *` | **Path A** — `POST /internal/tasks/sync-ca-sos/` | California SOS — election + race data |
| `poll-pending-results` | `0 6 * * *` | **Path A** — `POST /internal/tasks/poll-results/` | All state results adapters |

The original plan used **Celery Beat** as the scheduler. Celery Beat is a long-running process that maintains an internal clock and fires tasks on a configured schedule.

### Why Celery Beat is incompatible with Cloud Run

Cloud Run scales containers to zero when there is no incoming traffic. Celery Beat runs as a persistent process — if the container shuts down, the Beat scheduler terminates silently and scheduled ingestion stops. Forcing `min-instances=1` to prevent scale-to-zero keeps Beat alive but incurs constant cost for what is essentially a timer.

### Reference: SeaQuacks API pattern

The companion SeaQuacks project (Node.js/Express, Cloud Run) uses an in-process `node-cron` scheduler that runs alongside the HTTP server. The principle is the same — the **scheduler is owned by the API service** — but CivicMirror externalizes the trigger to Google Cloud Scheduler, which is a fully managed, durable service that survives container restarts and scale-to-zero events.

---

## Decision

Replace Celery Beat with **Google Cloud Scheduler**, using one of two trigger mechanisms depending on job characteristics:

### Path A — Cloud Scheduler → OIDC POST → Django endpoint → Celery (standard pattern)

Used by all jobs except `sync-elections-hourly`.

1. The Django API exposes internal trigger endpoints under `/internal/tasks/` (not public):

   | Endpoint | Job |
   |---|---|
   | `POST /internal/tasks/poll-sc-enr/` | SC ENR discovery (hourly :05) |
   | `POST /internal/tasks/sync-sc-enr-results/` | SC ENR results ingestion (hourly :20) |
   | `POST /internal/tasks/sync-fec/` | FEC campaign finance (six-hourly) |
   | `POST /internal/tasks/sync-sc-vrems/` | SC VREMS filings (daily 01:00) |
   | `POST /internal/tasks/sync-openstates/` | OpenStates legislative (daily 02:00) |
   | `POST /internal/tasks/sync-ia-sos/` | Iowa SOS (daily 02:00) |
   | `POST /internal/tasks/sync-co-sos/` | Colorado SOS (daily 02:00) |
   | `POST /internal/tasks/sync-ma-sos/` | Massachusetts SOS (daily 03:00) |
   | `POST /internal/tasks/sync-va-elections/` | Virginia ELECT (daily 03:30) |
   | `POST /internal/tasks/sync-ca-sos/` | California SOS (daily 04:00) |
   | `POST /internal/tasks/poll-results/` | All state results adapters (daily 06:00) |

2. Google Cloud Scheduler fires an authenticated OIDC POST to the endpoint.
3. The Django view validates the caller identity, enqueues the Celery task (`.delay()`), and returns `202 Accepted` immediately.
4. Celery workers process the task asynchronously.

### Path B — Cloud Scheduler → Cloud Run Job (batch pattern)

Used by: `sync-elections-hourly`

Cloud Scheduler triggers the `civicmirror-sync-elections` Cloud Run Job directly via the Cloud Run Jobs API. The job runs `python manage.py sync_elections`, which calls `sync_elections()` synchronously and exits. No Celery, no Redis for this job — appropriate because election list sync is fast and idempotent.

**Note:** This was the Option B evaluation path described in the original ADR. It is retained for `sync_elections` because the task completes reliably in under 2 minutes. Other jobs use Path A because they fan out work to Celery (race syncs, result polling) and benefit from async workers.

---

## Endpoint Security

### Production: Cloud Scheduler OIDC

Cloud Scheduler uses OIDC token authentication via the `cloudrun-runtime` GCP service account (shared with the API and worker Cloud Run services). Django verifies the token:

```
Cloud Scheduler
  └─ service account: cloudrun-runtime@civicmirror-2026.iam.gserviceaccount.com
  └─ role: roles/run.invoker (on the API Cloud Run service)
  └─ OIDC token → Authorization: Bearer <token>

Django middleware
  └─ Verify issuer: https://accounts.google.com
  └─ Verify audience: https://<api-cloud-run-url>/internal/tasks/*
  └─ Verify service account email claim
  └─ 401 on any mismatch; no logging of token contents
```

**Note:** The original ADR proposed a dedicated `civicmirror-scheduler` service account. The live deployment uses `cloudrun-runtime` for all services. A dedicated scheduler service account would be preferable for least-privilege but is not a blocking issue — tracked as future hardening.

### Local development: Shared secret fallback

Cloud Scheduler is not available locally. For local development and CI, use an `INTERNAL_TASK_TOKEN` environment variable as a bearer token:

```
POST /internal/tasks/sync-elections/
Authorization: Bearer <INTERNAL_TASK_TOKEN>
```

The auth middleware checks for OIDC first; if `DEBUG=True` or `INTERNAL_TASK_TOKEN` is set, it falls back to the shared secret. The shared secret path **must not** be enabled in production (`DEBUG=False` enforced in Cloud Run).

---

## Idempotency

Cloud Scheduler is at-least-once: network timeouts or transient 5xx responses can cause duplicate POSTs. The view must guard against duplicate task enqueues:

- Use a **Redis lock** keyed by `task_name:schedule_window` (e.g., `sync_elections:2026-05-18T06`).
- If the lock is held, return `202 Accepted` with `{"status": "already_running"}` — do not enqueue again.
- Store task invocation records (task name, scheduled time, Celery task ID, status) for observability.
- Configure Cloud Scheduler retry policy conservatively: max 1 retry, minimum retry interval 5 minutes.

### Lock TTL Reference

| Job | Lock key pattern | TTL |
|---|---|---|
| `sync-elections-hourly` | `task_lock:sync_elections:{YYYY-MM-DDTHH}` | 55 min |
| `poll-sc-enr` | `task_lock:poll_sc_enr:{YYYY-MM-DDTHH}` | 55 min |
| `sync-sc-enr-results` | `task_lock:sync_sc_enr_results:{YYYY-MM-DDTHH}` | 55 min |
| `sync-fec` | `task_lock:sync_fec:{YYYY-MM-DDT{00,06,12,18}}` | 6 h |
| `sync-sc-vrems` | `task_lock:sync_sc_vrems:{YYYY-MM-DD}` | 23 h |
| `sync-openstates` | `task_lock:sync_openstates:{YYYY-MM-DD}` | 23 h |
| `sync-ia-sos` | `task_lock:sync_ia_sos:{YYYY-MM-DD}` | 23 h |
| `sync-co-sos` | `task_lock:sync_co_sos:{YYYY-MM-DD}` | 23 h |
| `sync-ma-sos` | `task_lock:sync_ma_sos:{YYYY-MM-DD}` | 23 h |
| `sync-va-elect` | `task_lock:sync_va_elect:{YYYY-MM-DD}` | 23 h |
| `sync-ca-sos` | `task_lock:sync_ca_sos:{YYYY-MM-DD}` | 23 h |
| `poll-pending-results` | `task_lock:poll_pending_results:{YYYY-MM-DD}` | 23 h |

---

## Worker Topology Options

### Option A: Separate Cloud Run service (Celery workers) — Recommended for now

Run Celery workers as a separate Cloud Run service with `--min-instances=1`. The workers listen to Redis (Cloud Memorystore) and process enqueued tasks.

```
Cloud Scheduler
    │  OIDC POST
    ▼
Cloud Run: Django API  ──── Cloud SQL (Postgres)
    │  .delay()
    ▼
Cloud Memorystore (Redis broker)
    │
    ▼
Cloud Run: Celery Workers (min-instances=1)
```

Workers must bind to `$PORT` and expose a health check endpoint even if they are not HTTP-serving — use a lightweight health check process alongside the worker (e.g., `celery inspect ping`). Set `--cpu-boost` on worker startup to avoid cold-start task delays.

### Option B: Cloud Run Jobs (simpler, recommended if tasks are purely batch)

If ingestion tasks are short-lived and batch-style (finish within 60 minutes), **Cloud Run Jobs** is a better fit than a persistent worker service. Cloud Scheduler triggers a Cloud Run Job directly — no Celery, no Redis, no persistent worker process.

```
Cloud Scheduler ──► Cloud Run Job: sync_elections (runs to completion, exits)
Cloud Scheduler ──► Cloud Run Job: poll_pending_results (runs to completion, exits)
```

Evaluate Option B once the first ingestion adapters are built and their runtime characteristics are known. If tasks complete reliably in under 60 minutes, migrate workers to Cloud Run Jobs and remove Celery/Redis.

---

## Local Development Story

| Scenario | How to run |
|---|---|
| Run a task once (fast iteration) | `python manage.py sync_elections` (custom management command) |
| Run with full Celery stack | `docker compose up` — includes Redis + Celery worker + Django |
| Test the HTTP endpoint path | POST to `http://localhost:8000/internal/tasks/sync-elections/` with `Authorization: Bearer <INTERNAL_TASK_TOKEN>` |
| Simulate Cloud Scheduler retry | POST twice in quick succession; second call should return `{"status": "already_running"}` |

A `docker-compose.dev.yaml` will include: PostgreSQL, Redis, Django API, and Celery worker — matching SeaQuacks' local compose pattern.

---

## Observability

Each scheduler invocation must produce structured log entries:

- `scheduler.trigger.received` — Cloud Scheduler POST received, identity verified
- `scheduler.trigger.enqueued` — Celery task ID returned, 202 sent
- `scheduler.trigger.skipped` — lock held, duplicate suppressed
- `scheduler.trigger.auth_failed` — 401 returned; alert on repeated failures
- `task.sync_elections.started / completed / failed` — from within the Celery task

Celery task ID is returned in the 202 response body: `{"task_id": "<uuid>"}`.

---

## Deployment Checklist (Cloud Run)

- [x] Service account `cloudrun-runtime@civicmirror-2026.iam.gserviceaccount.com` used for all services
- [x] `roles/run.invoker` granted on the API Cloud Run service
- [x] All Path A Cloud Scheduler jobs configured with OIDC auth (10 jobs)
- [x] `civicmirror-sync-elections` Cloud Run Job configured (Path B)
- [x] `INTERNAL_TASK_TOKEN` in Secret Manager (local dev fallback)
- [x] `min-instances=1` on Celery worker (`civicmirror-worker`)
- [ ] Cloud Scheduler retry policy: max 1 retry, min 5-minute interval (not yet enforced — all jobs currently have unlimited retries)
- [ ] Dedicated `civicmirror-scheduler` service account (future hardening)

---

## Consequences

### Positive
- Scheduler is externally durable — Cloud Run container restarts do not lose the schedule
- OIDC auth is short-lived, keyless, and auditable via Cloud Logging
- The HTTP trigger path is testable end-to-end locally with a shared secret fallback
- Cloud Run Jobs migration path is clearly defined if Celery proves heavyweight

### Negative
- Requires GCP service account setup before first Cloud Run deployment
- Celery worker on Cloud Run needs careful `$PORT` binding and health check configuration
- Two production scheduler auth modes (OIDC + shared secret fallback) must be maintained until local dev tooling matures

---

## Related Decisions

- ADR-001: API Endpoint Structure
- ADR-003: API Authentication Model
- ADR-004: Worker Topology (Celery vs. Cloud Run Jobs)
