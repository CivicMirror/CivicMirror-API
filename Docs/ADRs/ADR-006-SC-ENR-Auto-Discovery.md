# ADR-006: SC ENR Election Auto-Discovery Integration

## Status
Proposed

## Context

South Carolina's Election Night Reporting (ENR) system runs on Clarity Elections, hosted at `https://www.enr-scvotes.org/SC/`. The CivicMirror-API already has:

- `backend/integrations/sc_vrems/` — scrapes candidate/filing data from VREMS
- `backend/results/adapters/sc.py` + `clarity.py` — fetches election-night results from Clarity ENR

The **gap**: `Election.results_url` (the URL the Clarity adapter reads) is currently set **manually in Django admin**. The SC ENR system exposes a documented, unauthenticated JSON discovery API:

```
GET https://www.enr-scvotes.org/SC/elections.json
```

This returns all currently-published elections with their EIDs. The EID is the only value needed to construct the ENR navigation URL (`/SC/{EID}/`), which resolves server-side to the full `web.XXXXXX` path required by the Clarity adapter.

### Requirements
- Auto-discover SC ENR elections from `elections.json` on a schedule
- Resolve EIDs to full `web.XXXXXX` URLs (needed for `current_ver.txt` and `summary.json`)
- Populate `Election.results_url` so the existing `ClarityAdapter` works without manual admin entry
- Link ENR entries to existing `Election` records (created by `sc_vrems`) where possible

### Constraints
- ENR ↔ VREMS have **no shared ID** — join must use `election_date + state`
- `elections.json` returns `[]` off-season — no active elections currently published
- The site blocks non-browser User-Agents (already handled by `_CLARITY_HEADERS` in `clarity.py`)
- GCP Cloud Run IPs are blocked by CloudFront — handled by CF Worker proxy (`CLARITY_PROXY_HOSTS`)
- Historical elections are NOT in `elections.json` — feed only shows currently active elections

---

## Options Evaluated

### Option A: Minimal — New task, no new model
Add a `poll_sc_enr_elections()` task directly to `sc_vrems/tasks.py` that hits `elections.json`, resolves URLs, and sets `Election.results_url` for date-matched elections. No new Django app or model.

**Decision matrix:**

| Criterion | Weight | Score | Notes |
|---|---|---|---|
| Implementation effort | 3 | 5 | ~1 task, no migration |
| Full county coverage | 2 | 1 | No county-level Election records exist; county ENR entries would be lost |
| Auditability | 2 | 2 | No record of what ENR elections were discovered or when |
| Separation of concerns | 2 | 2 | ENR logic in VREMS module is semantically wrong |
| Resilience to empty feed | 3 | 3 | Simple — just skip if `[]` |
| **Weighted total** | — | **30** | |

**Rejected:** County-level entries would be silently lost. No audit trail for discovered ENR elections. Mixing ENR concerns into VREMS module violates the established pattern.

---

### Option B: Full module — New `sc_enr` integration app + `ENRElection` model
New Django app `backend/integrations/sc_enr/` following the `sc_vrems` pattern. New `ENRElection` model stores every discovered election (state + county level) with its resolved URL and optional FK to `Election`.

**Decision matrix:**

| Criterion | Weight | Score | Notes |
|---|---|---|---|
| Implementation effort | 3 | 2 | New app, migration, tests |
| Full county coverage | 2 | 5 | All 47 entries persisted |
| Auditability | 2 | 5 | Full record of discovery history |
| Separation of concerns | 2 | 5 | Clean module per system |
| Resilience to empty feed | 3 | 5 | Records survive off-season |
| **Weighted total** | — | **52** | |

**Selected.** See critical design corrections below.

---

### Option C: Hybrid — New task in `sc_vrems` + `enr_base_url` field on `Election`
Add `enr_base_url` to the existing `Election` model (1 field, 1 migration) and a `poll_enr_elections` task in `sc_vrems/tasks.py`.

**Decision matrix:**

| Criterion | Weight | Score | Notes |
|---|---|---|---|
| Implementation effort | 3 | 3 | 1 migration + 1 task |
| Full county coverage | 2 | 2 | Same problem as Option A for county entries |
| Auditability | 2 | 3 | Stored on Election but no discovery history |
| Separation of concerns | 2 | 2 | ENR concerns in VREMS module |
| Resilience to empty feed | 3 | 5 | Field persists on Election |
| **Weighted total** | — | **37** | |

**Rejected:** Same county coverage gap as Option A.

---

## Decision

**Implement Option B** — a new `sc_enr` Django integration app with an `ENRElection` model, two Celery tasks, and the design corrections below.

### Justification
- Follows the established `sc_vrems` integration module pattern
- Full county-level ENR entries are preserved, enabling future precinct-level results
- Discovered elections survive the off-season with audit timestamps
- Separates ENR (results discovery) concerns cleanly from VREMS (candidate/filing) concerns
- The `ClarityAdapter` path is unchanged — it reads `Election.results_url`, which gets populated by the link step

---

## Design (Corrected)

### `ENRElection` model

