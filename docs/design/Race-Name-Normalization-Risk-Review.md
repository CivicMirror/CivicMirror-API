# Race Name Normalization — Risk Review

Review of `Race-Name-Normalization.md` (proposed plan). The normalization core
(geo-qualifier regex + `_normalize_ocd` + civic mapper fallback fix) is sound,
and choosing normalize-at-write over a two-pass fuzzy lookup is the right call.
The risk concentrates almost entirely in (a) the backfill command and (b) the
ballot-measure over-merge case. Items are ordered roughly by severity.

---

## 1. Over-merge risk on ballot measures (highest)

The design assumes the OCD division ID is the geographic disambiguator and the
title qualifier is redundant noise. That holds for **statewide candidate
offices** — there is exactly one Governor per state per election, so collapsing
`"Governor - Statewide Results"` → `governor` is unambiguously correct.

It does **not** obviously hold for **local ballot measures**. Titles like
`"Measure A"` or `"Proposition 1"` often rely on a geographic qualifier
(`- Citywide`, `- Countywide`) to distinguish a city Measure A from a county
Measure A *in the same election*. If both lack a real `ocd-division/...` ID and
carry only a state-code fallback, then after the two fixes they normalize to the
same `election_key|measure a|NO_OCD|measure` — and the backfill will merge two
genuinely distinct contests.

- The plan validates against CA Governor, the cleanest possible case, which will
  never surface this.
- **Mitigation:** before the live run, inspect the dry-run *collision groups*
  (not just the count) for any group whose members differ only by a stripped
  qualifier and both have `NO_OCD`. That is where a false merge hides.
- **Open question:** should `_GEO_QUALIFIER_RE` apply at all when
  `race_type == "measure"`? Consider restricting qualifier stripping to
  candidate races.

---

## 2. Backfill command needs more safety machinery than specified

The destructive path is described only at the algorithm level. Production
concerns not addressed in the plan:

- **Atomicity.** Each group's merge (remap `OfficialResult` / `MeasureOption`
  FKs, merge sources, update key, delete loser) must run inside a single
  `transaction.atomic()` block so a partial failure cannot leave results
  pointing at a deleted race.
- **Result-row conflicts.** When a loser's results move onto the winner
  candidate, the winner may already hold a result for that candidate/round.
  There must be an explicit conflict policy (skip, flag, or merge counts) rather
  than a blind reassignment. *(Confirmed against the model: `OfficialResult` has
  no relevant unique constraint, so this produces no `IntegrityError` — it
  silently creates logically duplicate result rows. Detect-and-flag; do not
  auto-sum vote counts in a backfill.)*
- **Candidate identity mapping.** "Call `ingest_candidate` then update
  `candidate_id`" only works with a reliable loser→winner candidate map. If
  matching is name-based, cross-source name variance (`"Robert Smith"` vs
  `"Bob Smith"`) will mis-map or fail to map. The merge must be explicit about
  how it resolves this and what it does when a loser candidate has no winner
  match. *(Confirmed: `Candidate` has `unique_candidate_name_per_race` and
  `MeasureOption` has `unique_measure_option_per_race` — these are the real
  collision surfaces, not results. Use a move-or-merge rule: reassign the FK
  when the winner has no equivalent row; merge fields + remap when it does.)*
- **Audit trail.** Deletes are irreversible and `--dry-run` does not help after
  the fact. Log every `(loser_race_id, loser_canonical_key) → (winner_race_id,
  new_key)` plus candidate/option remaps, ideally to a file, so a bad merge is
  diagnosable and reconstructable.

---

## 3. Deployment race window

"Deploy, then immediately run the command before the next scheduler fires"
leaves a window: if any sync fires between deploy and backfill completion, it
writes duplicates under the new normalization.

- **Mitigation:** pause the relevant schedulers, deploy, backfill, verify, then
  resume. This removes the timing dependency entirely rather than racing it.

---

## 4. `ingest_candidate` / single-source assumption

The plan proposes merging loser candidates by calling
`ingest_candidate(race=winner, ...)`. But candidates carry **no single source
field** — only `contributing_sources` and `field_provenance`. Re-applying a
loser candidate's merged field dict under one chosen source flattens per-field
provenance and can let a low-precedence value win because it was tagged with a
high-precedence source.

- **Mitigation:** do a provenance-aware field merge (compare each field's owning
  source rank donor-vs-target, copy on strict out-rank) instead of routing the
  whole dict through `ingest_candidate` under a single source.

---

## 5. Smaller code-level notes

- **`_normalize_ocd` should `.strip()`** before the state-code set check —
  `" CA "` will not match `_US_STATE_CODES` as written.
- **Territories omitted.** `_US_STATE_CODES` lacks PR, GU, VI, AS, MP. If
  `election.state` ever held a territory code as the old fallback, those will
  not be normalized in the backfill. A quick query against existing data
  confirms whether any exist.
- **Mapper `AttributeError`.** `contest.get("district", {}).get("id")` raises if
  `"district"` is present but explicitly `null` (the `{}` default only fires on
  a *missing* key). Pre-existing, but free to fix while touching that line.
- **Regex trailing-period miss.** `_GEO_QUALIFIER_RE`'s `$` anchor will not
  match `"... - Statewide Results."` (trailing period). Likely fine for real
  data; a silent miss if sources are inconsistent.
- **Idempotency claim.** Holds *only if* `race_canonical_key` is fully
  deterministic and stored keys exactly equal the recompute after run one. Add
  an explicit test that a second run on post-merge state is a no-op.

---

## 6. Unique-key update ordering (works — documented so nobody "fixes" it)

The collision-group logic is safe, and it is worth recording *why* so a later
change does not break it: within a group, each loser keeps its old distinct
stored key right up until deletion, so setting `winner.canonical_key = new_key`
never collides with a loser **provided losers are deleted before the winner's
key is set**. The only remaining collision possibility is `new_key` matching a
race *outside* the group (e.g., excluded by a `--state` filter) — unlikely, but
a reason to wrap the merge in a transaction and catch `IntegrityError` (roll
back the group, flag for review) rather than assume.

---

## Decision summary

| Area | Verdict |
|------|---------|
| Normalization core (regex, `_normalize_ocd`, mapper fix) | Sound — ship as designed |
| Normalize-at-write vs two-pass fuzzy lookup | Correct choice |
| Title stripping for candidate offices | Safe |
| Title stripping for measures | **Needs decision (item 1)** |
| Backfill command | **Hardening required (items 2, 4)** |
| Deployment sequencing | **Pause schedulers (item 3)** |
| Stored-key recompute before next sync | Essential — already flagged in plan |
