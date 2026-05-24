# Nebraska Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API; nonpartisan unicameral legislature |
| Stage 2 — Results Ingestion | ❌ No adapter | PDF/Excel (Clarity unverified) — no adapter built |

---

**Site:** https://sos.nebraska.gov/elections/election-results
**Operated by:** Nebraska Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Nebraska provides election results through the Secretary of State's website. Nebraska is notable for splitting its electoral votes by congressional district (like Maine).

---

## Data Access

### Election Results
- **URL:** https://sos.nebraska.gov/elections/election-results
- County-level results
- Historical archive

### Download Formats
- PDF reports
- Excel files

---

## API Access

No public REST API identified.

---

## Notes

- 93 counties
- Electoral votes split by congressional district (3 districts + 2 at-large)
- Unicameral (nonpartisan) state legislature

---

## Source Coverage Analysis

Nebraska's primary source (SOS website) provides county-level historical results in PDF/Excel only, with no API, no structured election-type metadata, no ballot measure data, and no candidate profile information. The state's unicameral nonpartisan legislature further limits party-primary data availability from the state source. Gaps in candidate info, officials/incumbents, ballot measures, and district boundaries should be supplemented with **Google Civic Information API** (elections, candidates, districts), **Ballotpedia** (ballot measures, candidate bios, incumbents), **OpenStates** (legislative data), and **OpenFEC** (federal candidate filings). Live election night results are not available from the state and may require **Clarity Elections** county-level coverage or **MEDSL** post-election data.
