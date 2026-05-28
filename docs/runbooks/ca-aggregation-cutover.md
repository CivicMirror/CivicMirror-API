# CA Aggregation Cutover (Phase 1)

Run after the Phase 0+1 code is deployed. Destructive — confirm before each step.

## 1. Pause not-yet-migrated scheduler jobs

Leave only the migrated sources enabled (Civic `sync-elections-hourly`, `sync-ca-sos`):

```bash
for job in sync-sc-vrems poll-sc-enr sync-sc-enr-results sync-co-sos \
           sync-ia-sos sync-ma-sos sync-va-elect sync-openstates \
           sync-fec poll-pending-results; do
  gcloud scheduler jobs pause "$job" --project=civicmirror-2026 --location=us-central1
done
```

## 2. Apply migrations

```bash
gcloud run jobs execute civicmirror-migrate \
  --project=civicmirror-2026 --region=us-central1 --wait
```

## 3. Wipe source-siloed election data

Clears old rows so re-sync produces canonical-keyed records. Run in a Django shell
on the worker/api (cascades to Race/Candidate/MeasureOption):

```bash
python manage.py shell -c "from elections.models import Election; Election.objects.all().delete()"
```

## 4. Re-sync the migrated sources

```bash
INTERNAL_TOKEN=$(gcloud secrets versions access latest --secret=INTERNAL_TASK_TOKEN --project=civicmirror-2026)
BASE="https://api.civicmirror.welshrd.com/internal/tasks"
curl -s -X POST "$BASE/sync-elections/" -H "Authorization: Bearer $INTERNAL_TOKEN"   # Civic
curl -s -X POST "$BASE/sync-ca-sos/"    -H "Authorization: Bearer $INTERNAL_TOKEN"   # CA SOS
```

## 5. Verify the merge

```bash
API_KEY=$(gcloud secrets versions access latest --secret=CIVICMIRROR_API_KEY --project=civicmirror-2026)
curl -s "https://api.civicmirror.welshrd.com/api/elections/?state=CA" -H "X-Api-Key: $API_KEY"
```

Expect a single CA primary with `canonical_key = "CA:primary:2026-06-02:state"` and
`sources` containing both `civic_api` and `ca_sos`.
