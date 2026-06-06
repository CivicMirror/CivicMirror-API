# CivicMirror API — Deployment Guide

This guide covers deploying CivicMirror API to Google Cloud Run with Cloud SQL (PostgreSQL), Cloud Memorystore (Redis), and Cloud Scheduler.

## Project architecture

Both the CivicMirror frontend and this API backend share the **`civicmirror-2026`** GCP project. The project has three Cloud Run services:

| Service | Description |
|---|---|
| `civicmirror-frontend` | CivicMirror web app (existing) |
| `civicmirror-api` | This Django/Celery API (new) |
| `civicmirror-worker` | Celery worker for background tasks (new) |

Shared infrastructure (Cloud SQL, Memorystore, Artifact Registry) is reused where it already exists.

---

## Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- Docker installed
- Already a member of the `civicmirror-2026` GCP project
- GitHub repository: `tokendad/CivicMirror-API`

```bash
export PROJECT_ID=civicmirror-2026
export REGION=us-central1
export REPO=civicmirror-api
export API_SERVICE=civicmirror-api
export WORKER_SERVICE=civicmirror-worker
export FRONTEND_SERVICE=civicmirror-frontend   # existing frontend service
export SCHEDULER_SA=civicmirror-scheduler

gcloud config set project $PROJECT_ID
gcloud config set run/region $REGION
```

---

## 1. Enable APIs

Most of these are already enabled if the frontend is deployed. Run to be safe — enabling an already-enabled API is a no-op.

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  redis.googleapis.com \
  iam.googleapis.com
```

---

## 2. Artifact Registry

```bash
gcloud artifacts repositories create $REPO \
  --repository-format=docker \
  --location=$REGION

# Full image path used throughout:
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$REPO
```

---

## 3. Cloud SQL (PostgreSQL)

```bash
gcloud sql instances create civicmirror-db \
  --database-version=POSTGRES_16 \
  --tier=db-g1-small \
  --region=$REGION \
  --storage-auto-increase

gcloud sql databases create civicmirror_api --instance=civicmirror-db
gcloud sql users create civicmirror \
  --instance=civicmirror-db \
  --password=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")

# Note the connection name:
gcloud sql instances describe civicmirror-db --format='value(connectionName)'
# → civicmirror-2026:us-central1:civicmirror-db
```

Set `DATABASE_URL` as:
```
postgresql://civicmirror:<password>@/civicmirror_api?host=/cloudsql/civicmirror-2026:us-central1:civicmirror-db
```

---

## 4. Cloud Memorystore (Redis)

```bash
gcloud redis instances create civicmirror-redis \
  --size=1 \
  --region=$REGION \
  --tier=BASIC

gcloud redis instances describe civicmirror-redis \
  --region=$REGION \
  --format='value(host,port)'
# → 10.x.x.x  6379
```

Set `REDIS_URL=redis://10.x.x.x:6379/0`  
Set `CELERY_BROKER_URL=redis://10.x.x.x:6379/0`  
Set `CELERY_RESULT_BACKEND=redis://10.x.x.x:6379/1`

> Redis on Memorystore is only accessible via VPC. The Cloud Run services must be connected to the same VPC using **Direct VPC egress** or a VPC connector.

---

## 5. Secret Manager

Store all sensitive values:

```bash
# Generate keys
DJANGO_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
CIVICMIRROR_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

gcloud secrets create django-secret-key --replication-policy=automatic
gcloud secrets create civicmirror-api-key --replication-policy=automatic
gcloud secrets create database-url --replication-policy=automatic
gcloud secrets create redis-url --replication-policy=automatic
gcloud secrets create civic-api-key --replication-policy=automatic
gcloud secrets create fec-api-key --replication-policy=automatic
gcloud secrets create openstates-api-key --replication-policy=automatic
gcloud secrets create internal-task-token --replication-policy=automatic

echo -n "$DJANGO_SECRET_KEY"   | gcloud secrets versions add django-secret-key --data-file=-
echo -n "$CIVICMIRROR_API_KEY" | gcloud secrets versions add civicmirror-api-key --data-file=-
# Add remaining secrets with actual values
```

---

## 6. Service Account (API + Worker)

```bash
gcloud iam service-accounts create civicmirror-api \
  --display-name="CivicMirror API Runtime"

SA_EMAIL=civicmirror-api@$PROJECT_ID.iam.gserviceaccount.com

# Grant Secret Manager access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/secretmanager.secretAccessor"

# Grant Cloud SQL access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/cloudsql.client"
```

---

## 7. Deploy API Service

```bash
# Build and push (normally done by CI — see GitHub Actions workflows)
docker build -t $IMAGE:latest ./backend
docker push $IMAGE:latest

# Run migrations before first deploy
gcloud run jobs create civicmirror-migrate \
  --image=$IMAGE:latest \
  --command=docker-entrypoint.sh \
  --args=migrate \
  --service-account=$SA_EMAIL \
  --set-cloudsql-instances=civicmirror-2026:us-central1:civicmirror-db \
  --set-secrets="DATABASE_URL=database-url:latest,SECRET_KEY=django-secret-key:latest" \
  --region=$REGION

gcloud run jobs execute civicmirror-migrate --region=$REGION --wait

# Deploy API service
gcloud run deploy $API_SERVICE \
  --image=$IMAGE:latest \
  --service-account=$SA_EMAIL \
  --min-instances=0 \
  --max-instances=10 \
  --memory=512Mi \
  --cpu=1 \
  --timeout=60 \
  --set-cloudsql-instances=civicmirror-2026:us-central1:civicmirror-db \
  --set-secrets="\
SECRET_KEY=django-secret-key:latest,\
DATABASE_URL=database-url:latest,\
REDIS_URL=redis-url:latest,\
CELERY_BROKER_URL=redis-url:latest,\
CIVICMIRROR_API_KEY=civicmirror-api-key:latest,\
CIVIC_API_KEY=civic-api-key:latest,\
FEC_API_KEY=fec-api-key:latest,\
OPENSTATES_API_KEY=openstates-api-key:latest" \
  --set-env-vars="\
DJANGO_SETTINGS_MODULE=config.settings.prod,\
DJANGO_ALLOWED_HOSTS=civicmirror-api-<hash>-uc.a.run.app,\
LOG_LEVEL=INFO,\
CELERY_TASK_ALWAYS_EAGER=False" \
  --no-allow-unauthenticated \
  --region=$REGION
```

