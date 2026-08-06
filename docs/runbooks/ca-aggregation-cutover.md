# CA Aggregation Cutover (Phase 1)

> ✅ **COMPLETED 2026-05-31** — Phase 1 cutover executed. CA elections are live on canonical rows with `civic_api` + `ca_sos` contributing sources. Kept for reference.

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
docker exec civicmirror-scheduler /usr/local/bin/trigger.sh /internal/tasks/sync-elections/   # Civic
docker exec civicmirror-scheduler /usr/local/bin/trigger.sh /internal/tasks/sync-ca-sos/       # CA SOS
```

## 5. Verify the merge

```bash
curl -s "https://civicmirror.app/api/elections/?state=CA" -H "X-Api-Key: $CIVICMIRROR_API_KEY"
```

Expect a single CA primary with `canonical_key = "CA:primary:2026-06-02:state"` and
`sources` containing both `civic_api` and `ca_sos`.
