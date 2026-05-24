# Georgia Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | Partial Clarity (returns 403 remotely) — no adapter built |

---

**Site:** https://sos.ga.gov/page/georgia-election-results
**Election Data Hub:** https://sos.ga.gov/election-data-hub
**Turnout Hub:** https://sos.ga.gov/page/election-data-hub-turnout
**Elections Portal:** https://elections.sos.ga.gov/
**Operated by:** Georgia Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Georgia provides election results through the Secretary of State's website with an interactive Election Data Hub, downloadable voter data, and historical results. The system includes turnout tracking and interactive data tools.

---

## Data Access

### Election Data Hub
- **URL:** https://sos.ga.gov/election-data-hub
- Interactive data application (Go Interactive mode)
- Allows download of Active/Inactive statistical voter data
- Covers recent election cycles

### Turnout Data Hub
- **URL:** https://sos.ga.gov/page/election-data-hub-turnout
- Real-time turnout tracking during elections
- County-level turnout data
- Updated as county election officials upload credit for voting

### Historical Results
- **URL:** https://sos.ga.gov/page/georgia-election-results
- Results prior to July 31, 2012 available as PDF documents
- More recent results via Clarity Elections or data hub

### Elections Portal
- **URL:** https://elections.sos.ga.gov/
- Voter history search
- Registration data

### County-Level Data
- Individual counties publish their own results including:
  - Summary reports (PDF)
  - Cast Vote Records (CVR)
  - Certification and reconciliation reports

---

## API Access

No public REST API identified. Data access is through:
1. Interactive Election Data Hub with download capability
2. PDF downloads for historical results (pre-2012)
3. County-level results through individual county websites
4. Elections portal for voter history

---

## Notes

- Pre-2012 results primarily in PDF format
- Interactive data hub provides the most modern data access
- County election officials have 60 days post-election to record all voting credit (per O.C.G.A. 21-2-215(i))
- Turnout numbers may increase in small increments for several days post-election
- CVR (Cast Vote Record) data published by some counties

---

## Source Coverage Analysis

Georgia's Election Data Hub and partial Clarity Elections usage provide reasonable coverage for modern election results and real-time turnout tracking, but pre-2012 results are locked in PDFs and the state source entirely lacks ballot measure data, candidate biographical information, district GeoJSON, and incumbent metadata. The partial Clarity Elections integration (`results.enr.clarityelections.com`) should be mapped to specific election cycles to determine when to use Clarity vs. the data hub as the ingestion source. **Google Civic API** fills district, official, and candidate contact gaps; **Ballotpedia** provides candidate profiles and ballot measure content; **MEDSL** provides normalized historical CSVs as a PDF-free substitute for pre-2012 data; and **OpenStates** covers state legislative incumbents.
