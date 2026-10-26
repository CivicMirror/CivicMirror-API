# NC contest identity and existing-data repair

Implements #214 and the canonical-race repair needed for #223. This work depends on the source-outcome and nomination safeguards in #218. The target is the legacy `elections`/`results` datastore served by the public API; the reported race IDs are not CM2 records.

## Identity contract

`ResultRow.raw.nc_contest_key` and `Race.source_metadata.nc_contest_key` contain the same versioned identity. It qualifies the source contest ID with contest type, normalized title, and electorate. Its election scope comes from the race's election FK. Candidate party is separate from identity; party-specific primary identity comes from the contest title, so a general election remains one contest across parties.

County contests use county identity. State/federal/district contests remain unified across reporting counties. The small `LOCAL_ELECTORATES` registry in `results/nc_identity.py` records explicit municipality/school/sanitary electorates and reporting counties observed in the official 2014-05-06 and 2024 ENRS feeds. A shared place, source group ID and allowed county set are all required. Generic county-office titles use county qualification. Other same-name local overlaps, including overlaps with different source IDs, remain unresolved. They are held during bootstrap and block full-scope repair until verified. Add source evidence and regression fixtures before adding electorate exceptions or source-ID aliases.

A race with identity never falls back to title matching. Existing unqualified legacy races require repair. A unique filing race can adopt its first results identity, and results bootstrap uses the filing canonical key for supported filing offices. Filing refreshes preserve results identity, seat evidence and candidate audit metadata. The adapter cache namespace is versioned to force a fresh fetch after the identity change.

Positive, consistent `Vote For` populates `max_selections` and `source_vote_for`; values greater than one select `multi_seat`. Missing, zero or conflicting evidence remains `source_vote_for_unresolved`, which prevents derivation. Candidate parties use canonical codes and retain conflicts. Incumbency comes from existing candidate-side evidence and is preserved with provenance; the results feed does not establish it.

Multiple write-in choices are combined into the one write-in natural key per contest. `write_in_components` retains each named/unnamed component. A narrow reconciliation correction, `write_in_reaggregation`, accounts for an old NC row containing only one of those components due to the previous overwrite behavior. The report records old and corrected totals. Other unexplained vote differences block application.

## Command and review contract

Run from `backend/` using Python 3.13 and PostgreSQL:

```bash
python manage.py repair_nc_contest_identity \
  --election-id 1997 \
  --race-id 21825 --race-id 21734 \
  --report /tmp/nc214-review.json
```

Omit `--race-id` to inventory the whole election. A selected race expands to its entire connected duplicate/split component; an operator cannot retire half a merged race. This example covers Senate District 01 and Governor. On the inspected snapshot it selected three old races and two contests: Senate races 21825/49844 merge into filing race 49844; Governor race 21734 receives sourced candidate party without inventing a second Governor record.

The command downloads the official ZIP directly, bypassing ETag/cache, validates source election dates, and computes SHA256. `--source-file /path/to/official.zip` supports a reproducible offline rehearsal. The source checksum and current election/race/candidate/option/result/source-record/mock-vote state participate in the fingerprint.

Review the complete JSON, including:

- `race_mapping`, `candidate_mapping`, and `option_mapping`;
- each group's canonical race ID or proposed creation;
- `vote_reconciliation`, including every permitted write-in correction;
- source winner flags, provenance conflicts and relationship blockers;
- `inventory.merged_races` versus `inventory.unresolved_race_splits`;
- `conflicts`, which must be empty for the selected scope.

Apply only a reviewed report, using a separate output file:

```bash
python manage.py repair_nc_contest_identity \
  --election-id 1997 \
  --race-id 21825 --race-id 21734 \
  --apply --approved-report /tmp/nc214-review.json \
  --report /tmp/nc214-applied.json
```

Apply refetches source data, locks the election and its races, rebuilds the plan and rejects a changed source/database fingerprint. The update is transactional, including failure to write the applied report. A repeated dry-run produces the current fingerprint; a repeated apply of an already-current plan preserves result IDs and values. Changes anywhere in the inspected election require a new review.

