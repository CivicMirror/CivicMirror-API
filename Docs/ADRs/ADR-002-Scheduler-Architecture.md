# ADR-002: Scheduler Architecture — Cloud Scheduler over Celery Beat

## Status
Accepted

## Context

CivicMirror API requires periodic background ingestion:

| Job | Trigger | Source |
|---|---|---|
| `sync_elections` | Every 6 hours | Google Civic API |
| `poll_pending_results` | Daily 06:00 UTC | Clarity Elections (state results) |

The original plan used **Celery Beat** as the scheduler. Celery Beat is a long-running process that maintains an internal clock and fires tasks on a configured schedule.

### Why Celery Beat is incompatible with Cloud Run

Cloud Run scales containers to zero when there is no incoming traffic. Celery Beat runs as a persistent process — if the container shuts down, the Beat scheduler terminates silently and scheduled ingestion stops. Forcing `min-instances=1` to prevent scale-to-zero keeps Beat alive but incurs constant cost for what is essentially a timer.

### Reference: SeaQuacks API pattern

The companion SeaQuacks project (Node.js/Express, Cloud Run) uses an in-process `node-cron` scheduler that runs alongside the HTTP server. The principle is the same — the **scheduler is owned by the API service** — but CivicMirror externalizes the trigger to Google Cloud Scheduler, which is a fully managed, durable service that survives container restarts and scale-to-zero events.

---

## Decision

Replace Celery Beat with **Google Cloud Scheduler → protected HTTP endpoint → Celery task**.

### How it works

1. The Django API exposes internal trigger endpoints (not public):
   - `POST /internal/tasks/sync-elections/`
   - `POST /internal/tasks/poll-results/`
2. Google Cloud Scheduler fires an authenticated POST to the appropriate endpoint at the configured interval.
3. The Django view validates the caller identity, enqueues the Celery task (`.delay()`), and returns `202 Accepted` immediately.
4. Celery workers process the task asynchronously.

The enqueue step is fast (milliseconds) — Cloud Scheduler's HTTP timeout is never a concern.

---

## Endpoint Security

### Production: Cloud Scheduler OIDC (preferred)

Cloud Scheduler supports OIDC token authentication using a dedicated GCP service account. Django verifies the token in a middleware layer:

```
Cloud Scheduler
  └─ service account: civicmirror-scheduler@<project>.iam.gserviceaccount.com
  └─ role: roles/run.invoker (on the API Cloud Run service)
  └─ OIDC token → Authorization: Bearer <token>

Django middleware
  └─ Verify issuer: https://accounts.google.com
  └─ Verify audience: https://<api-cloud-run-url>/internal/tasks/*
  └─ Verify service account email claim
  └─ 401 on any mismatch; no logging of token contents
```

This approach never involves a shared secret and tokens are short-lived (1 hour max).

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

- [ ] Create GCP service account `civicmirror-scheduler@<project>.iam.gserviceaccount.com`
- [ ] Grant `roles/run.invoker` on the API Cloud Run service
- [ ] Configure Cloud Scheduler jobs with OIDC auth pointing to the service account
- [ ] Set `INTERNAL_TASK_TOKEN` in Secret Manager (local/CI only; not deployed to Cloud Run)
- [ ] Set `MIN_INSTANCES=1` on Celery worker Cloud Run service
- [ ] Configure Cloud Scheduler retry: max 1 retry, min interval 5 minutes

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
- ADR-003 (future): Celery vs. Cloud Run Jobs — worker topology final decision
- ADR-004 (future): Authentication model (public read / authenticated write)
