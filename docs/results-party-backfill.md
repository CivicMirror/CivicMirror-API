# Results party metadata backfill (#215)

`backfill_result_parties` reports exact proposed assignments as JSON and defaults
to dry-run. `--apply` opts into metadata writes under a race lock. The command
does not change result totals, source flags, contest identities, election types,
or CT fusion aggregation, and does not run winner derivation.

```sh
python manage.py backfill_result_parties --state PA > /tmp/pa-party-plan.json
python manage.py backfill_result_parties --state PA --apply > /tmp/pa-party-applied.json
python manage.py derive_winners --dry-run --state PA --samples 20
```

Review the report before application. Deployment, metadata application and
winner backfill are separate operations. Winner backfills depend on #213's
source takeover and nomination safeguards (PR #218).

## Evidence rules

- CT primary race party comes from the existing contest/party identity. The
  same identity supplies candidate party; different primary identities remain
  separate. General-election fusion lines are not reinterpreted as primaries.
- GA primary/runoff suffixes and candidate payload party must agree when both
  exist. Missing suffixes do not justify a party-specific race assignment.
- PA candidate party is reconciled across stored result fragments, including
  county-only metadata. New aggregates carry canonical party when consistent,
  or preserve an explicit list of conflicting labels. No votes are re-summed by
  the backfill.
- MO payload party is usable only when the source election matches. The current
  adapter is restricted to its supported 2024-11-05 general election.
- Existing nonblank fields are preserved. Conflicts and missing evidence appear
  in the report and `source_metadata.results_party_unresolved`, which prevents
  primary winner derivation from treating a known race party as resolution of
  conflicting candidate evidence. Missing fields receive canonical party codes
  with field provenance; other provenance and source metadata are preserved.

Bootstrap uses the same planner for these four states. Reapplying a plan's
effects produces no further writes. Unknown party codes remain distinct and
may still be unsupported by the nomination rule; party capture is not proof of
nomination eligibility.

Normal result ingestion runs the planner again after matching incoming rows and
before optional winner derivation. A corrected source party can therefore add a
previously missing assignment, or record `results_party_unresolved` and clear
derived ownership before the derivation guard runs. Later corrections do not
leave a stale party marker in place.

## Read-only audit, 2026-10-05

Public race, candidate, provenance and result metadata were exported from local
production in a read-only transaction. The planner and pure winner derivation
were evaluated locally, including a second pass verifying no further changes.
No production metadata or result flags were written.

| State | Candidate races | Candidate assignments | Race assignments | Unresolved races | Unpartitioned skips before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| GA | 544 | 697 | 451 | 93 | 544 → 93 |
| PA | 401 | 1,230 | 0 | 0 | 325 → 0 |
| CT | 17 | 38 | 17 | 0 | 17 → 0 |
| MO | 4 | 0 | 0 | 4 | 4 → 4 |

Projected winner outcomes after the metadata plan:

- GA: 421 derived; 24 below nomination threshold; 93 missing party evidence;
  4 unknown seats; 2 ambiguous contest identities. Ten ballot measures in the
  export were excluded from party planning and remain measures.
- PA: 247 derived (including 76 already derived), 150 ambiguous contests, and
  4 unknown seat counts.
- CT: 15 derived and 2 ambiguous contests. All 17 retain their existing
  contest/party split.
- MO: all 4 remain unresolved. Races 56540–56543 are attached to the
  2026-08-04 primary but every stored result points to
  `https://www.sos.mo.gov/CMSImages/ElectionResultsStatistics/2024GeneralElection.pdf`.
  Their results require source/election repair before nomination is considered.
  The adapter now rejects requests outside that PDF's date and election type,
  before fetching or checking its cached checksum.

These are snapshot counts, not deployed changes. Remaining GA unknowns, PA/CT
identity ambiguity, and the mismatched MO source are intentionally not guessed.
