# Kentucky live-results rollout — 2026-11-01

Implemented on `fix/ky-live-results-repair`; deployed runtime code is commit
`3c93dc3f70a4b375f8ec5a6e4f63de2a737a8ce2` (initial repair `4b2663d`).
API and worker use image
`sha256:c4f61ed3121585bef5f436cd08024d00a8787bca7090e18bb9aeb227b1951dbc`.
The original checkout and unrelated changes remain preserved.

## Source accounting and persistence

Captured and freshly downloaded live XML produced identical source hash
`afcaed505bcf9c911195026b83986e535fa75a71177789b64e871b46f640cdda`.
These are assertions for this capture, not permanent upstream requirements.

| Disposition | Contests | Result rows |
| --- | ---: | ---: |
| Verified and persisted | 3,327 | 203,911 |
| Held for review | 6 | 4,226 |
| Metadata without result rows | 293 | 0 |
| Total | 3,626 | 208,137 |

The import reused 125 filings races and added 3,202 verified races. One existing
filings race remains held, so the election has 3,328 races in total. Candidate and
option counts are 6,272 and 271. All 203,911 persisted results were compared with
normalized source rows by contest ID, candidate ID, reporting-unit ID, vote
count, fragment, result type, and winner flag. They match exactly: 9,724 totals
and 194,187 breakdown rows. Contest identities are unique within the election.
All results are unofficial, winners and certified timestamps unset.

| Held source ContestId | Title | Rows | Reason |
| --- | --- | ---: | --- |
| 966 | CIRCUIT CLERK | 83 | State scope does not identify local jurisdiction |
| 1202 | CIRCUIT CLERK | 179 | State scope does not identify local jurisdiction |
| 2095 | CITY COMMISSIONERS City of Corbin | 99 | Duplicate normalized choice names |
| 173 | DISTRICT JUDGE 21st Judicial District 1st Division | 79 | Duplicate normalized choice names |
| 2620 | JAILER | 16 | Incomplete choice totals |
| 157 | UNITED STATES REPRESENTATIVE in CONGRESS 5th Congressional District | 3,770 | Incomplete choice totals |

All metadata-only contests and held evidence remain in the machine-readable
report and election `source_metadata.ky_results_review`.

## Verification and operational evidence

- Python 3.13, PostgreSQL 16: **807 tests passed**, covering results adapters,
  tasks, winner safeguards, KY filings and internal triggers. Ruff, Django system
  checks, and the commit secret scanner passed.
- Independent branch review found seat/jurisdiction conflicts and quadratic
  matching. Regression tests failed first and passed after fixes. The indexed
  complete-snapshot repeat on disposable PostgreSQL took 24.670 seconds with
  zero created or updated result rows.
- Production pilot covered source contests 122 (US House district 2), 2048
  (Knott sheriff), 1115 (Allen commissioners, four selections), 1749 (Anchorage
  school, three selections), and 1039 (Fayette charter measure). All five API
  responses match source/DB totals; 2,470 pilot rows and their breakdowns passed.
- Full production API checks repeated successfully after all verified contests
  were persisted. Missing auth returns 401 for the KY polling trigger. The
  authenticated date-window trigger returned 202 and queued no election on Nov 1;
  the explicit election-ID path returned 202 and queued election 1883.
- API/worker and solver networking are configured persistently in Compose.
  FlareSolverr retains `dockerconfigs_default` and additionally joins
  `civicmirror_default`; port 8191 remains bound to loopback. API and worker use
  `http://flaresolverr:8191`, independently of the existing CF solver.
- The authenticated explicit-election repeat completed successfully (task
  `6238c1f8-c823-4174-97f3-d463e7f2845d`): created/updated results both zero;
  all race/candidate/option/result counts unchanged. Its Celery result is 470
  bytes; the detailed review remains in DB/report storage.
- The scheduler's installed crontab includes the KY-only two-minute trigger.
  Existing state schedules are unchanged.

Private local evidence and rollback materials are under
`/data/DockerConfigs/CivicMirror/backups/ky-live-20261101/`: custom-format full
PostgreSQL backup and checksum, affected KY records before import, prior/current
Compose files, environment and image snapshots, captured XML, dry-run/apply
reports, API verification, complete-row audit, and test output. The 11,979,136-byte
backup passed its checksum and was restored into a disposable database; the
restored KY election had its original 126 races and zero results.

All votes are zero on Nov 1, before the Nov 3 election. A comparison of nonzero
totals with the official site remains a post-voting check. Use the
[rollout and rollback runbook](ky-live-results-rollout.md) for operations; do not
remove this worktree while Compose uses its build context.
