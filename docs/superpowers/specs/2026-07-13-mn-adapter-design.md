# Minnesota (MN) Adapter — Design Spec

**Date:** 2026-07-13
**Status:** Approved, not yet implemented

## Context

MN is the next state slated for adapter work after IL and NJ (per the phase-3 build order; GA and IL have since shipped). Prior research (`docs/state-research/MN/MN-Election_Research.md`, revised 2026-07-12) established that Minnesota publishes strong official Stage 1 (candidate filing) and Stage 2 (election-night results) sources with no authentication required, via the Secretary of State's `electionresults.sos.mn.gov` / `electionresultsfiles.sos.mn.gov` properties.

## Live Recon Findings (2026-07-13)

Fetched the Nov 5, 2024 general election's file index (`electionresults.sos.mn.gov/Select/MediaFiles/Index?ersElectionId=170`) and several of the underlying `.txt` files (`electionresultsfiles.sos.mn.gov/20241105/*.txt`) live, to validate the research doc's described format against real bytes rather than trusting prose.

**Confirmed: MN's downloadable files use a 16-field positional semicolon format, exactly matching the research doc's documented layout:**

```
state;county_id;precinct_name;office_id;office_name;district;candidate_order_code;candidate_name;suffix;incumbent_code;party;precincts_reporting;total_precincts;candidate_votes;candidate_pct;total_office_votes
```

Example (`ussenate.txt`, a "Statewide" file):
```
MN;;;0102;U.S. Senator;;0301;Rebecca Whiting;;;LIB;4103;4103;55215;1.73;3189323
MN;;;0102;U.S. Senator;;0202;Amy Klobuchar;;;DFL;4103;4103;1792441;56.20;3189323
```

**Critical finding: these files are already pre-aggregated to their file's stated granularity — no precinct-level summing is required for the Federal+State scope.** Every row in `ussenate.txt` (a "Statewide" file) shows `precincts_reporting == total_precincts == 4103`, i.e., final statewide totals per candidate, not one row per precinct. The same holds for the "by District" files (`ushouse.txt`, `stsenate.txt`): each district's rows are already summed across that district's precincts. This is a materially simpler shape than Illinois, whose CSVs are genuinely precinct-level and require a custom aggregation pass (`il_aggregate.py`). MN needs no equivalent aggregation module for this scope — each in-scope file's rows map directly to `ResultRow`s.

**Confirmed write-in convention:** candidate_order_code `9901` = write-in (matches research doc), e.g. `MN;;;0102;U.S. Senator;;9901;WRITE-IN;;;WI;4103;4103;3578;0.11;3189323`.

**Confirmed candidate table format** (`cand.txt`, 7-field positional semicolon):
```
candidate_id;candidate_name;office_id;office_title;county_id;order_code;party
```
Example: `01020202;Amy Klobuchar;0102;U.S. Senator;88;02;DFL` — the 8-character candidate ID and `office_id` values (`0102`) match the ones used in the results files, confirming `office_id` is the stable join key between `cand.txt` and the result files.

**Confirmed the file-index page's downloadable-file labels are stable, human-readable, and sufficient for scope classification.** The Nov 2024 index page lists (label → filename):

| Label | Filename | Granularity |
|---|---|---|
| U.S. President Statewide | USPres.txt | Statewide |
| U.S. Senator Statewide | ussenate.txt | Statewide |
| U.S. Representative by District | ushouse.txt | By district |
| State Senator by District | stsenate.txt | By district |
| State Representative by District | LegislativeByDistrict.txt | By district |
| Supreme Court and Courts of Appeals Races | judicial.txt | Statewide (per-seat) |

