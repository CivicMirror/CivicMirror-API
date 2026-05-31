# Maryland Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | CSV downloads (Clarity unverified) — no adapter built |

---

**Site:** https://elections.maryland.gov/elections/results_data/
**Operated by:** Maryland State Board of Elections
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Maryland provides election results through the State Board of Elections website with downloadable data files and an online results portal.

---

## Data Access

### Election Results & Data
- **URL:** https://elections.maryland.gov/elections/results_data/
- Official certified results
- Election night reporting

### Download Formats
- CSV files for election results
- PDF official canvass reports
- Excel files for some datasets

### Historical Data
- Results archive going back multiple election cycles
- Voter registration and turnout statistics

---

## API Access

No public REST API identified. Data access is through:
1. CSV/Excel file downloads
2. PDF canvass reports
3. Web-based results display

---

## Notes

- 24 jurisdictions (23 counties + Baltimore City)
- State Board of Elections administers elections statewide
- Early voting data and vote-by-mail statistics available
---

## Source Coverage Analysis

Maryland's State Board of Elections provides one of the more programmatically accessible state sources in this batch, offering certified results in CSV format across multiple election cycles for 24 jurisdictions, with early voting and vote-by-mail breakdowns. However, ballot measures, candidate biographical/contact data, official/incumbent records, and geographic boundary data are entirely absent, and the election night reporting mechanism is unspecified and should be investigated for **Clarity Elections** integration. **Google Civic Information API** and **Ballotpedia** are the recommended supplements for candidate profiles, ballot measures, and districts; **OpenStates** covers Maryland legislative incumbents; and the SBE's election night infrastructure should be confirmed against the Clarity Elections platform for live result ingestion.
