# Source Aggregation & Normalization Layer

**Date:** 2026-05-27
**Status:** ✅ Implemented — Phase 0+1 shipped; Phase 2 (all adapters) complete 2026-05-31
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

## Approach: ground-up clean schema

There is **no user base**, so existing data is disposable and the API contract is
not frozen. We therefore design the schema **canonical-first and clean** rather
than bolting compatibility onto the source-siloed models:

- No legacy data migration. **Wipe the database and re-sync** through the new layer.
- `canonical_key` is the **unique identity**, always populated by the ingest
  service (DB-`null=True` during the incremental rollout so not-yet-migrated
  adapters coexist; tightened to NOT NULL in the Phase-2 finish). Per-source
  ids live on `ElectionSourceLink`. The legacy `Election.source_id` column is
  **demoted to nullable** (kept unique in Phase 1 because un-migrated adapters
  bulk-upsert on it; NULLs are exempt from uniqueness so merged elections coexist).
  The column and its unique constraint are physically **dropped at the end of
  Phase 2** once every adapter is off it.
- The API may change freely (the CivicMirror frontend is updated alongside).
- **Adapters and infrastructure are kept and adapted**, not rewritten from scratch:
  the state-specific HTTP/parsing/proxy logic, scheduler endpoints, auth, API, and
  deployment are valuable and retained. Adapters are rewritten only to call the new
  ingest service.