No Governor/state executive file exists in the Nov 2024 general (off-year for MN's governor — next is 2026), so its exact label is unconfirmed; the adapter should match it by pattern (`"Governor"` in the label) when it appears in a future cycle rather than requiring it to exist now.

Every other label on the page (County Races, Municipal/Hospital/School races and questions, Constitutional Amendment, precinct-level variants, supporting lookup tables) is out of scope for this build and is simply never matched — no per-row office filtering is needed within an in-scope file, unlike IL's `is_federal_or_state_office` row-level check, because MN's file-splitting already does that separation at the file level.

**Confirmed bot-protection gap, and that it's not a blocker:** `electionresults.sos.mn.gov/Results/MediaFileLayout/Index` (the human-facing field-layout documentation page) returns a `302` behind Radware/perimeter bot-detection JS (`validate.perfdrive.com`) — a similar family of issue to OH SOS's Cloudflare block, but on a page this adapter doesn't need. The file-index page (`Select/MediaFiles/Index`) and every actual `.txt` data file (on the separate `electionresultsfiles.sos.mn.gov` host) returned `200` cleanly with a plain browser User-Agent and no challenge. The field schema above was reverse-engineered from live files instead of relying on the blocked layout doc, and matches the research doc's independently-documented field list exactly — cross-validated, not guessed.

**Confirmed `PartyTbl.txt` format** (party abbreviation lookup, not strictly required since result/candidate files already carry the abbreviation inline, but useful for display names): `abbreviation;full_name;order_code`, e.g. `DFL;Democratic-Farmer-Labor;02`.

## Decisions

1. **Scope: Federal + State offices only for v1** — President, US Senate, US House, State Senate, State House, and statewide judicial (Supreme Court, Court of Appeals). Governor/state executive included when present in a given election's file set (not this build's POC election). County, municipal, school, hospital-district races, ballot questions/constitutional amendments, and district court races are explicitly deferred as documented future work — same posture as IL's Federal+State-only v1 and NJ's off-platform-county deferral.
2. **Historical POC first.** Build and validate entirely against the Nov 5, 2024 general election (`ersElectionId=170`, files under `electionresultsfiles.sos.mn.gov/20241105/`). Live discovery of `ersElectionId` for future elections (2026 primary/general) is explicitly deferred to a follow-up — the POC election's ID and date path are hardcoded into fixtures and initial manual `Election.source_metadata`, not resolved dynamically. This matches the research doc's own recommended sequencing and de-risks the parser against real, stable data before touching a moving live target.
3. **No aggregation module needed for this scope**, per the recon finding above — MN's statewide/by-district files are already fully summed. `mn_sos/parsers.py` parses rows directly into `ResultRow`s; unlike `il_aggregate.py`, there is no precinct-summing pass.
4. **File-level scope classification, not row-level.** `mn_sos/mappers.py` classifies index-page *labels* (not individual result rows) against a fixed known-labels set. This is simpler than IL because MN's own file-splitting already separates office categories, unlike IL's single mixed CSV-per-office needing row inspection.
5. **New `Race.Source.MN_SOS` choice**, following the existing per-state enum pattern in `elections/models.py`.

## Architecture

### 1. `backend/integrations/mn_sos/` (Stage 1)

New Django app, modeled on `il_sbe`:

- **`client.py`**: `fetch_file_index(ers_election_id: int) -> str` (fetches the `Select/MediaFiles/Index` HTML page); `fetch_result_file(url: str) -> str` (fetches a `.txt` file from `electionresultsfiles.sos.mn.gov`); `fetch_candidate_table(date_path: str) -> str` (fetches `cand.txt`). All requests use a standard browser User-Agent (confirmed necessary/sufficient — no further bypass required).
- **`parsers.py`**:
  - `parse_file_index(html: str) -> list[dict]` → `{label, url}` pairs, parsed from `<a class="downloadlink">` elements (confirmed structure).
  - `parse_result_file(text: str) -> list[dict]` → parses the 16-field positional semicolon format into dicts (`state, county_id, precinct_name, office_id, office_name, district, candidate_order_code, candidate_name, suffix, incumbent_code, party, precincts_reporting, total_precincts, candidate_votes, candidate_pct, total_office_votes`).
  - `parse_candidate_table(text: str) -> list[dict]` → parses `cand.txt`'s 7-field format into dicts (`candidate_id, candidate_name, office_id, office_title, county_id, order_code, party`).
- **`mappers.py`**:
  - `IN_SCOPE_LABELS`: fixed set/pattern list of the Federal+State statewide/by-district labels documented above (including a `"Governor"`-substring pattern for future cycles).
  - `is_in_scope_file(label: str) -> bool`.
  - `is_write_in(candidate_order_code: str) -> bool` (`== "9901"`).
