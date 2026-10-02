# Production Deploy Runbook

Production runs from local Docker Compose in `/data/DockerConfigs/CivicMirror`, not Cloud
Run. There is no automated CI/CD deploy — pushing to `main` does not deploy anything.
See issue #163.

## Topology

```
Cloudflare (tunnel, cloudflared)
  └─> civicmirror-frontend  0.0.0.0:8089 -> :8080   nginx
        ├─ location /api/         -> proxy_pass http://civicmirror-api:8080/api/
        ├─ location /django-admin -> proxy_pass http://civicmirror-api:8080/...
        └─ location /             -> SPA
civicmirror-api      127.0.0.1:8090 -> :8080   (loopback only, by design)
civicmirror-scheduler  cron -> http://civicmirror-api:8080/internal/tasks/...
```

Nothing listens on host `:80`/`:443` — ingress is entirely via the Cloudflare tunnel.
The API is only reachable from outside through the frontend's `/api/` proxy at
`https://civicmirror.app/api/...`; there is no separate `api.` hostname.

## Deploying a change

```bash
cd /data/DockerConfigs/CivicMirror
docker compose build civicmirror-api civicmirror-worker
# Apply migrations with the NEW image before it takes traffic. Code that queries a
# table the running database doesn't have yet (e.g. api_apikey) returns 500s until
# the migration runs. Safe to run when there are no pending migrations.
docker compose run --rm civicmirror-api migrate
docker compose up -d civicmirror-api civicmirror-worker
```

## Service API keys

Service keys go to individually approved clients (ADR-010). Run inside the API container:

```bash
docker exec civicmirror-api python manage.py create_api_key --name "CivicData" --access read
docker exec civicmirror-api python manage.py list_api_keys
docker exec civicmirror-api python manage.py revoke_api_key cm_1a2b3c4d
```

The key is printed once. Send it to the client over a private channel and don't store it in tickets or chat.

## Schedule

The real schedule is `scheduler/crontab` in this directory (mounted into the
`civicmirror-scheduler` container), not GitHub Actions or Cloud Scheduler. Edit that file
and restart the `civicmirror-scheduler` container to change it.

## Operator tooling equivalents

| Old (Cloud Run / GCP) | Current |
|---|---|
| `gcloud logging read ... civicmirror-worker` | `docker logs civicmirror-worker` |
| `gcloud run jobs execute clear-idempotency-locks` | `docker exec civicmirror-api python manage.py clear_task_locks` |
| `gcloud scheduler jobs list` | `scheduler/crontab` in this directory |
| `curl https://api.civicmirror.welshrd.com/internal/tasks/...` | `docker exec civicmirror-scheduler /usr/local/bin/trigger.sh /internal/tasks/...` |
| `gcloud secrets versions access INTERNAL_TASK_TOKEN` | `INTERNAL_TASK_TOKEN` in the scheduler container env |
