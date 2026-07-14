# CivicMirror Local Hosting Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move CivicMirror off Google Cloud services and run the API, frontend, database, Redis, workers, and scheduled ingestion locally on this machine with a reversible cutover.

**Architecture:** Use Docker Compose as the local production runtime, with one shared Postgres service, one Redis service, the `CivicMirror-API` Django API, a Celery worker, a lightweight local scheduler, and the `CivicMirror-FrontEnd/frontend` nginx-served Vite build. Keep the API's existing `X-Api-Key` contract and replace GCP-only dependencies with local environment files, volumes, cron/scheduler triggers, and optional Cloudflare/DNS routing.

**Tech Stack:** Docker Compose, Django 5.2, Gunicorn, Celery, Redis 7, PostgreSQL 16, React 18, Vite, nginx, local cron/scheduler container, optional Cloudflare DNS/proxy.

## Global Constraints

- Planning stage only until the user explicitly approves implementation.
- Preserve current cloud services until local browser-level verification succeeds.
- Do not delete or disable GCP resources in implementation tasks without a separate explicit user approval at the cutover gate.
- Preserve the `X-Api-Key` contract between `CivicMirror-FrontEnd/frontend/src/api/civicApiClient.ts` and `CivicMirror-API/backend/api/permissions.py`.
- Treat `CivicMirror-API` as the election aggregation API consumed by the frontend via `VITE_CIVIC_API_URL`.
- Reconcile the older backend inside `CivicMirror-FrontEnd/backend` before deciding whether it is still part of production.
- Use local persistent volumes or bind mounts for Postgres and Redis; no ephemeral database for production-local hosting.
- Keep all real secrets out of git. Use local `.env` files under `/data/DockerConfigs` or another ignored private location.
- For LAN testing from another device, do not build the frontend with `localhost` API URLs; browser-side `localhost` points at the viewer's device, not this server.
- Public-domain cutover requires HTTPS termination, firewall rules, and either a reverse proxy or Cloudflare Tunnel before DNS moves.

---

## Current Repo Map

- `CivicMirror-API/backend/Dockerfile`: existing production API image; runs `docker-entrypoint.sh api` by default.
- `CivicMirror-API/backend/docker-entrypoint.sh`: supports `api`, `worker`, `migrate`, and arbitrary commands.
- `CivicMirror-API/docker-compose.dev.yaml`: currently starts only Postgres and Redis for development.
- `CivicMirror-API/backend/.env.example`: authoritative API env list for local secrets and provider keys.
- `CivicMirror-API/docs/adr/ADR-002-Scheduler-Architecture.md`: current Cloud Scheduler and Cloud Run Job design; must be replaced or amended for local scheduling.
- `CivicMirror-API/docs/adr/ADR-003-API-Auth.md`: API key contract shared with the frontend.
- `CivicMirror-FrontEnd/frontend/Dockerfile`: nginx-served Vite image; currently defaults build args to cloud URLs.
- `CivicMirror-FrontEnd/frontend/.env.example`: frontend API URL and API-key inputs.
- `CivicMirror-FrontEnd/frontend/src/api/civicApiClient.ts`: consumes `VITE_CIVIC_API_URL` and sends `X-Api-Key`.
- `CivicMirror-FrontEnd/.github/workflows/deploy.yml`: current Cloud Run deploy for frontend.
- `CivicMirror-FrontEnd/terraform/*.tf`: current Cloud Run, Cloud Scheduler, Cloud SQL, Cloudflare, and related GCP infrastructure.
- `CivicMirror-FrontEnd/docker-compose.yml`: older local full-stack compose with backend, celery, and celery beat; review before reuse because it points at `CivicMirror-FrontEnd/backend`, not `CivicMirror-API`.

## Migration Phases

### Task 1: Inventory Live Cloud And Local Runtime Contracts

**Files:**
- Read: `CivicMirror-API/.github/workflows/deploy.yml`
- Read: `CivicMirror-API/docs/design/DEPLOYMENT.md`
- Read: `CivicMirror-API/docs/adr/ADR-002-Scheduler-Architecture.md`
- Read: `CivicMirror-FrontEnd/.github/workflows/deploy.yml`
- Read: `CivicMirror-FrontEnd/terraform/cloud_run.tf`
- Create: `CivicMirror-API/docs/ops/local-migration-inventory.md`

**Interfaces:**
- Consumes: Current GCP service names, current env var names, current scheduler job list.
- Produces: A checked inventory used by all later implementation tasks.

- [ ] **Step 1: Capture live GCP state without changing anything**

Run:
```bash
gcloud run services list --project=civicmirror-2026 --region=us-central1
gcloud run jobs list --project=civicmirror-2026 --region=us-central1
gcloud scheduler jobs list --project=civicmirror-2026 --location=us-central1
gcloud sql instances list --project=civicmirror-2026
gcloud redis instances list --project=civicmirror-2026 --region=us-central1
gcloud secrets list --project=civicmirror-2026
```

Expected: output confirms the active frontend, API, worker, job, database, Redis, and secret names that must be replaced locally.

- [ ] **Step 1a: Capture effective Cloud Run traffic, revision, image, and env bindings**

For every Cloud Run service returned by Step 1, run:
```bash
service="civicmirror-frontend"
gcloud run services describe "$service" \
  --project=civicmirror-2026 \
  --region=us-central1 \
  --format='yaml(metadata.name,status.url,status.traffic,spec.template.spec.containers[].image,spec.template.spec.containers[].env)'
```

Repeat with `service="civicmirror-api"`, `service="civicmirror-worker"`, and any legacy or unexpected service such as `civicmirror-backend`.