> `--no-allow-unauthenticated` keeps the Cloud Run service private. The CivicMirror frontend uses the `X-Api-Key` header; internal endpoints use OIDC (see section 9).

---

## 8. Deploy Worker Service

```bash
gcloud run deploy $WORKER_SERVICE \
  --image=$IMAGE:latest \
  --service-account=$SA_EMAIL \
  --min-instances=1 \
  --max-instances=5 \
  --memory=2Gi \
  --cpu=2 \
  --command=docker-entrypoint.sh \
  --args=worker \
  --set-cloudsql-instances=civicmirror-2026:us-central1:civicmirror-db \
  --set-secrets="\
SECRET_KEY=django-secret-key:latest,\
DATABASE_URL=database-url:latest,\
REDIS_URL=redis-url:latest,\
CELERY_BROKER_URL=redis-url:latest,\
CELERY_RESULT_BACKEND=redis-url:latest,\
CIVIC_API_KEY=civic-api-key:latest,\
FEC_API_KEY=fec-api-key:latest,\
OPENSTATES_API_KEY=openstates-api-key:latest" \
  --set-env-vars="\
DJANGO_SETTINGS_MODULE=config.settings.prod,\
CELERY_CONCURRENCY=2,\
CELERY_LOG_LEVEL=INFO,\
LOG_LEVEL=INFO" \
  --no-allow-unauthenticated \
  --region=$REGION
```

---

## 9. Cloud Scheduler (ADR-002)

### Service account for scheduler

```bash
gcloud iam service-accounts create $SCHEDULER_SA \
  --display-name="CivicMirror Cloud Scheduler"

SCHEDULER_SA_EMAIL=$SCHEDULER_SA@$PROJECT_ID.iam.gserviceaccount.com

# Grant permission to invoke the API Cloud Run service
gcloud run services add-iam-policy-binding $API_SERVICE \
  --member="serviceAccount:$SCHEDULER_SA_EMAIL" \
  --role="roles/run.invoker" \
  --region=$REGION

export API_URL=$(gcloud run services describe $API_SERVICE \
  --region=$REGION --format='value(status.url)')
```

### Create scheduler jobs

```bash
# sync-elections: hourly
gcloud scheduler jobs create http sync-elections \
  --location=$REGION \
  --schedule="0 * * * *" \
  --uri="$API_URL/internal/tasks/sync-elections/" \
  --http-method=POST \
  --oidc-service-account-email=$SCHEDULER_SA_EMAIL \
  --oidc-token-audience="$API_URL/internal/tasks/sync-elections/"

# poll-results: daily at 06:00 UTC
gcloud scheduler jobs create http poll-results \
  --location=$REGION \
  --schedule="0 6 * * *" \
  --uri="$API_URL/internal/tasks/poll-results/" \
  --http-method=POST \
  --oidc-service-account-email=$SCHEDULER_SA_EMAIL \
  --oidc-token-audience="$API_URL/internal/tasks/poll-results/"

# sync-openstates: daily at 02:00 UTC (off-peak, avoids OpenStates rate limits)
gcloud scheduler jobs create http sync-openstates \
  --location=$REGION \
  --schedule="0 2 * * *" \
  --uri="$API_URL/internal/tasks/sync-openstates/" \
  --http-method=POST \
  --oidc-service-account-email=$SCHEDULER_SA_EMAIL \
  --oidc-token-audience="$API_URL/internal/tasks/sync-openstates/"

# sync-fec: every 6 hours
gcloud scheduler jobs create http sync-fec \
  --location=$REGION \
  --schedule="0 */6 * * *" \
  --uri="$API_URL/internal/tasks/sync-fec/" \
  --http-method=POST \
  --oidc-service-account-email=$SCHEDULER_SA_EMAIL \
  --oidc-token-audience="$API_URL/internal/tasks/sync-fec/"
```

---

## 10. Verify

```bash
# Health check (exempt from API key auth)
curl "$API_URL/health/"

# Force an election sync (requires INTERNAL_TASK_TOKEN for local testing)
curl -X POST "$API_URL/internal/tasks/sync-elections/" \
  -H "Authorization: Bearer $INTERNAL_TASK_TOKEN"
```

---

## Rolling Updates

New deploys (done by CI) follow the same `gcloud run deploy` commands with updated image tags. Cloud Run performs zero-downtime rollouts by default. Run migrations as a Cloud Run Job before deploying the new revision.

## Secret Rotation

1. Update the secret version in Secret Manager.
2. Redeploy both Cloud Run services (CI re-deploy or `gcloud run deploy --update-secrets`).
3. The old secret version can be disabled after confirming the new version is live.
