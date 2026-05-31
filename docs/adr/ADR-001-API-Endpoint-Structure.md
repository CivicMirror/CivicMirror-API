# ADR-001: CivicMirror API Endpoint Structure

## Status
Accepted

## Context

CivicMirror needs a unified REST API that normalizes election data from heterogeneous sources (Google Civic, OpenStates, Ballotpedia, OpenFEC, Clarity Elections, MEDSL, and others). The API must serve:

- The CivicMirror web app (primary consumer)
- Potential public/third-party consumers (future)

### Core Data Entities (from concept.md)

| Entity | Key Attributes |
|---|---|
| **Elections** | Type (primary/general/special/midterm/party), date, jurisdiction, status |
| **Races** | Office title, election, geography scope, race type (candidate vs. measure) |
| **Candidates** | Name, party, contact, website, phone, bio, platform statement |
| **Ballot Measures** | Title, type (resolution/referendum/direct/indirect), text, options |
| **Officials** | Incumbent status, office held, district, term start/end |
| **Districts** | Level (federal/state/local), OCD-ID, FIPS code, GeoJSON boundary |
| **Results** | Vote counts, result type (UNOFFICIAL/OFFICIAL), precinct reporting status |

### Requirements

- Support address/ZIP-based ballot lookups (primary use case for CivicMirror UI)
- Filter elections/races by state, type, date range, and jurisdiction
- Expose live results (unofficial) and certified results (official) distinctly
- Normalize all IDs using OCD-IDs and FIPS codes
- Support GeoJSON boundary retrieval for districts
- Version the API for future evolution without breaking changes
- Return paginated lists for collection endpoints

### Constraints

- Django/DRF backend (pre-development; Django REST Framework is the natural choice)
- Pre-development / concept phase — no legacy endpoints to preserve
- Single developer initially; keep surface area manageable

---

## Decision

Use a **hybrid resource-oriented REST API** with:

1. **Top-level resource collections** for direct entity access
2. **Nested sub-resources** for tightly coupled relationships (e.g., races within an election)
3. A dedicated **`/lookup`** endpoint for address/ZIP-based ballot queries (mirrors Google Civic's primary UX pattern)
4. **`/api/v1/` prefix** for versioning from day one

### Chosen Option: Hybrid Flat + Nested with Lookup

```
/api/v1/
  elections/
  elections/{id}/
  elections/{id}/races/
  elections/{id}/results/
  races/
  races/{id}/
  races/{id}/candidates/
  races/{id}/results/
  candidates/
  candidates/{id}/
  ballot-measures/
  ballot-measures/{id}/
  officials/
  officials/{id}/
  districts/
  districts/{id}/
  districts/{id}/boundary/
  lookup/
```

### Justification

- **Top-level resources** (`/races/`, `/candidates/`, `/officials/`) allow direct filtered access without knowing the parent election ID — required for search, cross-election candidate tracking, and incumbent lookups
- **Nested sub-resources** (`/elections/{id}/races/`) express the natural parent-child relationship and allow the CivicMirror UI to load a full election view in one logical chain of requests
- **`/lookup`** as a first-class endpoint (not buried under `/elections`) reflects the primary user journey: "what's on my ballot?" — it accepts an address or ZIP and returns a full ballot context
- **`/districts/{id}/boundary`** as a separate sub-resource keeps GeoJSON out of default list/detail payloads (GeoJSON can be very large; lazy-load boundary data only when needed)
- **`/v1/` prefix** enables non-breaking evolution; v2 can coexist if the data model expands significantly

---

## Decision Matrix

| Option | DX Simplicity | Query Flexibility | Nesting Clarity | Payload Size Control | Django/DRF Fit | Total |
|---|---|---|---|---|---|---|
| **A — Fully Flat** | 5 | 5 | 2 | 3 | 5 | 20 |
| **B — Hybrid (chosen)** | 4 | 5 | 5 | 4 | 5 | 23 |
| **C — Fully Nested** | 2 | 2 | 5 | 4 | 3 | 16 |
| **D — GraphQL Only** | 3 | 5 | 5 | 5 | 2 | 20 |

*Weights: DX Simplicity=1×, Query Flexibility=1×, Nesting Clarity=1×, Payload Size=1×, Django/DRF Fit=1×*

---

## Consequences

### Positive
- Address/ZIP lookup is a first-class, discoverable endpoint — matches CivicMirror UI flow
- Nested race endpoints (`/elections/{id}/races/`) make ballot-page assembly straightforward
- Flat top-level endpoints enable cross-election candidate tracking and incumbent lookups
- `/districts/{id}/boundary/` keeps list/detail payloads lean
- Versioning from day one prevents breaking the companion app on schema evolution
- Aligns well with Django REST Framework router conventions

### Negative
- Some resources (e.g., candidates) are reachable via both `/candidates/` and `/races/{id}/candidates/` — consistent behavior must be maintained at both paths
- Lookup endpoint requires special handling — it calls upstream sources (Google Civic), not just the local DB
- Slightly larger URL surface than a pure-flat API

---

## Alternatives Considered

### Fully Flat (`/api/v1/elections/`, `/api/v1/races/`, etc.)
**Reason rejected:** Loses the natural parent-child relationship in the URL structure; forces the UI to do more client-side join logic to build a ballot view.

### Fully Nested (`/elections/{id}/races/{raceId}/candidates/{id}/`)
**Reason rejected:** Deep nesting (3+ levels) makes direct entity lookups impossible without traversing the full hierarchy. Cross-election candidate and official lookups become impractical.

### GraphQL Only
**Reason rejected:** concept.md explicitly identifies REST as the primary output format; GraphQL is listed as a future/optional endpoint. GraphQL also has a steeper learning curve for public API consumers and is harder to cache at the HTTP layer.

---

## Related Decisions

- ADR-002 (future): Pagination strategy (cursor vs. page/limit)
- ADR-003 (future): Authentication model (public read / authenticated write)
- ADR-004 (future): GraphQL endpoint shape and co-location strategy