Expected: the inventory records the active traffic split, serving revision, container image digest or tag, and every env var or Secret Manager binding. This prevents the known failure mode where a deploy succeeds but traffic remains pinned to an older frontend bundle/API-key revision.

- [ ] **Step 1b: Capture scheduler, job, database, Redis, and secret details**

For every scheduler job and Cloud Run job returned by Step 1, run:
```bash
gcloud scheduler jobs describe sync-elections-hourly \
  --project=civicmirror-2026 \
  --location=us-central1 \
  --format='yaml(name,schedule,timeZone,state,httpTarget.uri,httpTarget.oidcToken.serviceAccountEmail)'

gcloud run jobs describe civicmirror-migrate \
  --project=civicmirror-2026 \
  --region=us-central1 \
  --format='yaml(metadata.name,spec.template.template.spec.template.spec.containers[].image,spec.template.template.spec.template.spec.containers[].args,spec.template.template.spec.template.spec.containers[].env)'
```

Then capture backing service configuration:
```bash
gcloud sql instances describe civicmirror-db \
  --project=civicmirror-2026 \
  --format='yaml(name,databaseVersion,region,settings.tier,settings.backupConfiguration.enabled,connectionName)'

gcloud redis instances describe civicmirror-redis \
  --project=civicmirror-2026 \
  --region=us-central1 \
  --format='yaml(name,tier,memorySizeGb,host,port,redisVersion)'

gcloud secrets versions list CIVICMIRROR_API_KEY --project=civicmirror-2026
gcloud secrets versions list DATABASE_URL --project=civicmirror-2026
gcloud secrets versions list REDIS_URL --project=civicmirror-2026
```

Expected: the inventory records schedules, target URLs, auth service accounts, job args, database version/connection name, Redis shape, and active secret version numbers without printing secret values.

- [ ] **Step 2: Write the inventory document**

Create `CivicMirror-API/docs/ops/local-migration-inventory.md` with this structure:
```markdown
# CivicMirror Local Migration Inventory

## Cloud Resources To Replace

> **Names below are expected values, not verified ones.** Replace every
> "Current name" cell with the actual names from the Step 1 `gcloud ... list`
> output before marking any row `inventoried`. Known discrepancy: the API repo
> workflow deploys `civicmirror-api`/`civicmirror-worker`, but
> `CivicMirror-FrontEnd/terraform/cloud_run.tf` deploys the backend as
> `civicmirror-backend`. Both may be live; every live service must get a row
> here or it will survive the Task 8 shutdown and keep billing.

| Cloud resource | Current name | Local replacement | Migration status |
|---|---|---|---|
| Frontend Cloud Run service | civicmirror-frontend | Docker Compose service `civicmirror-frontend` | planned |
| API Cloud Run service | civicmirror-api | Docker Compose service `civicmirror-api` | planned |
| Legacy backend Cloud Run service | civicmirror-backend (verify if live) | none — superseded by `civicmirror-api`, or reconciled per Task 1 Step 3 | planned |
| Worker Cloud Run service | civicmirror-worker | Docker Compose service `civicmirror-worker` | planned |
| Migration Cloud Run job | civicmirror-migrate | `docker compose run --rm civicmirror-api migrate` | planned |
| Sync elections Cloud Run job | civicmirror-sync-elections | local scheduler POST or management command | planned |
| Cloud SQL Postgres | civicmirror-db | Docker Compose service `civicmirror-postgres` | planned |
| Memorystore Redis | civicmirror-redis | Docker Compose service `civicmirror-redis` | planned |
| Cloud Scheduler jobs | see scheduler table | Docker Compose service `civicmirror-scheduler` | planned |
| Artifact Registry images | civicmirror-images | local Docker builds | planned |
| Secret Manager entries | see secret table | `/data/DockerConfigs/CivicMirror/.env` | planned |

## Cloud Run Effective Runtime

| Service | URL | Serving revision(s) + traffic | Image | Env/secret bindings | Notes |
|---|---|---|---|---|---|
| civicmirror-frontend | Current URL from describe | revision=percent | image digest/tag | VITE_* build inputs or runtime env if present | planned |
| civicmirror-api | Current URL from describe | revision=percent | image digest/tag | DATABASE_URL, REDIS_URL, CIVICMIRROR_API_KEY, provider keys | planned |
| civicmirror-worker | Current URL from describe | revision=percent | image digest/tag | DATABASE_URL, REDIS_URL, CELERY_*, provider keys | planned |
| civicmirror-backend | Record `not found` or current URL from describe | revision=percent or `not live` | image digest/tag or `none` | env bindings or `none` | record whether this legacy service must be deleted |

## Secret Bindings

| Secret | Active version(s) | Bound service/job | Local env replacement | Verified |
|---|---|---|---|---|
| CIVICMIRROR_API_KEY | version from `gcloud secrets versions list` | frontend build + API | `CIVICMIRROR_API_KEY` and `VITE_CIVIC_API_KEY` | no |
| DATABASE_URL | version from `gcloud secrets versions list` | API, worker, migrate job | local Postgres `DATABASE_URL` | no |
| REDIS_URL | version from `gcloud secrets versions list` | API, worker | local Redis URLs | no |

## Scheduler Jobs

| Job | Schedule UTC | Local trigger |
|---|---:|---|
| sync-elections-hourly | 0 * * * * | POST `/internal/tasks/sync-elections/` |
| poll-sc-enr | 5 * * * * | POST `/internal/tasks/poll-sc-enr/` |
| sync-sc-enr-results | 20 * * * * | POST `/internal/tasks/sync-sc-enr-results/` |
| sync-fec | 0 */6 * * * | POST `/internal/tasks/sync-fec/` |
| sync-sc-vrems | 0 1 * * * | POST `/internal/tasks/sync-sc-vrems/` |
| sync-openstates | 0 2 * * * | POST `/internal/tasks/sync-openstates/` |
| sync-ia-sos | 0 2 * * * | POST `/internal/tasks/sync-ia-sos/` |
| sync-co-sos | 0 2 * * * | POST `/internal/tasks/sync-co-sos/` |
| sync-ma-sos | 0 3 * * * | POST `/internal/tasks/sync-ma-sos/` |
| sync-va-elect | 30 3 * * * | POST `/internal/tasks/sync-va-elections/` |
| sync-ca-sos | 0 4 * * * | POST `/internal/tasks/sync-ca-sos/` |
| sync-wa-votewa | 0 3 * * * | POST `/internal/tasks/sync-wa-votewa/` |
| sync-fl-ew | 0 4 * * * | POST `/internal/tasks/sync-fl-ew/` |
| sync-tx-goelect | 0 5 * * * | POST `/internal/tasks/sync-tx-goelect/` |
| sync-oh-sos | 30 4 * * * | POST `/internal/tasks/sync-oh-sos/` |
| poll-pending-results | 0 6 * * * | POST `/internal/tasks/poll-results/` |

## Cutover Gate

Do not disable or delete GCP resources until local frontend, local API health, local scheduled trigger auth, migrated data, and at least one manual ingestion/result check are verified.
```

