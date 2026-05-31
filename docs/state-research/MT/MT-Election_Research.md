# Montana Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | PDF/CSV (Clarity unverified) — no adapter built |

---

**Site:** https://sosmt.gov/elections/results/
**Operated by:** Montana Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Montana provides election results through the Secretary of State's website with downloadable canvass reports and election night results.

---

## Data Access

### Election Results
- **URL:** https://sosmt.gov/elections/results/
- Canvass results by election
- County-level breakdowns

### Download Formats
- PDF canvass reports
- Excel/CSV files for some datasets

---

## API Access

No public REST API identified.

---

## Notes

- 56 counties
- Small population allows for relatively simple data structure

---

## Source Coverage Analysis

Montana's SOS source provides canvass reports and limited CSV exports for election results, but coverage is primarily PDF-centric and lacks an API, live results feed, ballot measure data, or candidate metadata. Montana has an active ballot initiative process, making the ballot measure gap especially relevant. Gaps should be filled using **Ballotpedia** (ballot measures, candidate bios), **Google Civic Information API** (candidates, districts, election types), **OpenStates** (state legislative incumbents), **OpenFEC** (federal candidates), and **MEDSL** for normalized historical CSV data. Verify whether Montana counties or the SOS use **Clarity Elections** for live election night reporting.
