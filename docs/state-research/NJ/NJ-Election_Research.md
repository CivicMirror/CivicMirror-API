# New Jersey Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | County-level downloads (Clarity unverified) — no adapter built |

---

**Site:** https://nj.gov/state/elections/election-information-results.shtml
**Operated by:** New Jersey Division of Elections
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

New Jersey provides election results through the Division of Elections website with county-level certified results.

---

## Data Access

### Election Results
- County-level certified results
- Historical results archive
- PDF and Excel downloads for some elections

---

## API Access

No public REST API identified.

---

## Notes

- 21 counties
- County clerk offices manage elections locally
- Results organized by election year and type

---

## Source Coverage Analysis

New Jersey's Division of Elections provides county-level certified results organized by election year and type, but no public REST API, no ballot measure data, and no candidate profile information are available from the state source. The county-clerk-managed election model means live results may exist at individual county levels (potentially via **Clarity Elections**), but this is not currently documented. Candidate data, ballot measures, officials/incumbents, and district boundaries should be supplemented using **Google Civic Information API** (elections, candidates, district lookups), **Ballotpedia** (ballot measures, candidate bios, incumbency), **OpenStates** (NJ legislative data), and **OpenFEC** (federal races and campaign finance). Live/real-time coverage should be investigated at the county level for **Clarity Elections** adoption across NJ's 21 county clerks.