- Adapters are cut over **one at a time, CA first**. Not-yet-migrated adapters are
  **disabled** (they don't write legacy rows); each repopulates its state's data
  when cut over.

"Fresh migrations" here means clean canonical-first model definitions with new
migrations applied to a wiped database — **not** a squash/reset of the whole
migration history (out of scope; the only thing that would additionally fix is the
local-SQLite test quirk, which is acceptable as-is).

## Key decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Precedence config | **DB-configurable, admin-editable** (`SourcePrecedence` table) |
| Canonical Election identity | **Strict natural key** `state + election_type + election_date + jurisdiction_level`, stored as a **unique** `canonical_key` (DB-nullable during the incremental rollout so not-yet-migrated adapters coexist; **always populated by the ingest service**; tightened to NOT NULL in the Phase-2 finish); unmatched/ambiguous data kept separate and flagged `needs_review` |
| Data handling | **Wipe + re-sync** (no legacy data migration) |
| Merge semantics | Per-field provenance; precedence changes take effect on a source's **next sync** |
| Candidate matching | **Order-independent normalized name + party** within a race (nonpartisan: name only); bias to avoid false merges; mismatches flagged for review |
| Merge architecture | **Shared ingest service (normalize-on-write)** — adapters emit normalized fields + source name; one service applies precedence/provenance |
| Adapters / infra | **Keep & adapt** (rewrite onto the ingest contract); disable until cut over |
| Rollout | Generic layer built once; validated on CA; states migrated incrementally |

---

## Architecture

A new package `backend/aggregation/` containing:

- **`identity.py`** — canonical key construction + normalization helpers
  (`normalize_office_title`, `normalize_name`, `name_match_key`, `normalize_party`).
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

## Data model (clean, canonical-first)

### Election
- `canonical_key` (`CharField`, **unique**, `null=True` during rollout) =
  `f"{state}:{election_type}:{election_date.isoformat()}:{jurisdiction_level}"`.
  Always set by the ingest service; not-yet-migrated adapters leave it NULL
  (multiple NULLs are allowed under the unique constraint). Tightened to NOT NULL
  in the Phase-2 finish.
- **Make `source_id` nullable** (`unique=True, null=True, blank=True`); the unique
  constraint is *kept* in Phase 1 because not-yet-migrated adapters (e.g.
  `sc_vrems`) `bulk_create` with `update_conflicts=True, unique_fields=["source_id"]`
  and require it. NULLs are exempt from uniqueness, so merged elections with
  `source_id=NULL` coexist. Per-source ids live on `ElectionSourceLink`. Migrated
  adapters (CA SOS, Civic) do not set it. The column (and constraint) are dropped
  in the Phase-2 finish.
- Add `field_provenance` (`JSONField`, default `dict`) — `field → source`.
- Add `contributing_sources` (`JSONField`, default `list`).
- Add `needs_review` (`BooleanField`, default `False`).
- Keep `name`, `election_date`, `election_type`, `jurisdiction_level`, `state`,
  `status`, `source_metadata`, `last_synced_at`, `election_cycle`, `results_url`
  (`results_url` owned via the `results` precedence group).

### ElectionSourceLink (new)
`election (FK, related_name='source_links_rel')`, `source (CharField)`,
`source_id (CharField)`, `results_url (URLField, blank)`,
`last_synced_at (DateTimeField, null)`. Unique on `(election, source)`.

### Race
- `canonical_key` (**unique**, `null=True` — unchanged from the current model),
  redefined source-independent:
  `f"{election.canonical_key}|{normalized_office_title}|{ocd_division_id or 'NO_OCD'}|{race_type}"`.
- Add `field_provenance`, `contributing_sources` (`JSONField`).
- `source` retained = highest-precedence contributing source (representative).

### Candidate
- Add `normalized_party` (`CharField`) and `field_provenance` (`JSONField`).
- Semantic dedup is performed by the ingest service via an order-independent
  `name_match_key` + normalized party (nonpartisan: name only). The existing
  `(race, name)` unique constraint is **kept** as a DB backstop.

### SourcePrecedence (new, admin-editable)
`state (CharField, default '*')`, `field_group (CharField, default '*')`,
`source (CharField)`, `rank (IntegerField; lower = higher precedence)`.
Unique on `(state, field_group, source)`. Seeded by migration with the Civic-first
baseline.

---

## Precedence

**Field groups** (the precedence unit, not individual columns) map model fields to
a small set: `identity` (name/title), `date`, `status`, `contacts`
(phone/website/email/photo/description), `party`, `district`
(ocd/jurisdiction/scope), `results` (vote-bearing fields, results_url). The
field→group map lives in `precedence.py`.

**Resolution** for `(state, field_group, source)`:
1. Most-specific `SourcePrecedence` row wins: exact `(state, field_group)` >
   `(state, '*')` > `('*', field_group)` > `('*', '*')`.
2. A source with no matching row is treated as **lowest precedence** (+∞; may only
   fill fields with no current owner).

**Seeded baseline (examples):**
```
('*','*',      'civic_api', 0)   # Civic is the default baseline everywhere
('*','*',      'fec',       1)
('CA','results','ca_sos',   0)   # CA: live results owned by CA SOS
('CA','results','civic_api',1)
('CA','date',  'ca_sos',    0)   # CA: authoritative date from CA SOS catalog
('CA','contacts','civic_api',0)  # CA: candidate contacts owned by Civic
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
4. Candidates: within the canonical race, match on `(name_match_key,
   normalized_party)`; get-or-create, then merge fields by the same rule. No
   confident match → create separate candidate flagged for review.

Idempotent and order-independent for a fixed precedence config.

---

## Adapter contract

Each adapter exposes functions returning normalized records:
- **election:** `{state, election_type, election_date, jurisdiction_level, name, status, …}`
- **race:** `{office_title, ocd_division_id, race_type, …}` (+ election identity)
- **candidate:** `{name, party, contacts…}` (+ race identity)

…and calls `aggregation.ingest.ingest_election/race/candidate(source=<name>, …)`.
A base helper performs normalization. Adapters are cut over one at a time;
not-yet-migrated adapters are **disabled** until their state is onboarded.

---

## CA validation (Phase 1) + CA SOS adapter fixes

1. **Catalog file:** fetch `api-endpoints.csv` (lists `https://api.sos.ca.gov/returns/…`,
   matching the REST client) instead of `json-endpoints.csv` (bulk-JSON catalog,
   incompatible with `fetch_contest`).
