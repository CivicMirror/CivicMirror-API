# ADR-004: Celery Worker Topology — Cloud Run Service

## Status
Accepted

## Context

CivicMirror API uses Celery for all background ingestion tasks. The workload after Phase 5:

| Task | Trigger | Typical duration |
|---|---|---|
| `sync_elections` | Every 6 hours | 2–5 s (Civic API list call) |
| `sync_election_races` | Per election, fan-out from sync_elections | 1–15 s per election |
| `ingest_official_results` | On-demand / daily poll | 2–30 s (HTTP + DB write) |
| `poll_pending_results` | Daily 06:00 UTC | 5–60 s (fan-out) |
| `sync_openstates_legislators` | Daily, per state | 30–120 s (paginated API) |
| `sync_openstates_all_states` | Daily fan-out | seconds (queues 50 sub-tasks) |
| `sync_fec_candidates` | Per-cycle, on-demand | 60–300 s (throttled API) |

### Options considered

#### Option A — Cloud Run Jobs

Cloud Run Jobs run a container to completion for each invocation. They bill per CPU-second and have no minimum instance cost.

**Pros:** Zero cost between runs; no always-on container.  
**Cons:** 5–20 second cold start for every task invocation; unsuitable for fan-out tasks (each sub-task requires its own job invocation); cannot consume from a Redis queue; requires direct invocation or Pub/Sub trigger per task.

Cloud Run Jobs are a poor fit for a Celery architecture because Celery workers pull tasks from a queue. Jobs do not support long-lived queue polling.

#### Option B — Cloud Run Service (chosen)

A separate Cloud Run **service** runs the Celery worker as a long-lived process (`celery -A config worker`). The service:

- Keeps `min-instances=1` so the worker is always ready to pull tasks.
- Uses the same Docker image as the API service; the `CMD` is overridden via the Cloud Run service configuration to `["worker"]` (handled by `docker-entrypoint.sh`).
- Scales beyond 1 instance under high task load (Cloud Run autoscaling on CPU).

**Pros:** Matches Celery's pull-from-queue model exactly; zero cold starts for task processing; familiar operational model; one image for both services.  
**Cons:** Minimum 1 always-on instance (small, predictable cost ~$5–10/month at 256 MB).

## Decision

Run Celery workers as a **Cloud Run Service** with `min-instances=1`.

The Django API service runs in a separate Cloud Run Service with `min-instances=0` (scales to zero between requests).

### Service configuration summary

| Service | Image | CMD | min-instances | Memory |
|---|---|---|---|---|
| `civicmirror-api` | `civicmirror-api:$SHA` | `api` | 0 | 512 MB |
| `civicmirror-worker` | `civicmirror-api:$SHA` | `worker` | 1 | 512 MB |

Both services use the same Docker image tag (built once in CI, deployed to both services). The entrypoint selects the correct process based on the `CMD` argument.

### Why not separate images?

A single image ensures the API and worker always run identical code and dependencies. Version drift between API and worker is a common source of subtle bugs in distributed systems.

## Consequences

### Positive
- Task processing begins within milliseconds of enqueueing.
- Fan-out tasks (OpenStates all-states, poll_pending_results) work correctly.
- Single image tag simplifies deployment rollback.
- Worker restarts are handled automatically by Cloud Run health checks.

### Negative
- The worker service incurs a baseline ~$5–10/month cost (1 × 256 MB minimum instance).
- Worker cannot scale to zero; a runaway task loop would keep the instance alive.

## Related Decisions

- ADR-002: Scheduler Architecture (Cloud Scheduler → HTTP → Celery)
- ADR-005: VIP Email Monitoring (fast-path trigger)
