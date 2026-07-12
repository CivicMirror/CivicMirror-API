# Illinois Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Built | IL SBE `votetotalsearch.aspx` election dropdown (`integrations/il_sbe/`) |
| Stage 1 — Race Creation | ✅ Built | IL SBE results category pages, Federal + State offices only |
| Stage 2 — Results Ingestion | ✅ Built | IL SBE per-office CSV (`results/adapters/il.py`) |

---

**Site:** https://www.elections.il.gov/electionoperations/ElectionVoteTotals.aspx
**Results Search:** https://www.elections.il.gov/electionoperations/votetotalsearch.aspx
**Operated by:** Illinois State Board of Elections
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Illinois provides election results through the State Board of Elections website with searchable results, downloadable vote totals, and historical data. County-by-county results are available for federal, statewide, legislative, and judicial offices from 1998 onward. Local election results are handled by 108 individual election authorities.

---

## Data Access

### Vote Total Search
- **URL:** https://www.elections.il.gov/electionoperations/votetotalsearch.aspx
- Search by office name or candidate last name
- Downloadable vote totals
- Includes ballots cast and voter registration totals
- Elections available: 2009–2025 (Primaries, Generals, Consolidateds, Specials)

### Election Results Page
- **URL:** https://www.elections.il.gov/electionoperations/ElectionResults.aspx
- Election authority contact information for unofficial results
- Links to local jurisdiction websites

### Official Vote Total Book
- Published for each election cycle
- Contains comprehensive results data

### Voter File
- Available in Microsoft Access and comma-delimited text formats
- Single-file format (voter + voting history combined)
- Multi-file normalized format (three tables: voter, subdivision, history)
- Includes up to last 15 elections of voting history per voter

---

## API Access

CSV mechanism discovered: IL SBE exposes pre-built results category pages (`ElectionVoteTotals.aspx?ID=...&OfficeType=...`) with stable `OfficeType` tokens per category and a per-election encrypted `ID` token. Each office links to a public, unauthenticated, precinct-level CSV. See the Update section below for full details.

---

## Notes

- 108 election authorities: 102 county clerks + 6 municipal (Chicago, Bloomington, Rockford, Galesburg, Danville, East St. Louis)
- Local/unofficial results not reported to State Board
- County-by-county data available from 1998 onward
- Voter file available with history for qualified requestors
---

## Source Coverage Analysis

Illinois's State Board of Elections is one of the stronger state sources in this batch, explicitly covering all four required election types (Primary, General, Consolidated, Special) from 2009 onward with county-level results and a voter file with 15-election history. However, ballot measures, candidate biographical/contact data, official/incumbent records, and geographic boundary data are entirely absent, and live results are fragmented across 108 independent election authorities. **Ballotpedia** and **Google Civic Information API** are the primary recommended supplements for candidate profiles, ballot measures, and district boundaries; **OpenStates** covers state legislative incumbents; and individual election authority websites (or a **Clarity Elections** aggregation) should be evaluated for live result ingestion.

---

## Update 2026-07-11: CSV mechanism found, adapter built

Superseded the "no public REST API identified" finding above. IL SBE exposes
pre-built results category pages (`ElectionVoteTotals.aspx?ID=...&OfficeType=...`)
with stable `OfficeType` tokens per category and a per-election encrypted `ID`
token resolved via an ASP.NET auto-postback replay (plain `requests`, no
browser needed). Each office links to a public, unauthenticated, precinct-level
CSV. Full mechanism documented in `docs/superpowers/specs/2026-07-11-il-adapter-design.md`.

**Deferred for future integration:** Judicial retention/contested races and
statewide ballot measures use the identical CSV mechanism (see the `Judicial`
category token in `integrations/il_sbe/client.py`) but are out of scope for
the Federal + State build. Adding them is a matter of adding the Judicial
category token to `sync_il_races`/`il.py`'s category loop and updating
`is_federal_or_state_office`'s filter (or adding a parallel measures path) —
no new scraping mechanism required.