2. **Parser rewrite** (`integrations/ca_sos/parsers.py`): handle the headerless
   format — line 1 base URL, line 2 title, then bare endpoint URLs separated by
   blanks. Strip `API_BASE` to derive `/returns/…` paths; skip `/county/`
   breakdowns and `/district/all` (keep statewide + `/district/N`); reuse skip
   patterns for `/status`, files, `/query`.
3. **Date from catalog title:** parse the election date out of the catalog title
   ("…California June 2, 2026 …Primary Election") via regex; fall back to the
   statutory formula only if absent.
4. **Route Civic + CA SOS through the ingest service.**

**Expected end state:** one canonical 2026 CA primary (`2026-06-02`, `state`,
`primary`), races merged across both sources, candidates merged,
`results`←CA SOS, `contacts/district`←Civic, with provenance recorded.

---

## Data reset (replaces a data migration)

Because data is disposable, there is **no merge migration**. Cutover procedure:
1. Deploy the new schema + aggregation layer with only migrated adapters enabled
   (Phase 1: Civic + CA SOS).
2. **Wipe** the elections data (`flush` the relevant tables / fresh DB) to clear
   the old source-siloed rows before re-syncing through the aggregation layer.
3. Apply migrations; the `SourcePrecedence` baseline is seeded by a data migration.
4. Trigger CA syncs to repopulate through the ingest service.
Non-CA states stay empty until their adapters are cut over (Phase 2+).

---

## API surface

The API need not preserve backward compatibility (no users); the CivicMirror
frontend is updated alongside. Concretely:
- `Election` exposes `sources` (contributing sources, from `contributing_sources`)
  and optional `field_provenance`; the deprecated `source_id` may remain on the
  serializer until the column is dropped in Phase 2.
- `Race`/`Candidate` serializers gain `sources` / `field_provenance`.
- Keep changes otherwise minimal to limit frontend churn.

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

---

## Testing

- **Ingest service (unit):** precedence resolution (wildcards, most-specific),
  per-field merge + provenance, downgrade-on-next-sync, candidate matching incl.
  order-independent name key, party normalization, nonpartisan races,
  false-merge avoidance.
- **CA SOS parser:** `api-endpoints.csv` parsing, `/county/` + `/district/all`
  filtering, date extraction.
- **CA integration:** Civic + CA SOS → one merged Election/Race/Candidate tree with
  expected field ownership.
- Local runs use `pytest --no-migrations` (the test DB can't replay the existing
  Postgres-only `RunSQL` migrations on SQLite; CI runs against Postgres).

---

## Phasing

- **Phase 0** — canonical-first schema (unique `canonical_key`, nullable during
  rollout; provenance; `ElectionSourceLink`; `SourcePrecedence`; demote
  `Election.source_id` to nullable/non-unique) + `aggregation/` service +
  precedence engine. No adapters migrated yet.
- **Phase 1** — migrate Civic + CA SOS onto the service; fix the CA SOS adapter;
  wipe + re-sync; validate end-to-end. **← first implementation plan covers Phase 0+1.**
- **Phase 2+** — migrate SC (ENR/VREMS), CO, IA, MA, VA, FEC, OpenStates
  incrementally; each its own plan; disabled until cut over. **Finish:** once all
  adapters are migrated, drop the `Election.source_id` column and tighten
  `canonical_key` to NOT NULL.

## Out of scope (YAGNI)

- Squash/reset of the full migration history across apps.
- Legacy data migration / merging existing rows (wipe + re-sync instead).
- Staging tables / instant re-projection without re-fetch ("next sync" chosen).
- Fuzzy candidate matching and an alias table (start exact; revisit if needed).
- GeoJSON/FIPS boundary ingestion, Ballotpedia, Democracy Works (future sources).
- Migrating non-CA states (Phase 2+, separate plans).
