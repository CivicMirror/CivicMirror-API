# NC election jurisdiction and classification

NC classification preserves jurisdiction, phase, special context and evidence confidence separately. `Election.election_type` remains the compatibility projection: primary/primary-runoff phases retain those types, an ordinary municipal general projects to `municipal`, and a special general projects to `special`. The API's `classification` field exposes the independent dimensions and `confirmed`, `inferred` or `held` evidence status.

Regular state dates use exact historical primary dates and the applicable regular calendar. Bare ENRS folders no longer make every non-March/May/November date a special election. Known special/second-primary/rerun exceptions are scoped to their contests. `UNEXPIRED` in an official contest title or an explicit TRUE filing flag permits inferred special context; no marker does not prove an election is regular. Missing/conflicting jurisdiction or phase remains held.

## Municipal defaults and later dates

A resolved November municipal contest without applicable contrary evidence is inferred general, with research pending. Known special context remains independent. Other unresolved municipal dates await the announced follow-up; they are not inferred special merely because they fall outside November.

`backend/integrations/nc_sbe/evidence/municipal_dates.json` is initially empty. Follow-up evidence can add exact, sourced overrides:

```json
[
  {
    "municipality": "OFFICIAL UPPERCASE MUNICIPALITY NAME",
    "date": "YYYY-MM-DD",
    "phase": "general_runoff",
    "source_url": "https://official.example/election-notice"
  }
]
```

Supported phases are `primary`, `primary_runoff`, `general`, and `general_runoff`. Records apply only to that place/date. Conflicting overrides hold the assignment. A conditional runoff date does not create an event by itself. Evidence changes invalidate NC results-cache validity; confidence-only promotion does not change event identity.

The bundled NC OSBM name reference only normalizes municipality names and office qualifiers, for example Bessemer City versus a generic “city council” label. It establishes neither election dates/methods nor historical boundaries. County reporting is not proof of a county electorate. Existing NC electorate/contest identity safeguards still apply.

## Ingestion and compatibility

Regular state calendar events can be discovered before results exist. Current/future filing rows materialize resolved jurisdiction-scoped events; candidate creation keeps its existing federal/state office scope. Results are filtered to the classified event before bootstrap. Filing hints preserve unexpired context when a results title omits it.

Legacy records require explicit repair. Existing unkeyed state records retain their `e{pk}` race-key namespace through a virtual event-key alias until repair, avoiding duplicate results-side races. Lower-evidence NC sources cannot recreate an ambiguous bare-key date bucket beside classified events.

Future-dated archives are pre-election evidence and are not persisted as results. Preview reports explicitly list `pre_election_resets` when a source-matched, zero-vote future race was previously certified or archived. Approved application restores those races/events to upcoming/active and marks their existing zero-vote rows unofficial with no certification timestamp. IDs, relationships and vote values stay intact. Nonzero future results or source-set winners require review instead of automatic lifecycle correction.

Retired split parents disappear from ordinary election lists and ZIP lookup but retain detail responses with replacement IDs. Parents with unresolved historical components remain review containers. Held race records, source-set winners, candidate/result IDs and result values are preserved; ordinary ingestion and derivation skip those held components.

## Preview, rehearsal and application

Run from `backend/` using Python 3.13 and an explicitly verified database/cache environment:

```sh
python manage.py repair_nc_election_classification --all-nc --dry-run --report /private/preview.json
python manage.py repair_nc_election_classification --all-nc --apply --approved-report /private/preview.json --report /private/applied.json
```

For one scope use `--election-id ID` instead of `--all-nc`. `--source-file` and `--filing-file` accept saved official files for a single-Election rehearsal; their bytes participate in the fingerprint. The ordinary path refetches source files. Missing ZIPs are explicit source states and do not authorize replacing results.

Review each supported mapping and hold before apply. The fingerprint covers source contents, implementation/evidence decisions, complete affected database relationships and source links. Apply locks and rebuilds the plan, rejecting changed evidence/state. A report-write failure rolls back that scope. Independent historical identity conflicts stay held instead of being merged as part of classification.

Existing destinations outside a legacy parent's recorded replacements are included in the snapshot and locks. A held destination cannot be unheld by moving another parent's races into it. Candidate refreshes and winner derivation also respect held/tombstoned records.

1. Rehearse against an isolated restored production snapshot with separate cache/broker settings.
2. Compare candidate/result/option/source-record/mock-vote IDs and values, plus every held/superseded race, before and after.
3. Repeat previews/applies and actual syncs against frozen responses to prove stable keys and counts. Rehearse rollback.
4. Drain affected NC writers, verify a fresh backup, regenerate the exact production preview, and apply only its accepted mappings.
5. Deploy coordinated routing/repair code, invalidate affected cache versions and resume controlled then scheduled ingestion. Do not run old month-based writers against corrected keys.
6. Verify API evidence, preserved relationships/results, local Compose health and scheduled convergence; retain private backup/report references.

Production images must preserve the already-deployed KY work. Compare the live baseline of shared files before overlaying the scoped NC change. No raw database dump, candidate contacts or private apply report belongs in Git or public issue comments.