- [ ] **Step 3: Review ambiguous backend ownership**

Run:
```bash
diff -qr /data/Projects/CivicMirror/CivicMirror-API/backend /data/Projects/CivicMirror/CivicMirror-FrontEnd/backend | head -100
```

Expected: differences confirm whether `CivicMirror-FrontEnd/backend` is legacy or still needed. Record the conclusion in the inventory before implementing compose changes.

- [ ] **Step 4: Commit the inventory**

Run:
```bash
git -C /data/Projects/CivicMirror/CivicMirror-API add docs/ops/local-migration-inventory.md
git -C /data/Projects/CivicMirror/CivicMirror-API commit -m "docs: inventory civicmirror local migration"
```

### Task 2: Add A Local Production Compose Stack

**Files:**
- Create: `/data/DockerConfigs/CivicMirror/docker-compose.yml`
- Create: `/data/DockerConfigs/CivicMirror/.env`
- Create: `/data/DockerConfigs/CivicMirror/.env.example`
- Modify: `/data/DockerConfigs/docker-compose.yaml` only if this machine's main stack should own CivicMirror.

**Interfaces:**
- Consumes: Dockerfiles from `CivicMirror-API/backend` and `CivicMirror-FrontEnd/frontend`.
- Produces: Local services named `civicmirror-postgres`, `civicmirror-redis`, `civicmirror-api`, `civicmirror-worker`, `civicmirror-scheduler`, and `civicmirror-frontend`.

- [ ] **Step 1: Create the private env file**

Create `/data/DockerConfigs/CivicMirror/.env` outside git:
```dotenv
POSTGRES_DB=civicmirror_api
POSTGRES_USER=civicmirror
POSTGRES_PASSWORD=replace-with-local-postgres-password

DJANGO_SECRET_KEY=replace-with-local-django-secret
DJANGO_DEBUG=False
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,api.civicmirror.local,api.civicmirror.app
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8089,http://localhost:8090,https://civicmirror.app,https://api.civicmirror.app
CORS_ALLOWED_ORIGINS=http://localhost:8089,https://civicmirror.app
FRONTEND_BASE_URL=http://localhost:8089
DATABASE_URL=postgres://civicmirror:replace-with-local-postgres-password@civicmirror-postgres:5432/civicmirror_api
REDIS_URL=redis://civicmirror-redis:6379/0
CELERY_BROKER_URL=redis://civicmirror-redis:6379/0
CELERY_RESULT_BACKEND=redis://civicmirror-redis:6379/1
CELERY_TASK_ALWAYS_EAGER=False
GUNICORN_WORKERS=2
GUNICORN_TIMEOUT=300
INTERNAL_TASK_TOKEN=replace-with-local-internal-task-token
CIVICMIRROR_API_KEY=replace-with-local-api-key-shared-with-frontend

# Firebase/community auth:
# Option A, keep Firebase auth enabled and mount a local service-account JSON
# at /run/secrets/firebase-service-account.json using the compose volume shown below.
# Option B, set FIREBASE_AUTH_ENABLED=False only if local production does not need
# account/community flows during the migration window.
FIREBASE_AUTH_ENABLED=True
FIREBASE_CREDENTIALS_FILE=/run/secrets/firebase-service-account.json

CIVIC_API_KEY=
FEC_API_KEY=
OPENSTATES_API_KEY=
GITHUB_TOKEN=

CIVICMIRROR_PROXY_URL=
CIVICMIRROR_PROXY_SECRET=
IA_SOS_PROXY_URL=
IA_SOS_PROXY_SECRET=
CF_SOLVER_URL=
CF_SOLVER_SECRET=

# Same-host smoke-test defaults. Before LAN or public use, replace these with
# the selected origin from Task 6 and rebuild `civicmirror-frontend`.
VITE_API_URL=http://localhost:8090
VITE_API_BASE_URL=http://localhost:8090
VITE_CIVIC_API_URL=http://localhost:8090
VITE_CIVIC_API_KEY=replace-with-local-api-key-shared-with-frontend
```

- [ ] **Step 2: Create the compose file**

