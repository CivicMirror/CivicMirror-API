# Kentucky live results: repair and local rollout

Kentucky's WCF XML is implicitly scoped to the current election. Validate both
date and type before using it. `KY_FLARESOLVERR_URL` optionally supplies browser
credentials through `/v1`; it is independent of the `/solve` CF solver. XML
always downloads through ordinary HTTP. Cookies and User-Agent are cached as a
pair for up to 20 minutes, bounded by cookie expiry, and never logged.

`CurrentResults` includes local contests by default. Set election
`source_metadata.ky_results_feed` to `exclude_local` only for reduced coverage;
`all` is the explicit full-feed value. The legacy `ky_election_id` cannot bypass
validation. Every result remains unofficial with an unset winner.

## Preview and apply

Run from `backend/` under Python 3.13. Preview performs no database or cache
writes, including when it needs browser recovery. `--snapshot-dir` reads all
six dataset XML files locally instead of fetching them. Feed selection also
determines which captured CurrentResults file is used.

```bash
python manage.py reconcile_ky_results --election-id 1883 --report /tmp/ky-review.json
python manage.py reconcile_ky_results --election-id 1883 --snapshot-dir /snapshot \
  --expect-rows 208137 --expect-reported-contests 3333 --expect-no-results 293 \
  --report /tmp/ky-snapshot-review.json
python manage.py reconcile_ky_results --election-id 1883 --apply \
  --contest-id 122 --contest-id 2048 --contest-id 1115 \
  --contest-id 1749 --contest-id 1039 --report /tmp/ky-pilot.json
python manage.py reconcile_ky_results --election-id 1883 --apply --report /tmp/ky-applied.json
```

The snapshot counts above are assertions for the 2026-11-01 capture only. All
rows are accounted for as accepted or held, and metadata contests without rows
are listed separately. Review entries include source IDs, jurisdiction and
reporting evidence, candidate names, competing races, and reasons. The latest
applied report is also retained in election `source_metadata.ky_results_review`.
Celery returns a compact coverage summary so repeated polls do not retain the
complete review in Redis.
Pilot reports distinguish proposed coverage from the number of contests actually
applied. Use the same reviewed snapshot for preview and pilot when reproducing a
capture; a live apply revalidates the freshly downloaded source.

A PostgreSQL transaction advisory lock covers fetching through persistence.
Overlapping tasks return `already_running`. Race/candidate creation and all
result changes commit together. Natural keys use the existing database
constraint; retries compare records and bulk-insert/update only changed results.
Malformed IDs/votes/joins abort without replacing results. Missing totals,
duplicate choice names, unknown local jurisdictions, and conflicting source/race
identities, jurisdiction evidence, and seat counts are held. A changed stored result-key set aborts for explicit review.
No rows are deleted by this workflow.

Reconciliation runs on every poll so held contests can be resolved by mapping
changes. The hash includes all datasets and parser version. A version is cached
only after complete, successful persistence with no held contests. Identical
imports still reconsider mappings and compare persisted rows.

## Local Docker rollout

Production is `/data/DockerConfigs/CivicMirror`, with health at
`http://127.0.0.1:8090/health/`. Before changes, capture a PostgreSQL custom-format
backup plus checksum, KY election/race/candidate/result rows, image IDs, Compose
files, scheduler crontab, and environment configuration in a private directory.
Build the API/worker image explicitly from the isolated branch's `backend/`.
Pin both services to that image; retain the previous images/configuration for
rollback. Do not rebuild or recreate unrelated services.

In `/data/DockerConfigs/docker-compose.yaml`, attach FlareSolverr to both its
existing `default` network and an external network named `civicmirror_default`.
Keep `127.0.0.1:8191:8191`. Set `KY_FLARESOLVERR_URL=http://flaresolverr:8191`
for API/worker (commands can run from either). Do not change `/solve` settings.

After deploying API/worker and solver networking, preview from the worker, pilot
one legislative, county, municipal multi-seat, school and measure contest, and
verify API totals and breakdowns. Apply all verified contests, repeat identically,
and check no extra race/candidate/option/result records were created. Retain all
holds for review.

The authenticated trigger is `POST /internal/tasks/poll-ky-results/`, using the
existing `Authorization: Bearer <INTERNAL_TASK_TOKEN>`. An empty body queues KY
elections dated today/yesterday in America/New_York, excluding terminal status.
JSON `{"election_id":1883}` allows a pre-election smoke check. Add only this cron:

```cron
*/2 * * * * /usr/local/bin/trigger.sh /internal/tasks/poll-ky-results/
```

Recreate only the scheduler after editing its mounted source crontab because it
copies the file on startup. Check the installed crontab, trigger HTTP status,
worker completion logs, container health, API totals, unofficial/winner flags,
and the saved coverage report. Compare nonzero totals with the official site
after voting starts; the Nov 1 snapshot has zero votes.

## Rollback

Remove the KY polling line first. Restore saved API/worker image references,
Compose and solver network configuration, and recreate only affected services.
Keep the pre-rollout backup and affected-row export. If pilot mappings are
incorrect, stop KY imports and restore affected data from the reviewed export or
backup using a scoped, reviewed transaction; do not overwrite unrelated live
state by blindly restoring the whole database.