```python
class ENRElection(models.Model):
    election_name = models.CharField(max_length=200)
    election_date = models.DateField()
    scope = models.CharField(max_length=10, choices=[('state', 'State'), ('county', 'County')])
    county = models.CharField(max_length=100, blank=True, null=True)
    eid = models.IntegerField()
    enr_base_url = models.URLField()
    enr_resolved_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)  # False when no longer in elections.json
    link_confidence = models.CharField(
        max_length=20,
        choices=[('auto', 'Auto-linked'), ('ambiguous', 'Ambiguous'), ('manual', 'Manual')],
        default='auto',
    )
    election = models.ForeignKey(
        "elections.Election", null=True, blank=True, on_delete=models.SET_NULL
    )
    discovered_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            # County-scoped uniqueness (non-null county)
            models.UniqueConstraint(
                fields=['eid', 'county'],
                condition=models.Q(county__isnull=False),
                name='unique_enr_county_election',
            ),
            # State-scoped uniqueness (null county)
            models.UniqueConstraint(
                fields=['eid'],
                condition=models.Q(county__isnull=True),
                name='unique_enr_state_election',
            ),
        ]
```

> **Why two constraints**: PostgreSQL does not consider NULL == NULL in `unique_together`, so a standard `unique_together = [("eid", "county")]` allows unlimited duplicate state-level rows (county=NULL). Two partial `UniqueConstraint` objects handle each case correctly.

> **Why `enr_resolved_url` on this model, not bare URL on `Election.results_url`**: The `ClarityAdapter` constructs `{results_url}current_ver.txt` by string concatenation. It needs the fully resolved path (`/SC/{EID}/web.XXXXXX/`), not the base EID path (`/SC/{EID}/`). The link step copies `enr_resolved_url` → `Election.results_url` only after successful resolution.

---

### Task flow

```
poll_enr_elections (scheduled, election-season only)
  │
  ├─ GET elections.json → list of {ElectionName, Date, County, EID}
  │
  ├─ For each entry:
  │     upsert ENRElection (upsert-only — never delete)
  │     if enr_resolved_url is empty: call resolve_url(eid, county)
  │     mark is_active=True / last_seen_at=now
  │
  ├─ Mark ENRElections NOT in this batch as is_active=False
  │
  └─ For state-level ENRElections with county=null:
        attempt Election FK link: match on (election_date, state="SC")
        if exactly 1 match → FK + link_confidence="auto"
        if 0 or >1 matches → FK=null + link_confidence="ambiguous" + log warning
        copy enr_resolved_url → Election.results_url (only if confidence="auto")

sync_enr_results (triggered by poll or scheduled during election window)
  │
  ├─ Query ENRElections WHERE is_active=True AND election_id IS NOT NULL
  │   (skip county entries and unlinked state entries)
  │
  └─ For each: call ClarityAdapter.fetch_results(election_date, election_id)
               (uses Election.results_url already set by poll step)
```

---

### URL resolution caching

`resolve_url()` follows the server-side redirect from `/{EID}/` to `/{EID}/web.XXXXXX/`. This is only called when `ENRElection.enr_resolved_url` is empty or when a 404 is encountered fetching `current_ver.txt` (indicating the resolved URL is stale). **Do not resolve on every poll cycle.**

---

### Election date matching rules

The link step matches state-level ENRElections to Elections using:

```python
matches = Election.objects.filter(
    election_date=enr_election.election_date,
    state="SC",
)
```

Rules:
- **1 match** → auto-link, `link_confidence="auto"`, copy resolved URL
- **0 matches** → leave FK null, `link_confidence="ambiguous"`, log warning once
- **>1 matches** → leave FK null, `link_confidence="ambiguous"`, log warning with match list

Manual linking is performed in Django admin. County-level ENRElections are **not** linked to Elections automatically — the VREMS-created Election records are statewide.

---

## Module Structure

```
backend/integrations/sc_enr/
    __init__.py
    apps.py          # AppConfig, label="sc_enr"
    client.py        # ENRClient: get_elections(), resolve_url()
    mappers.py       # map_enr_election(), link_to_election()
    models.py        # ENRElection
    tasks.py         # poll_enr_elections(), sync_enr_results()
    exceptions.py    # SCEnrError, SCEnrRetryableError
    admin.py         # ENRElection admin with link_confidence filter
    migrations/
    tests/
        test_client.py
        test_mappers.py
        test_tasks.py
```

---

## Consequences

### Positive
- `Election.results_url` is populated automatically for state-level SC elections — removes a manual admin step
- Full audit trail of all ENR elections discovered, with timestamps and link confidence
- County-level ENR entries are stored for future precinct-level results ingestion
- The existing `ClarityAdapter` is unchanged — it reads `Election.results_url` exactly as before
- Off-season `[]` response from `elections.json` is safe — existing records are never deleted

### Negative
- New Django app + migration required
- Date-only matching means ambiguous cases need manual admin resolution
- County-level ENRElections that have no matching `Election` record skip results ingestion (expected — county-level `Election` records are not created by `sc_vrems`)
- Scheduling must account for the election-season-only nature of `elections.json`

### Technical Debt Accepted
- No precinct-level or county-level results ingestion in this ADR — county ENRElections are stored but their results are not fetched until a future ADR extends the `sync_enr_results` task

---

## Alternatives Considered

### Not creating a new `ENRElection` model
Rejected — no audit trail, county entries lost, and `results_url` would be cleared accidentally on empty-feed runs.

### Using `SCElectionResults.xml` for discovery
Rejected — confirmed dead feed. Single entry from 2013, never updated since SC migrated to the Angular SPA.

### Using `clarify` Python library for XML parsing
Deferred — `clarify` parses the older `detailxml.zip` XML format. The current `ClarityAdapter` uses the JSON API (`summary.json`), which is preferred. The `clarify` library is a valid fallback if JSON API access degrades but is not needed for the auto-discovery feature.

---

*Authored: 2026-05-26. Code review conducted by automated review agent prior to ADR finalization.*
