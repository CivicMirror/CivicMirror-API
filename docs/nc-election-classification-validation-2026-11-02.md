# NC classification validation — November 2, 2026

The shared state/county/municipal baseline is implemented for issue #188. Municipality-specific dates and methods remain follow-up; the November municipal inference is usable now. This evidence records an isolated rehearsal, not a production cutover.

## Automated checks

- Full backend suite on Python 3.13: **2,449 passed, 3 skipped**.
- Focused routing/repair suite on PostgreSQL 16: **28 passed**, including stale approval rejection, report-write rollback, held/tombstone preservation, destination protection and future/election-day lifecycle boundaries.
- Scoped Ruff, Django system checks and commit secret scanning passed.
- No NC schema migration. `makemigrations --check` still reports the baseline's unrelated KY `Race.Source` choice drift in unchanged model/migration files.

## Production-snapshot rehearsal

A verified complete database dump was restored into a separate PostgreSQL container. The repair command fetched official source evidence, generated a complete no-write preview, and applied its unchanged fingerprints to that restored database. Production writers and data were not changed.

| Disposition | Races |
| --- | ---: |
| Supported classifications | 14,102 |
| Held with recorded reasons | 4,247 |
| Existing superseded records preserved | 680 |
| Total accounted | 19,029 |

Before/after hashes verified:

- All original race IDs and preserved race fields remained intact.
- All **4,927 held/superseded race records** remained unchanged.
- Candidate, result, measure-option, mock-vote, source-record and source-link IDs, values and relationships were preserved.
- Candidate count stayed **45,924**, result count **50,840**, measure-option count **638**, linked source-record count **171**, source-link count **57**, and mock-vote count **0**.
- Vote values remained unchanged. The explicitly reviewed exception changed lifecycle fields for **185 future zero-vote races**: upcoming/active races and unofficial result rows with no certification timestamp replaced premature certification/archive state.

Earlier rehearsal caught a PostgreSQL nullable-join locking error before the first scope committed. The corrected lock targets only source-record rows. The successful full application and focused PostgreSQL transaction tests validate the corrected path.

## Repeated actual ingestion

Using frozen official filing/ZIP bytes, separate in-process cache and memory-only Celery settings:

1. Two complete discovery/candidate runs converged at **4,408 Elections, 19,041 races and 45,948 candidates**. The first run added 192 current/future jurisdiction events, three previously absent historical runoff events, 12 filing races and 24 candidates; the second added none. The historical additions were supported by the known runoff calendar and official filings, and had no same-title peers in their target events.
2. Candidate refresh skipped all **318 exact filing-key matches to protected held races**. All 4,927 held/superseded race records and their candidate records remained unchanged after both runs.
3. Actual adapter/task results ingestion ran twice for seven representative special-primary, special-general, municipal/nomination and future events. Race/candidate counts stayed stable, and result count stayed **50,840**. Unchanged source versions were skipped on the second pass; the future archive produced no results.

After ingestion refresh, representative scopes for April 30, 2019; September 10, 2019; and November 3, 2026 passed exact snapshot comparison on repeat repair and on an intentionally rolled-back transaction. Their scope sizes were 6, 12 and 185 races respectively. Fresh previews were generated from the refreshed state; the original preview is intentionally stale after ingestion/code changes.

Private dumps, raw candidate contact files and detailed repair reports remain outside Git. The public inventory, classification contract and runbook describe the evidence and operational requirements. Live cutover still requires a fresh backup, a fresh preview against the actual database, coordinated writer activation, API health checks and scheduled convergence evidence. Municipal date research does not block the implemented baseline.
