# Source Aggregation & Normalization Layer

**Date:** 2026-05-27
**Status:** Approved (design) — implementation plan covers Phase 0+1
**Area:** `backend/aggregation/` (new), `backend/elections/`, all source adapters under `backend/integrations/`, `backend/results/`

## Problem

CivicMirror's concept calls for aggregating multiple heterogeneous sources into one
normalized API, with sources **augmenting** each other (`concept.md`: "Build
normalization / deduplication layer" — still unchecked). In practice the ingestion
layer is **source-siloed**:

- `Election.source_id` is globally unique *per source*, so Google Civic's `11255`
  and CA SOS's `ca_sos_2026_primary` become **separate Election rows** for the same
  real election.
- The `Race.canonical_key` **embeds the source and the per-source election id**
  (`civic_api:11255:…` vs `ca_sos_2026_primary:…`), so two sources can **never**
  converge on one Race.
- Candidate identity is per-source as well.

Result: duplicate elections, no field-level merging, and no way to let one source
own some fields (e.g. live results) while another owns others (e.g. candidate
contacts). California is the concrete case: a Google Civic election (id 8, correct
date 2026-06-02, 38 races) coexists with mis-dated empty CA SOS shells
(`ca_sos_2026_primary` dated 2026-03-03, 0 races).

## Goal

Build a **source-agnostic aggregation layer** so that, for any state, multiple
sources merge onto a single canonical Election → Race → Candidate tree with
**field-level source precedence** that is adjustable at runtime. Prove it on
California (Civic + CA SOS), then migrate other states incrementally. New
states/sources onboard by implementing a small adapter contract and adding
precedence rows — no core changes.

## Key decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Precedence config | **DB-configurable, admin-editable** (`SourcePrecedence` table) |
| Canonical Election identity | **Strict natural key**: `state + election_type + election_date + jurisdiction_level`; unmatched source elections kept separate and flagged `needs_review` (no silent dupes) |
| Merge semantics | Per-field provenance; precedence changes take effect on a source's **next sync** |
| Candidate matching | **Exact normalized name + party** within a race (nonpartisan: name only); bias to avoid false merges; mismatches flagged for review |
| Merge architecture | **Shared ingest service (normalize-on-write)** — adapters emit normalized fields + source name; one service applies precedence/provenance |
| Rollout | Generic layer built once; validated on CA; states migrated incrementally |

---

## Architecture

A new package `backend/aggregation/` containing:

- **`identity.py`** — canonical key construction + normalization helpers
  (`normalize_office_title`, `normalize_name`, `normalize_party`, OCD parsing).
- **`precedence.py`** — precedence resolution against the `SourcePrecedence` table,
  with field→field_group mapping and wildcard defaults.
- **`ingest.py`** — the ingest service: `ingest_election()`, `ingest_race()`,
  `ingest_candidate()`. Resolves/creates the canonical row, applies per-field
  precedence + provenance, records contributing sources.

Adapters under `integrations/*` and `results/*` are refactored to **produce
normalized field dicts and call the ingest service** instead of writing models
directly. Each adapter declares only its `source` name; it knows nothing about
precedence.

```
adapter (civic / ca_sos / …)
   │  emits: canonical identity + source name + normalized field dicts
   ▼
aggregation.ingest  ──reads──▶  SourcePrecedence (DB, admin-editable)
   │  per field: if rank(source) outranks current owner → write + set provenance
   ▼
Election / Race / Candidate  (+ field_provenance, contributing_sources)
   └─ ElectionSourceLink (per-source id, results_url, last_synced_at)
```

---

## Data model changes

### Election
- **Add** `canonical_key` (`CharField`, unique, nullable during rollout) =
  `f"{state}:{election_type}:{election_date.isoformat()}:{jurisdiction_level}"`.
- **Add** `field_provenance` (`JSONField`, default `dict`) — `field → source`.
- **Add** `contributing_sources` (`JSONField`, default `list`).
- **Add** `needs_review` (`BooleanField`, default `False`).
- **Demote** `source_id`: drop the `unique=True` (kept for backward-compat reads;
  per-source ids now live on `ElectionSourceLink`). Not removed in Phase 1.

### ElectionSourceLink (new)
`election (FK)`, `source (CharField)`, `source_id (CharField)`,
`results_url (URLField, blank)`, `last_synced_at (DateTimeField)`.
Unique on `(election, source)`. One row per contributing source per election.

### Race
- **Redefine** `canonical_key` (already unique, nullable) source-independent:
  `f"{election.canonical_key}|{normalized_office_title}|{ocd_division_id or 'NO_OCD'}|{race_type}"`.
  Legacy source-scoped keys coexist (different shape, no collision) until a state
  is migrated.
- **Add** `field_provenance` (`JSONField`), `contributing_sources` (`JSONField`).
- `source` field retained = highest-precedence contributing source (for API
  back-compat).

### Candidate
- Identity = `(race, normalized_name, normalized_party)`. Add a
  `normalized_party` column; nonpartisan races match on name only.
- Replace the `(race, name)` unique constraint with `(race, normalized_name,
  normalized_party)` (migration recomputes normalized fields, then adds the
  constraint).
- **Add** `field_provenance` (`JSONField`).

### SourcePrecedence (new, admin-editable)
`state (CharField, default '*')`, `field_group (CharField, default '*')`,
`source (CharField)`, `rank (IntegerField; lower = higher precedence)`.
Unique on `(state, field_group, source)`. Seeded by data migration with the
Civic-first baseline (see Precedence).

---

## Precedence

**Field groups** (the precedence unit, not individual columns) map model fields to
a small set: `identity` (name/title), `date`, `status`, `contacts`
(phone/website/email/photo), `party`, `district` (ocd/jurisdiction/scope),
`results` (vote-bearing fields). The field→group map lives in `precedence.py`.

**Resolution** for `(state, field_group, source)`:
1. Most-specific `SourcePrecedence` row wins: exact `(state, field_group)` >
   `(state, '*')` > `('*', field_group)` > `('*', '*')`.
2. A source with no matching row is treated as **lowest precedence** (it may only
   fill fields that have no current owner).

**Seeded baseline (examples):**
```
('*','*',      'civic_api', 0)   # Civic is the default baseline everywhere
('*','*',      'fec',       1)
('CA','results','ca_sos',   0)   # CA: live results owned by CA SOS
('CA','results','civic_api',1)
('CA','contacts','civic_api',0)  # CA: candidate contacts owned by Civic
('CA','date',  'ca_sos',    0)   # CA: authoritative date from CA SOS catalog
```
"Downgrading" a source for a state = edit a `rank` in admin; effective on that
source's next sync.

---

## Merge algorithm (ingest service)

For an incoming `(canonical_key, source, fields)`:
1. Resolve or create the canonical row by `canonical_key`. If the natural key
   cannot be confidently formed (e.g. missing/garbage date), create/keep the
   source's own row with `needs_review=True` and stop.
2. Record/refresh the `ElectionSourceLink` (source id, results_url, sync time);
   add `source` to `contributing_sources`.
3. For each provided field:
   - `group = field_group(field)`; `incoming_rank = resolve(state, group, source)`.
   - `owner = field_provenance.get(field)`; `owner_rank = resolve(state, group, owner)` (or +∞ if no owner).
   - If `owner is None` **or** `incoming_rank <= owner_rank`: write the value and
     set `field_provenance[field] = source`.
4. Candidates: within the canonical race, match on `(normalized_name,
   normalized_party)`; get-or-create, then merge fields by the same rule. No
   confident match → create separate candidate flagged for review.

Idempotent and order-independent for a fixed precedence config.

---

## Adapter contract

Each adapter exposes a function returning normalized records:
- **election:** `{state, election_type, election_date, jurisdiction_level, name, status, source_metadata…}`
- **race:** `{office_title, ocd_division_id, race_type, …}` (+ election identity)
- **candidate:** `{name, party, contacts…}` (+ race identity)

…and calls `aggregation.ingest.ingest_election/race/candidate(source=<name>, fields=…)`.
A base helper performs normalization (office title, party, OCD, name). Adapters
are migrated one at a time; un-migrated adapters keep their current direct-write
behavior until their state is onboarded.

---

## CA validation (Phase 1) + CA SOS adapter fixes

1. **Catalog file:** fetch `api-endpoints.csv` (lists `https://api.sos.ca.gov/returns/…`,
   matching the REST client) instead of `json-endpoints.csv` (bulk-JSON catalog,
   incompatible with `fetch_contest`).
2. **Parser rewrite** (`integrations/ca_sos/parsers.py`): handle the headerless
   format — line 1 is the base URL, line 2 a title, then bare endpoint URLs
   separated by blanks. Strip `API_BASE` to derive `/returns/…` paths; skip
   `/county/` breakdowns (keep statewide + `/district/N`); reuse existing skip
   patterns for `/status`, files, `/query`.
3. **Date from catalog title:** parse the election date out of the catalog title
   ("…California June 2, 2026 …Primary Election") via regex; fall back to the
   statutory formula only if absent.
4. **Route Civic + CA SOS through the ingest service.**

**Expected end state:** one canonical 2026 CA primary (`2026-06-02`, `state`,
`primary`), races merged across both sources, candidates merged,
`results`←CA SOS, `contacts/district`←Civic, with provenance recorded.

---

## Data migration

A **CA-scoped** one-time migration:
- Backfill `canonical_key`, normalized fields, and provenance for CA rows.
- Merge the duplicate CA primaries (Civic id 8 and CA SOS `ca_sos_2026_primary`,
  plus the `ca_sos_2026_general`) and their races/candidates onto canonical rows;
  create `ElectionSourceLink`s.
- Seed the `SourcePrecedence` baseline + CA overrides.

No global big-bang. Each later state gets its own merge migration when its
adapters are onboarded (Phase 2+). The schema columns are added globally and are
nullable, so un-migrated states are unaffected.

---

## API surface (backward compatible)

- Keep all existing Election/Race/Candidate fields.
- `Race.source` = highest-precedence contributing source (representative value).
- **Add** `sources: [...]` (contributing sources) and optional `field_provenance`
  on Election/Race/Candidate serializers for transparency.
- `race_count` and existing filters unchanged. CivicMirror consumers keep working.

---

## Error handling & edge cases

- **Unmatched / ambiguous election** → kept as its own row, `needs_review=True`,
  visible in admin for manual linking or dismissal.
- **Precedence miss** → fall back through wildcard tiers; unranked source fills
  only empty fields.
- **Party normalization** → map source variants to canonical codes
  (`"Democratic Party"`/`"Dem"`/`"DEM"` → `DEM`); empty party = nonpartisan.
- **Cross-window / partial syncs** → each source updates only the fields it
  outranks; stale values refreshed on that source's next sync.
- **Source stops providing a field** → value persists until re-asserted/cleared on
  re-sync (acceptable per "next sync" semantics).

---

## Testing

- **Ingest service (unit, cache/DB):** precedence resolution (wildcards, most-specific),
  per-field merge + provenance, downgrade-on-next-sync, candidate matching incl.
  party normalization and nonpartisan races, false-merge avoidance.
- **CA SOS parser:** `api-endpoints.csv` parsing, `/county/` filtering, date extraction.
- **CA integration:** Civic + CA SOS → one merged Election/Race/Candidate tree with
  expected field ownership.
- **Migration test:** CA dedup merges existing duplicates correctly and idempotently.
- Local runs use `pytest --no-migrations` (the test DB can't replay the existing
  Postgres-only `RunSQL` migrations on SQLite; CI runs against Postgres).

---

## Phasing

- **Phase 0** — schema (canonical keys, provenance, `ElectionSourceLink`,
  `SourcePrecedence`) + `aggregation/` service + precedence engine. No adapters
  migrated yet.
- **Phase 1** — migrate Civic + CA SOS onto the service; fix the CA SOS adapter;
  CA data migration; validate end-to-end. **← first implementation plan covers
  Phase 0+1.**
- **Phase 2+** — migrate SC (ENR/VREMS), CO, IA, MA, VA, FEC, OpenStates
  incrementally; each its own plan + state-scoped data migration.

## Out of scope (YAGNI)

- Staging tables / instant re-projection without re-fetch (rejected; "next sync"
  semantics chosen).
- Fuzzy candidate matching and an alias table (start exact; revisit if needed).
- GeoJSON/FIPS boundary ingestion, Ballotpedia, Democracy Works (future sources).
- Migrating non-CA states (Phase 2+, separate specs/plans).
