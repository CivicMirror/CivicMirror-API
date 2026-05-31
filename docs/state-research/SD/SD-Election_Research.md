# South Dakota Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | Excel downloads — no adapter built |

---

**Site:** https://sdsos.gov/elections-voting/election-results/default.aspx
**Operated by:** South Dakota Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

South Dakota provides election results through the Secretary of State's website with downloadable results by election year.

---

## Data Access

### Election Results
- County-level results
- Historical results archive
- PDF and downloadable formats

---

## API Access

No public REST API identified.

---

## Notes

- 66 counties
- Results organized by election year
---

## Source Coverage Analysis

South Dakota's SOS website provides county-level historical results via downloadable Excel files for Primary, General, and Special elections, but the state source lacks ballot measure data — a significant gap given South Dakota's status as one of the country's most active initiative states. Candidate biographical/contact data, official/incumbent records, and district boundary data are also entirely absent, and no live results feed is documented. **Ballotpedia** is the highest-priority supplementary source for South Dakota ballot measures; **Google Civic Information API** fills candidate, official, and district gaps; **OpenStates** covers SD state legislative incumbents; **OpenFEC** adds federal candidates; and **MEDSL** provides normalized historical CSV data for cross-validation.
