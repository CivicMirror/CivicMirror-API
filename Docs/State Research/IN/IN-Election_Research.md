# Indiana Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | SOS archive only — no adapter built |

---

**Site:** https://www.in.gov/sos/elections/election-commission/election-results/
**New Portal:** https://indianavoters.in.gov/ENRHistorical/ElectionResults
**Operated by:** Indiana Secretary of State / Indiana Election Division
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Indiana provides election results through the Secretary of State's website and a new IndianaVoters.in.gov portal. Historical voter registration and turnout statistics are available from 1948–2018. Election results archives cover elections from 2002 onward.

---

## Data Access

### New Election Results Portal
- **URL:** https://indianavoters.in.gov/ENRHistorical/ElectionResults
- For elections since 2024
- Historical election results search

### Past Election Results
- **URL:** https://www.in.gov/sos/elections/statistics-and-maps/archive-of-past-election-information/
- Candidate lists, delegate numbers, public questions
- Coverage: 2002–2024

### Voter Registration & Turnout Statistics
- Selected statistics from 1948–2018

### Campaign Finance Data
- Electronic filings available online via data download page

---

## API Access

No public REST API identified. Data access is through:
1. IndianaVoters.in.gov portal for recent results
2. Archive of past election information on SOS website
3. Contact election division: elections@iec.in.gov / (317) 232-3939

---

## Notes

- Bipartisan election commission administers elections statewide
- County election boards responsible for local conduct
- Vote center system adopted by nearly half of counties since 2001
- Voter file access: $5,000 annual subscription fee for computerized access
- Limited to political parties, media organizations, and elected officials
---

## Source Coverage Analysis

Indiana's SOS archive and IndianaVoters portal provide reasonable historical coverage (2002–2024) and uniquely reference "candidate lists" and "public questions" — giving partial coverage of candidate names and ballot measures that most peer states lack. However, full candidate contact, biography, party, and platform data are absent, as are official/incumbent records and geographic boundary data, and no live results feed is identified. **Google Civic Information API** and **Ballotpedia** are the recommended supplements for complete candidate profiles and ballot measure taxonomy; **OpenStates** covers state legislative incumbents; and county election boards should be assessed for **Clarity Elections** live reporting capability.