Create `/data/DockerConfigs/CivicMirror/docker-compose.yml`:
```yaml
services:
  civicmirror-postgres:
    image: postgres:16-alpine
    container_name: civicmirror-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - civicmirror_postgres_data:/var/lib/postgresql/data
      - ./backups:/backups
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 10

  civicmirror-redis:
    image: redis:7-alpine
    container_name: civicmirror-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - civicmirror_redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 10

  civicmirror-api:
    build:
      context: /data/Projects/CivicMirror/CivicMirror-API/backend
    container_name: civicmirror-api
    restart: unless-stopped
    env_file: .env
    command: ["api"]
    volumes:
      - ./secrets/firebase-service-account.json:/run/secrets/firebase-service-account.json:ro
    ports:
      - "8090:8080"
    depends_on:
      civicmirror-postgres:
        condition: service_healthy
      civicmirror-redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/', timeout=5)\""]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 40s

  civicmirror-worker:
    build:
      context: /data/Projects/CivicMirror/CivicMirror-API/backend
    container_name: civicmirror-worker
    restart: unless-stopped
    env_file: .env
    command: ["worker"]
    volumes:
      - ./secrets/firebase-service-account.json:/run/secrets/firebase-service-account.json:ro
    depends_on:
      civicmirror-api:
        condition: service_healthy

  civicmirror-scheduler:
    image: alpine:3.20
    container_name: civicmirror-scheduler
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./scheduler/crontab:/etc/crontabs/root:ro
      - ./scheduler/trigger.sh:/usr/local/bin/trigger.sh:ro
    command: ["sh", "-c", "apk add --no-cache curl && crond -f -l 8"]
    depends_on:
      civicmirror-api:
        condition: service_healthy

  civicmirror-frontend:
    build:
      context: /data/Projects/CivicMirror/CivicMirror-FrontEnd/frontend
      args:
        VITE_API_URL: ${VITE_API_URL}
        VITE_CIVIC_API_URL: ${VITE_CIVIC_API_URL}
        VITE_CIVIC_API_KEY: ${VITE_CIVIC_API_KEY}
    container_name: civicmirror-frontend
    restart: unless-stopped
    ports:
      - "8089:8080"
    depends_on:
      civicmirror-api:
        condition: service_healthy

volumes:
  civicmirror_postgres_data:
  civicmirror_redis_data:
```

- [ ] **Step 3: Validate compose syntax**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml config
```

Expected: Compose renders without unresolved variables.

- [ ] **Step 3a: Validate private files exist and are not tracked**

Run:
```bash
test -f /data/DockerConfigs/CivicMirror/.env
if grep -q '^FIREBASE_AUTH_ENABLED=False' /data/DockerConfigs/CivicMirror/.env; then
  echo "Firebase disabled for local production; confirm this is recorded in docs/ops/local-migration-inventory.md"
else
  test -f /data/DockerConfigs/CivicMirror/secrets/firebase-service-account.json
fi
if git -C /data/DockerConfigs rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C /data/DockerConfigs status --short -- CivicMirror/.env CivicMirror/secrets/firebase-service-account.json
fi
```

Expected: required private files exist, or Firebase is intentionally disabled and recorded in `docs/ops/local-migration-inventory.md`; the `git status --short -- ...` command prints no tracked secret changes if `/data/DockerConfigs` is a git repo. If Firebase is intentionally disabled, set `FIREBASE_AUTH_ENABLED=False`, remove the two Firebase volume mounts from compose, and record that choice in `docs/ops/local-migration-inventory.md`.

- [ ] **Step 4: Commit only repo-owned docs if any were added**

Do not commit `/data/DockerConfigs/CivicMirror/.env`. If `/data/DockerConfigs` is tracked separately, commit only `.env.example`, compose, and scheduler scripts after secrets are removed.

### Task 3: Replace Cloud Scheduler With Local Scheduler Scripts

**Files:**
- Create: `/data/DockerConfigs/CivicMirror/scheduler/trigger.sh`
- Create: `/data/DockerConfigs/CivicMirror/scheduler/crontab`
- Modify: `CivicMirror-API/docs/adr/ADR-002-Scheduler-Architecture.md`

**Interfaces:**
- Consumes: `INTERNAL_TASK_TOKEN`, internal API trigger URLs from `CivicMirror-API/backend/internal/urls.py`.
- Produces: Local recurring task triggers with the same auth path as local development.

- [ ] **Step 1: Create the trigger script**

Create `/data/DockerConfigs/CivicMirror/scheduler/trigger.sh`:
```sh
#!/bin/sh
set -eu

path="$1"

if [ -z "${INTERNAL_TASK_TOKEN:-}" ]; then
  echo "INTERNAL_TASK_TOKEN is required" >&2
  exit 1
fi

curl -fsS \
  -X POST \
  -H "Authorization: Bearer ${INTERNAL_TASK_TOKEN}" \
  "http://civicmirror-api:8080${path}"
```

Then run:
```bash
chmod +x /data/DockerConfigs/CivicMirror/scheduler/trigger.sh
```

- [ ] **Step 2: Create the crontab**

Create `/data/DockerConfigs/CivicMirror/scheduler/crontab`:
```cron
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