- **`tasks.py`**: `sync_mn_races` (Celery task) — fetches the file index + candidate table for the tracked election, filters to in-scope files, enumerates distinct `(office_id, office_name, district)` tuples from those files to create/update `Race` rows, and joins `cand.txt` rows by `office_id` to create/update `Candidate` rows (party from the inline `party` field). Snapshot/upsert semantics — no hard-deletes on candidates that disappear between runs (mirrors MN's own documented candidate lifecycle guidance and NJ/IL precedent).

### 2. `backend/results/adapters/mn.py` (Stage 2)

`MinnesotaAdapter(StateResultsAdapter)`:

- Reads `election.source_metadata["mn_ers_election_id"]` and `["mn_date_path"]` (populated by Stage 1, or manually seeded for the POC election). If absent, return an empty `AdapterResult` with `mapping_confidence="none"` and an explanatory note — standard graceful-failure posture.
- Fetches the file index, filters to in-scope files via `mn_sos.mappers.is_in_scope_file`, fetches each in-scope `.txt` file, and parses each row directly into a `ResultRow` (`candidate_name`, `vote_count` from `candidate_votes`, `vote_pct` from `candidate_pct`, `office_title` from `office_name` + `district` when present, `is_write_in_aggregate` when `candidate_order_code == "9901"`).
- **Version/change detection**: checksum over the concatenated bytes of all fetched in-scope files this run, cached and compared the same way IL does (`hashlib.md5`, `django.core.cache`, write-after-success-only).

### 3. `elections/models.py`

Add `MN_SOS = 'mn_sos', 'Minnesota SOS'` to `Race.Source`. New migration.

## Error Handling

- Missing `mn_ers_election_id`/`mn_date_path` metadata → empty `AdapterResult`, `mapping_confidence="none"`, explanatory note.
- A single in-scope file failing to fetch (network error, 404, unexpected format) → log and skip that file, continue with the rest — never let one bad file abort the whole run (same posture as every other multi-file adapter in this codebase).
- Unrecognized/malformed rows (wrong field count) → log and skip the row, don't raise.

## Testing

- Fixture-based tests using real files already captured during recon (`mn_index.html`, `ussenate.txt`, `USPres.txt`, `ushouse.txt`, `judicial.txt`, `cand.txt`, `PartyTbl.txt`) — not synthetic data.
- Unit tests for `parse_file_index` against the real index HTML — must extract all confirmed labels/URLs, and must not include any out-of-scope label as in-scope.
- Unit tests for `parse_result_file` against real `ussenate.txt`/`ushouse.txt`/`judicial.txt` fixtures — verify field mapping, write-in detection (`9901`), and that statewide vs. by-district rows both parse correctly.
- Unit tests for `parse_candidate_table` against real `cand.txt` — verify the 8-char candidate ID and `office_id` join key.
- Unit tests for `is_in_scope_file` covering all six confirmed in-scope labels plus representative out-of-scope labels (County Races, Municipal Questions, precinct-level variants) and the Governor-pattern-match case.
- No live network calls in CI.

## Binding lesson from the IL build (apply here up front, don't rediscover it)

IL's trigger endpoint shipped without an entry in `backend/internal/task_locks.py`'s `TASK_LOCKS` registry, causing a live 500 on first real invocation — caught only during post-merge manual verification. **The task that wires the MN trigger endpoint must add a `TASK_LOCKS["sync_mn_sos"]` entry in the same commit**, and the plan must include a live-trigger verification step before considering the endpoint done. (Also note: since the last IL incident, `backend/internal/tests/test_clear_task_locks.py` now derives its expected registry from source rather than a hardcoded list — see commit `4563ac6` — so a missing entry should now also surface as a test failure, not just a runtime 500. Confirm this test still catches the MN case during implementation.)

## Out of Scope (this build)

- Live election discovery (resolving `ersElectionId` for elections other than the Nov 2024 POC).
- County, municipal, school, hospital-district races and their candidates.
- Ballot questions and constitutional amendments.
- District court races.
- Official certification (State Canvassing Board / county canvassing records).
- GIS/precinct geography.
- Ranked-choice voting municipal adapters.
