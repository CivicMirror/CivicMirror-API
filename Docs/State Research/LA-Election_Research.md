# Louisiana Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API; jungle primary type requires custom election subtype |
| Stage 2 — Results Ingestion | ❌ No adapter | Parish-level portal — no adapter built |

---

**Site:** https://voterportal.sos.la.gov/
**Results:** https://www.sos.la.gov/ElectionsAndVoting/
**Operated by:** Louisiana Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Louisiana provides election results through the Secretary of State's website. Louisiana uses a unique "jungle primary" system where all candidates regardless of party appear on the same ballot, with a runoff if no candidate receives a majority.

---

## Data Access

### Election Results
- Official results available through Secretary of State
- Parish-level (Louisiana's equivalent of counties) breakdowns
- Precinct-level data available

### Voter Portal
- **URL:** https://voterportal.sos.la.gov/
- Voter registration and election information

### Historical Data
- Results archive available on SOS website
- Registration and turnout data broken down by party and race

---

## API Access

No public REST API identified. Data access is through:
1. Web-based results portal
2. Downloadable files from SOS website
3. Parish-level results pages

---

## Notes

- 64 parishes (not counties)
- Unique "jungle primary" system — all candidates on single ballot
- Runoff elections common
- Registration data includes party and race breakdowns
---

## Source Coverage Analysis

Louisiana's SOS portal provides historical results and voter registration data broken down by party and race across 64 parishes, and the state's distinctive "jungle primary" / top-two runoff system is an important data-modeling note — the CivicMirror election type taxonomy should accommodate a "Non-Partisan Open / Jungle Primary" subtype for Louisiana. Ballot measures, candidate profiles, official/incumbent records, and parish geographic boundaries are all absent from the state source, and no live results feed is documented. **Google Civic Information API** and **Ballotpedia** are recommended to fill candidate and ballot measure gaps; **OpenStates** covers Louisiana legislative incumbents; and individual parish election offices should be assessed for **Clarity Elections** live result feeds.
