# Pennsylvania Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API, PA Election Calendar |
| Stage 1 — Race Creation | 🟡 Available via Scraping | Candidate database available through PA Voter Services Beta site; no public API |
| Stage 1 — Candidate Enrichment | 🟡 Partial | Candidate records available; biographical enrichment requires external sources |
| Stage 1 — Ballot Measures | ⚠️ Research Needed | No statewide structured source identified |
| Stage 2 — Results Ingestion | ❌ No adapter | electionreturns.pa.gov reverse engineering required |
| Stage 2 — Precinct Results | ⚠️ Possible | Data appears available through election returns system |
| Stage 2 — Certification Data | ⚠️ Possible | Further research required |

---

**Site:** https://www.electionreturns.pa.gov/
**Data:** https://data.pa.gov/
**Operated by:** Pennsylvania Department of State
**Researched:** Updated June 2026
**Status:** Public, no authentication required

---

## Overview

Pennsylvania provides election results through the Department of State's election returns website and the PA Open Data portal. Additional research confirms that pre-election candidate information is available through the Pennsylvania Voter Services candidate database, although no public API has been identified.

---

## Data Access

### Election Returns
- URL: https://www.electionreturns.pa.gov/
- Interactive results portal
- County-level and precinct-level results
- Historical results archive
- No documented public API identified

### PA Open Data Portal
- URL: https://data.pa.gov/
- Structured datasets with API access via Socrata/SODA
- Primarily administrative election datasets
- Does not currently provide comprehensive candidate/race creation data

### Pennsylvania Voter Services Candidate Database
- Search Interface:
  https://www.pavoterservices.beta.pa.gov/electioninfo/BasicSearch.aspx
- Candidate Detail Pages:
  https://www.pavoterservices.beta.pa.gov/ElectionInfo/CandidateInfo.aspx?ID=<candidate_id>

HAR validation confirms:
- HTTP 200 responses
- Functional search workflow
- Candidate detail pages accessible
- Structured candidate information available

---

## API Access

### Results Data
- Socrata/SODA API via data.pa.gov
- No dedicated election results API identified

### Candidate Data
- No public API identified
- Candidate data accessible via ASP.NET WebForms application
- Browser automation (Playwright) recommended

---

## Candidate Database Findings

### Example Fields Observed

- Candidate Name
- Candidate ID
- Election Year
- Party
- Office Sought
- District
- Filing Information
- Election Type

Example:

```json
{
  "candidate_id": "2026C0020",
  "office": "Representative in the General Assembly",
  "district": "55th Legislative District",
  "party": "Republican",
  "election_year": 2026
}
```

### Engineering Assessment

Recommended workflow:

```text
Playwright
    ↓
BasicSearch.aspx
    ↓
ElectionInfo.aspx
    ↓
CandidateInfo.aspx
```

### CivicMirror Impact

Pennsylvania should no longer be considered fully blocked for Stage 1 race creation.

Updated assessment:

```text
Race Creation = Available via Browser Automation
```

Potential coverage includes:

- Governor
- Lieutenant Governor
- State Senate
- State House
- Judicial races
- Additional local races (pending verification)

---

## Election Calendar Research

Potential sources provide:

- Election dates
- Candidate filing deadlines
- Petition circulation periods
- Withdrawal deadlines
- Certification dates
- Registration deadlines
- Mail ballot deadlines

Use for Stage 1 election creation and scheduling.

---

## Source Coverage Analysis

Pennsylvania remains one of the strongest election-information states, but much of the useful data is exposed through web applications rather than APIs.

### Primary Sources

1. Pennsylvania Election Returns
2. Pennsylvania Voter Services Candidate Database
3. Pennsylvania Department of State Election Calendars
4. PA Open Data Portal

### Supplemental Sources

- Google Civic Information API
- Ballotpedia
- OpenStates
- OpenFEC

---

## Future Research Opportunities

### Priority 1 — Candidate Enumeration

Research:

- Election year filters
- Office filters
- District filters
- Pagination behavior
- Search parameter structure

Goal:

Full statewide candidate ingestion.

### Priority 2 — Candidate Enrichment

Determine availability of:

- Committee information
- Contact information
- Incumbent status
- Withdrawal status
- Certification status

### Priority 3 — Judicial Elections

Verify support for:

- Supreme Court
- Superior Court
- Commonwealth Court
- Retention Elections

### Priority 4 — County & Municipal Coverage

Verify:

- County Commissioner
- Sheriff
- School Board
- Township Offices
- Borough Offices
- Local Referenda

### Priority 5 — Ballot Measures

Research sources for:

- Constitutional Amendments
- Statewide Referenda
- Local Ballot Questions

### Priority 6 — Election Returns Reverse Engineering

Investigate:

- Network traffic
- JSON endpoints
- Anti-bot protections
- Results delivery mechanisms

Goal:

Dedicated Stage 2 Results Adapter.

---

## Recommended CivicMirror Adapter Architecture

### PA-Elections Adapter

Responsibilities:

- Election creation
- Calendar ingestion
- Deadline management

### PA-Candidates Adapter

Responsibilities:

- Candidate discovery
- Race creation
- Candidate enrichment

Implementation:

Playwright-based scraper

### PA-Results Adapter

Responsibilities:

- Election-night reporting
- County results
- Precinct results
- Certification data

Implementation:

ElectionReturns reverse engineering

---

## Updated Assessment

| Capability | Status |
|------------|----------|
| Election Creation | ✅ |
| Candidate Discovery | 🟡 |
| Race Creation | 🟡 |
| Candidate Enrichment | 🟡 |
| Ballot Measures | ⚠️ |
| Election Results | ⚠️ |
| Precinct Results | ⚠️ |

Pennsylvania should be classified as a high-value Playwright target rather than an API-first integration.