0 * * * * /usr/local/bin/trigger.sh /internal/tasks/sync-elections/
5 * * * * /usr/local/bin/trigger.sh /internal/tasks/poll-sc-enr/
20 * * * * /usr/local/bin/trigger.sh /internal/tasks/sync-sc-enr-results/
0 */6 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-fec/
0 1 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-sc-vrems/
0 2 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-openstates/
0 2 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-ia-sos/
0 2 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-co-sos/
0 3 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-ma-sos/
0 3 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-wa-votewa/
30 3 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-va-elections/
0 4 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-ca-sos/
0 4 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-fl-ew/
30 4 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-oh-sos/
0 5 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-tx-goelect/
0 6 * * * /usr/local/bin/trigger.sh /internal/tasks/poll-results/
```

- [ ] **Step 3: Manually test one trigger**

After the stack is running, run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec civicmirror-scheduler /usr/local/bin/trigger.sh /internal/tasks/sync-elections/
```

Expected: JSON with `task_id` or `{"status": "already_running"}` and HTTP 202.

- [ ] **Step 4: Amend scheduler ADR**

Add a section to `CivicMirror-API/docs/adr/ADR-002-Scheduler-Architecture.md`:
```markdown
## Local Production Hosting

When CivicMirror is hosted locally, Google Cloud Scheduler is replaced by the
`civicmirror-scheduler` Docker Compose service. The scheduler service runs
`crond` and calls the same `/internal/tasks/*/` endpoints with
`Authorization: Bearer ${INTERNAL_TASK_TOKEN}`. This keeps the same idempotency
locks, Celery enqueue path, and operational behavior as the Cloud Scheduler
HTTP path, while removing the GCP dependency.

Cloud Run Jobs are replaced by either the same internal trigger endpoint or a
manual command:

```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec civicmirror-api python manage.py sync_elections
```
```

- [ ] **Step 5: Run API tests for internal triggers**

Run:
```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest internal/tests/test_views.py internal/tests/test_lock_release.py internal/tests/test_clear_task_locks.py -v
```

Expected: all selected tests pass.

### Task 4: Migrate Cloud SQL Data To Local Postgres

**Files:**
- Create: `/data/DockerConfigs/CivicMirror/backups/`
- No repo files are modified unless a runbook is added.

**Interfaces:**
- Consumes: production Cloud SQL database `civicmirror-db`.
- Produces: local Postgres volume `civicmirror_postgres_data` with migrated data.

- [ ] **Step 1: Take a cloud SQL export or pg_dump backup**

Production connects to Cloud SQL through the Cloud SQL connector
(`CivicMirror-FrontEnd/terraform/cloud_run.tf` mounts
`data.google_sql_database_instance.db.connection_name`), so the instance is
likely not directly reachable from this machine. Run `pg_dump` through
Cloud SQL Auth Proxy:
```bash
mkdir -p /data/DockerConfigs/CivicMirror/backups
gcloud sql instances describe civicmirror-db --project=civicmirror-2026 --format='value(connectionName)'
cloud-sql-proxy --port 5433 <connectionName-from-above> &
pg_dump "postgres://<cloud-sql-user>:<cloud-sql-password>@127.0.0.1:5433/civicmirror_api" \
  --format=custom \
  --no-owner \
  --no-acl \
  --file=/data/DockerConfigs/CivicMirror/backups/civicmirror_api-before-local-cutover.dump
kill %1
```

The local `pg_dump` client must be version 16 or newer (matching the server); use the `civicmirror-postgres` container's `pg_dump` via `docker run --network=host postgres:16-alpine pg_dump ...` if the host client is older.

Fallback if a proxy path is unavailable — server-side export to a GCS bucket:
```bash
gcloud sql export sql civicmirror-db gs://<bucket>/civicmirror_api-before-local-cutover.sql \
  --database=civicmirror_api --project=civicmirror-2026
gsutil cp gs://<bucket>/civicmirror_api-before-local-cutover.sql /data/DockerConfigs/CivicMirror/backups/
```
(A plain-SQL export restores with `psql -f` instead of `pg_restore` in Step 3.)

Expected: dump file exists and has non-zero size.

- [ ] **Step 2: Start only local database dependencies**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d civicmirror-postgres civicmirror-redis
```

Expected: Postgres and Redis are healthy.

- [ ] **Step 3: Restore into local Postgres**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec -T civicmirror-postgres \
  pg_restore --clean --if-exists --no-owner --no-acl \
  -U civicmirror \
  -d civicmirror_api \
  /backups/civicmirror_api-before-local-cutover.dump
```

Expected: restore completes without fatal errors.

- [ ] **Step 4: Run migrations against local data**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml run --rm civicmirror-api migrate
```

Expected: Django migrations complete with no unapplied migration errors.

- [ ] **Step 5: Validate core table counts**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec civicmirror-postgres \
  psql -U civicmirror -d civicmirror_api -c "SELECT COUNT(*) AS elections FROM elections_election;"
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec civicmirror-postgres \
  psql -U civicmirror -d civicmirror_api -c "SELECT COUNT(*) AS races FROM elections_race;"
```

Expected: counts are plausible compared with production before cutover.

### Task 5: Build And Verify Local API, Worker, Scheduler, And Frontend

**Files:**
- Read: `CivicMirror-API/backend/api/permissions.py`
- Read: `CivicMirror-FrontEnd/frontend/src/api/civicApiClient.ts`
- Read: `CivicMirror-FrontEnd/frontend/src/api/client.ts`

**Interfaces:**
- Consumes: local `.env`, restored database, local Redis.
- Produces: browser-accessible local frontend and API.

- [ ] **Step 1: Build the complete stack**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml build
```

Expected: API and frontend images build successfully.

- [ ] **Step 2: Start the complete stack**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d
```

Expected: all services are running or healthy.

- [ ] **Step 3: Verify API health**

Run:
```bash
curl -fsS http://127.0.0.1:8090/health/
```

Expected:
```json
{"status":"ok"}
```

- [ ] **Step 4: Verify API-key protected endpoint**

Run:
```bash
API_KEY="$(grep '^CIVICMIRROR_API_KEY=' /data/DockerConfigs/CivicMirror/.env | cut -d= -f2-)"
curl -fsS -H "X-Api-Key: ${API_KEY}" "http://127.0.0.1:8090/api/v1/elections/"
```

Expected: HTTP 200 JSON response.

- [ ] **Step 5: Verify frontend container serves the built app**

Run:
```bash
curl -fsSI http://127.0.0.1:8089/
```

Expected: HTTP 200 with nginx response headers.

- [ ] **Step 6: Verify frontend uses local API URL**

Run:
```bash
API_ORIGIN="$(grep '^VITE_CIVIC_API_URL=' /data/DockerConfigs/CivicMirror/.env | cut -d= -f2-)"
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec civicmirror-frontend \
  sh -c "grep -R '$API_ORIGIN' -n /usr/share/nginx/html | head && ! grep -R 'run.app' -n /usr/share/nginx/html"
```

Expected: built assets contain the intended local API base URL and do not contain `run.app`.

- [ ] **Step 7: Verify worker connectivity**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec civicmirror-worker celery -A config inspect ping
```

Expected: worker responds with `pong`.

- [ ] **Step 8: Check logs for startup errors**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml logs --tail=100 civicmirror-api civicmirror-worker civicmirror-scheduler civicmirror-frontend
```

Expected: no repeated database, Redis, CORS, API-key, or scheduler auth failures.

### Task 6: Route Local Domains And Frontend/API Origins

**Files:**
- Modify: `/data/DockerConfigs/CivicMirror/.env`
- Optional Modify: local reverse proxy config if this machine already uses one.
- Optional Modify: Cloudflare DNS records if public access must continue.

**Interfaces:**
- Consumes: running local ports `8089` and `8090`.
- Produces: stable local or public URLs for frontend and API.

- [ ] **Step 1: Choose local-only or public routing**

Use this decision table:
```markdown
| Option | Frontend URL | API URL | Required network boundary | Exposure |
|---|---|---|---|---|
| Same-host smoke test | http://localhost:8089 | http://localhost:8090 | host-only browser | private host |
| LAN direct ports | http://server-ip:8089 | http://server-ip:8090 | firewall allows 8089/8090 only from LAN | private LAN |
| Local reverse proxy | https://civicmirror.local | https://api.civicmirror.local | local DNS + TLS proxy + firewall blocks direct app ports | private LAN |
| Public Cloudflare Tunnel | https://civicmirror.app | https://api.civicmirror.app | tunnel routes to compose network or localhost; no direct router port-forward to app containers | public via tunnel |
| Public DNS to home IP | https://civicmirror.app | https://api.civicmirror.app | HTTPS reverse proxy, firewall, router port-forward only to proxy ports 80/443 | public internet |
```

- [ ] **Step 2: Update environment for selected origins**

For same-host smoke testing only, set:
```dotenv
FRONTEND_BASE_URL=http://localhost:8089
CORS_ALLOWED_ORIGINS=http://localhost:8089
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
VITE_CIVIC_API_URL=http://localhost:8090
VITE_API_URL=http://localhost:8090
```

For LAN testing from another computer or phone, replace `<server-ip>` with this machine's LAN address:
```dotenv
FRONTEND_BASE_URL=http://<server-ip>:8089
CORS_ALLOWED_ORIGINS=http://<server-ip>:8089
DJANGO_ALLOWED_HOSTS=<server-ip>,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://<server-ip>:8089,http://<server-ip>:8090
VITE_CIVIC_API_URL=http://<server-ip>:8090
VITE_API_URL=http://<server-ip>:8090
```

For public domain cutover, set:
```dotenv
FRONTEND_BASE_URL=https://civicmirror.app
CORS_ALLOWED_ORIGINS=https://civicmirror.app
DJANGO_ALLOWED_HOSTS=api.civicmirror.app,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://civicmirror.app,https://api.civicmirror.app
VITE_CIVIC_API_URL=https://api.civicmirror.app
VITE_API_URL=https://api.civicmirror.app
```

- [ ] **Step 2a: Enforce the selected network boundary before public cutover**

For LAN-only direct ports, verify that app ports are not reachable outside the LAN:
```bash
ss -ltnp | grep -E ':8089|:8090'
```

Expected: ports may listen locally, but the host firewall/router must block them from the public internet.

For public Cloudflare Tunnel, route traffic through the tunnel and do not forward `8089` or `8090` on the router:
```text
civicmirror.app -> http://127.0.0.1:8089
api.civicmirror.app -> http://127.0.0.1:8090
```

For public DNS to home IP, terminate TLS at a reverse proxy and forward only ports `80` and `443` from the router to that proxy. Do not expose Postgres, Redis, `8089`, or `8090` directly to the internet.

- [ ] **Step 3: Rebuild frontend after URL changes**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml build civicmirror-frontend
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d civicmirror-frontend civicmirror-api
```

Expected: frontend bundle points at the selected API URL.

- [ ] **Step 4: Verify browser URL behavior from the intended client**

For same-host testing, run:
```bash
curl -fsSI http://127.0.0.1:8089/
curl -fsS http://127.0.0.1:8090/health/
```

For LAN testing, run the same checks from another LAN device using `http://<server-ip>:8089/` and `http://<server-ip>:8090/health/`, then open the frontend in that device's browser.

Expected: the frontend loads and all API requests go to the selected API origin, not to `localhost` on the client device and not to any `run.app` URL.

### Task 7: Local Backup, Restore, And Operational Runbook

**Files:**
- Create: `CivicMirror-API/docs/runbooks/local-hosting.md`
- Create: `/data/DockerConfigs/CivicMirror/scripts/backup-postgres.sh`
- Create: `/data/DockerConfigs/CivicMirror/scripts/restore-postgres.sh`

**Interfaces:**
- Consumes: local Docker Compose stack.
- Produces: repeatable backup/restore and operations commands.

- [ ] **Step 1: Create backup script**

Create `/data/DockerConfigs/CivicMirror/scripts/backup-postgres.sh`:
```sh
#!/bin/sh
set -eu

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p /data/DockerConfigs/CivicMirror/backups

docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec -T civicmirror-postgres \
  pg_dump -U civicmirror --format=custom --no-owner --no-acl civicmirror_api \
  > "/data/DockerConfigs/CivicMirror/backups/civicmirror_api-${stamp}.dump"
```

- [ ] **Step 2: Create restore script**

Create `/data/DockerConfigs/CivicMirror/scripts/restore-postgres.sh`. The API holds
persistent database connections (`CONN_MAX_AGE=600` in `config/settings/prod.py`),
which block the `DROP` statements from `pg_restore --clean`, so the script must
stop the app services and clear remaining backends before restoring:
```sh
#!/bin/sh
set -eu

dump_path="${1:?usage: restore-postgres.sh /path/to/file.dump}"
compose="docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml"

# Stop everything that holds Postgres connections; --clean DROPs block on them.
$compose stop civicmirror-api civicmirror-worker civicmirror-scheduler civicmirror-frontend

# Terminate any straggler connections to the target database.
$compose exec -T civicmirror-postgres \
  psql -U civicmirror -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'civicmirror_api' AND pid <> pg_backend_pid();"

$compose exec -T civicmirror-postgres \
  pg_restore --clean --if-exists --no-owner --no-acl \
  -U civicmirror \
  -d civicmirror_api \
  < "$dump_path"

$compose up -d civicmirror-api civicmirror-worker civicmirror-scheduler civicmirror-frontend
```

- [ ] **Step 3: Create runbook**

Create `CivicMirror-API/docs/runbooks/local-hosting.md`:
````markdown
# CivicMirror Local Hosting Runbook

## Start

```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d
```

## Stop

```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml down
```

## Rebuild API And Frontend

```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml build civicmirror-api civicmirror-worker civicmirror-frontend
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d civicmirror-api civicmirror-worker civicmirror-frontend
```

## Run Migrations

```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml run --rm civicmirror-api migrate
```

## Health Checks

```bash
curl -fsS http://127.0.0.1:8090/health/
curl -fsSI http://127.0.0.1:8089/
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml ps
```

## Trigger One Scheduled Job

```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml exec civicmirror-scheduler /usr/local/bin/trigger.sh /internal/tasks/sync-elections/
```

## Backup

```bash
/data/DockerConfigs/CivicMirror/scripts/backup-postgres.sh
```

## Restore

```bash
/data/DockerConfigs/CivicMirror/scripts/restore-postgres.sh /data/DockerConfigs/CivicMirror/backups/civicmirror_api-YYYYMMDDTHHMMSSZ.dump
```
````

- [ ] **Step 4: Test backup script**

Run:
```bash
chmod +x /data/DockerConfigs/CivicMirror/scripts/backup-postgres.sh /data/DockerConfigs/CivicMirror/scripts/restore-postgres.sh
/data/DockerConfigs/CivicMirror/scripts/backup-postgres.sh
ls -lh /data/DockerConfigs/CivicMirror/backups/*.dump | tail -5
```

Expected: a fresh non-empty dump exists.

### Task 8: Cutover And GCP Cost Shutdown Gate

**Files:**
- Modify: `CivicMirror-API/docs/ops/local-migration-inventory.md`
- Optional Modify: Cloudflare DNS/proxy config.
- No GCP resource deletion until this task is explicitly approved.

**Interfaces:**
- Consumes: verified local stack and backup.
- Produces: production traffic served locally and cloud services paused or removed only after approval.

- [ ] **Step 1: Freeze cloud writes**

Pause Cloud Scheduler jobs first so cloud ingestion stops mutating Cloud SQL while the final local backup is taken:
```bash
gcloud scheduler jobs pause sync-openstates --location=us-central1 --project=civicmirror-2026
gcloud scheduler jobs pause poll-pending-results --location=us-central1 --project=civicmirror-2026
```

Repeat for every active scheduler job from the inventory.

- [ ] **Step 2: Take final production backup**

Run the Task 4 dump command again, then restore it with the Task 7 restore script (which stops the local API/worker/scheduler first — a live API holds 10-minute persistent connections that block `pg_restore --clean`):
```bash
/data/DockerConfigs/CivicMirror/scripts/restore-postgres.sh /data/DockerConfigs/CivicMirror/backups/<final-dump>.dump
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml run --rm civicmirror-api migrate
```

- [ ] **Step 3: Verify local frontend in browser**

Manual checklist:
```markdown
- [ ] Frontend loads from the selected local/public URL.
- [ ] If testing from another LAN device, frontend API calls target `http://<server-ip>:8090`, not `http://localhost:8090`.
- [ ] Elections list loads from local API.
- [ ] At least one race detail page loads.
- [ ] Results panel loads for a race with known results.
- [ ] API health returns OK.
- [ ] Worker responds to Celery ping.
- [ ] Local scheduler trigger returns 202.
- [ ] Account/community flows either work with mounted Firebase credentials or are explicitly documented as disabled with `FIREBASE_AUTH_ENABLED=False`.
- [ ] Logs show no CORS or API-key errors.
```

- [ ] **Step 4: Move traffic**

For public DNS, update `civicmirror.app` and `api.civicmirror.app` only after Task 6 Step 2a confirms the selected public network boundary.

If Cloudflare Tunnel is used, point the tunnel routes to host-local ports:
```text
civicmirror.app -> http://127.0.0.1:8089
api.civicmirror.app -> http://127.0.0.1:8090
```

If a reverse proxy is used instead, point DNS at the home IP and proxy:
```text
https://civicmirror.app -> http://127.0.0.1:8089
https://api.civicmirror.app -> http://127.0.0.1:8090
```

Expected: public traffic reaches only HTTPS proxy/tunnel entrypoints; direct internet access to app ports, Postgres, and Redis remains blocked.

- [ ] **Step 5: Observe for one scheduler cycle**

Run:
```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml logs -f civicmirror-api civicmirror-worker civicmirror-scheduler
```

Expected: at least one scheduled trigger is accepted and either enqueues a Celery task or reports `already_running` due to idempotency.

- [ ] **Step 6: After explicit approval, shut down GCP cost centers**

Use deletion or scale-down commands only after the user confirms local production is good. Service names below are placeholders — substitute the verified names from the Task 1 inventory, and cover **every** live Cloud Run service found there (including `civicmirror-backend` if it exists). Safer first step (Cloud Run does not accept `--max-instances=0`; pause all schedulers and scale minimums to zero instead):
```bash
gcloud run services update civicmirror-worker --min-instances=0 --region=us-central1 --project=civicmirror-2026
gcloud scheduler jobs pause sync-elections-hourly --location=us-central1 --project=civicmirror-2026
```

Repeat the pause for every scheduler job in the inventory (they should already be paused from Step 1).

Final deletion candidates after a retention window (use inventory names; delete every Cloud Run service in the inventory, not just these):
```bash
gcloud run services delete civicmirror-frontend --region=us-central1 --project=civicmirror-2026
gcloud run services delete civicmirror-api --region=us-central1 --project=civicmirror-2026
gcloud run services delete civicmirror-worker --region=us-central1 --project=civicmirror-2026
# Only if Task 1 confirmed the legacy service is live and unneeded:
gcloud run services delete civicmirror-backend --region=us-central1 --project=civicmirror-2026
gcloud sql instances delete civicmirror-db --project=civicmirror-2026
gcloud redis instances delete civicmirror-redis --region=us-central1 --project=civicmirror-2026
```

After deletion, run the Step 1-style `gcloud run services list` / `gcloud scheduler jobs list` commands from Task 1 again and confirm nothing billable remains.

Expected: this step is executed only when backups are verified and the user explicitly accepts the loss of managed cloud rollback.

## Risks And Mitigations

- **Data loss risk:** mitigate with `pg_dump` before every restore/cutover and keep Cloud SQL alive until local verification passes.
- **Scheduler drift risk:** use the existing internal endpoints and Redis locks instead of inventing a new task path.
- **API-key drift risk:** generate one local `CIVICMIRROR_API_KEY` and use the same value for frontend `VITE_CIVIC_API_KEY`.
- **Frontend stale bundle risk:** rebuild `civicmirror-frontend` whenever `VITE_*` values change.
- **LAN localhost risk:** use `localhost` only for same-host smoke tests; for phone/laptop LAN testing, build the frontend with `http://<server-ip>:8090` or a LAN DNS name.
- **Firebase/auth drift risk:** either mount `FIREBASE_CREDENTIALS_FILE` and verify account/community flows, or intentionally set `FIREBASE_AUTH_ENABLED=False` and record the disabled scope before cutover.
- **Cloud Run traffic drift risk:** record `status.traffic`, active revisions, image digests, and frontend bundle API URL before assuming a cloud deploy or shutdown target is current.
- **Cloudflare/source blocking risk:** current cloud workarounds include proxy and solver env vars; keep `CIVICMIRROR_PROXY_*`, `IA_SOS_PROXY_*`, and `CF_SOLVER_*` in the local env until each adapter is verified from the local network.
- **Port collision risk:** this plan uses host ports `8089` for frontend and `8090` for API; change them before implementation if those are already occupied.
- **Security exposure risk:** LAN-only hosting should bind behind local firewall rules; public hosting requires HTTPS, a reverse proxy or tunnel, and no direct Postgres/Redis or app-container host ports exposed to the internet.

## Verification Summary

Implementation is complete only when all are true:

- `docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml ps` shows API, worker, Redis, Postgres, scheduler, and frontend running.
- `curl -fsS http://127.0.0.1:8090/health/` returns `{"status":"ok"}`.
- `curl -fsS -H "X-Api-Key: ${CIVICMIRROR_API_KEY}" http://127.0.0.1:8090/api/v1/elections/` returns JSON.
- `curl -fsSI http://127.0.0.1:8089/` returns HTTP 200.
- A local scheduler trigger returns HTTP 202.
- A Celery worker responds to `celery -A config inspect ping`.
- The browser loads the frontend and consumes the local API without `run.app` requests.
- Browser verification passes from the intended client location: same host, LAN device, or public domain.
- Public-domain verification confirms HTTPS proxy/tunnel routing and no direct public exposure of Postgres, Redis, `8089`, or `8090`.
- Account/community flows are verified with mounted Firebase credentials, or the migration inventory explicitly records that Firebase is disabled locally.
- A fresh local Postgres backup exists after cutover.
- Cloud resources remain untouched until the final explicit shutdown approval.