Conflicts hold the selected component. Resolve source-name/party/seat/electorate disagreement with evidence, then rerun the dry-run. A source-set winner on a merged result cannot be copied across newly split contests. Ambiguous source-record or mock-vote mappings also block apply. Incumbency/identifier conflicts are retained for review rather than overwritten.

## Retirement and API behavior

The candidate-side race is preferred as survivor when its identity is supported. Its filing canonical key and existing candidate detail are preserved. Source records and mock-vote selections are remapped only when the destination is unambiguous. Per-contest vote reconciliation precedes result replacement.

Superseded races and candidates remain audit records. Their totals are retired, their canonical keys released, and `source_metadata.nc_superseded_by` records replacement race IDs. The API excludes these tombstones from race/candidate/detail/result endpoints and election counts. Winner derivation skips superseded records; scheduled ingestion excludes them. A database rollback restores the original rows and relationships together.

Winner derivation uses verified identity and sourced seats while retaining #218 source precedence, historical nomination thresholds, tie/write-in restrictions and classification skips. `Election.needs_review`, unsupported election types, unresolved party/seat/electorate evidence and unsupported nomination rules remain skipped. Repair does not rekey or reclassify elections (#188), and it does not automatically run winner derivation.

## Production rollout and rollback

The reviewed implementation and snapshot rehearsal do not apply changes to production. Before a production pilot:

1. Merge/deploy #218 and this change through the normal local Compose workflow at `/data/DockerConfigs/CivicMirror`. Preserve the prior API/worker image tags for rollback.
2. Pause the NC candidate/results schedules and workers for the maintenance window. Keep the API available for read verification. The command still rejects concurrent database changes through its fingerprint/locks.
3. Create a PostgreSQL custom-format backup outside the repository and verify it with `pg_restore --list`. Record the snapshot time and matching application image IDs. For the local database container:

   ```bash
   docker exec civicmirror-postgres sh -c \
     'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
     > /path/to/backup/nc214-before.dump
   pg_restore --list /path/to/backup/nc214-before.dump > /path/to/backup/nc214-before.list
   ```

4. Run the scoped command inside the deployed API container, copy the review report to the operator, and review the actual mapping, totals and conflicts. Use the production report for application; a snapshot report has a different database fingerprint.
5. Apply that exact scope/report. Verify the applied audit, combined API race/candidate details, certification, per-choice vote counts, source-set winners and relationship integrity. Check that the retired race has no served results and no duplicated race/candidate counts.
6. Run `python manage.py derive_winners --dry-run --state NC` and compare remaining skip reasons. Review any separate winner backfill before applying it. Run a fresh repair dry-run to confirm idempotence, then restore schedules.
7. Expand to additional reviewed connected components. Keep unresolved electorates, names, source discrepancies and nomination outcomes in their reports. Close #223 only after the live API outcome is verified.

For rollback, quiesce writes and restore the database backup with the matching prior application images. Restore keys, candidates, results, mock votes and source links together:

```bash
docker exec -i civicmirror-postgres sh -c \
  'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < /path/to/backup/nc214-before.dump
```

Verify local Compose health and the API, then resume schedules. A whole-database restore returns the database to its backup time, so the maintenance window must account for writes after that snapshot.

## Validation evidence

The 2026-10-26 read-only production snapshot contained 18,639 NC races: 16,466 results-adapter records and 2,173 filing records. It also contained 171 NC source-record links and no NC mock votes. Existing winner outcomes, using the deployed pre-change rules, were 2,022 derived; 10,985 ambiguous; 2,734 unpartitioned primary; 329 unknown seats; 87 missing totals; 306 measures; 2,175 not certified; and one zero-vote contest. These counts describe the baseline rather than a target number of winners.

The snapshot and fresh official-source reports were rehearsed in a separate PostgreSQL database; production was read only. Focused regressions cover county collisions, multi-county state/district/local contests, unknown electorate aliases, party separation, sourced/unknown seats, identity mismatch, filing refresh, invalid votes, source True/False outcomes, duplicate merging, split conservation, write-in correction, measure conversion, stale review rejection, transaction rollback, relationship preservation and API output. See the PR validation output for the final suite counts and snapshot pilot result.
