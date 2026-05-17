---
date: 05/17/2026
developer: Walter LeFort
ai_tools: Copilot Pro, Claude, ChatGPT
companion_app: https://github.com/tokendad/CivicMirror
---

# Election Data Aggregator — Concept

> 🚧 **Status: Concept / Pre-development**

## Purpose

The purpose of this project is to provide a normalized source of election and ballot data for the [CivicMirror](https://github.com/tokendad/CivicMirror) web app.

## AI Prompt

> Source election and ballot data from multiple free sources for federal, state, and local contests, and normalize that data into an aggregate API for CivicMirror and possibly public use.

---

## Data Points

The following data points are not a complete list, but represent minimum standards when sourcing data.

- **Elections**
  - Primary
    - Open
    - Closed
    - Non-Partisan
  - General
  - Special
  - Mid-Term
  - Party
- **Ballot Measures**
  - Resolutions
  - Referendums
  - Direct
  - Indirect
- **Candidates**
  - General Information
    - Contact Information
    - Website
    - Phone
  - Party Affiliation
  - CV / Résumé
  - Platform Statement
- **Officials**
  - Incumbent Status
  - Office Currently Held
  - District Represented
  - Term Start / End Dates
- **Districts & Jurisdictions**
  - Federal (House, Senate, Presidential)
  - State (Legislative, Gubernatorial)
  - Local (County, Municipal, School Board, Special District)
  - Geographic Boundaries (GeoJSON / FIPS codes)

---

## Data Sources

The following are target sources for aggregation. This list is not exhaustive and will evolve as the project matures.

| Source | Coverage | Format | Notes |
|---|---|---|---|
| [Google Civic Information API](https://developers.google.com/civic-information) | Federal, State, Local | REST/JSON | Election & rep data by address |
| [OpenStates API](https://openstates.org/api/v3/) | State Legislative | REST/JSON | Bills, legislators, votes |
| [Ballotpedia](https://ballotpedia.org/API_documentation) | Federal, State, Local | REST/JSON | Candidate & ballot measure data |
| [OpenFEC (FEC API)](https://api.open.fec.gov/developers/) | Federal | REST/JSON | Campaign finance, candidates, filings |
| [MIT Election Data Lab](https://electionlab.mit.edu/data) | Federal, State | CSV/JSON | Historical results |
| [EAVS (EAC)](https://www.eac.gov/research-and-data/election-administration-voting-survey) | State | CSV | Election admin statistics |

---

## Normalization Strategy

The goal is to ingest data from heterogeneous sources and output a unified, queryable API.

### Output Format
- **REST API** with JSON responses (primary)
- Potential **GraphQL** endpoint for CivicMirror front-end flexibility

### Key Normalization Goals
- Standardize jurisdiction identifiers using **FIPS codes** and **OCD-IDs** (Open Civic Data Division Identifiers)
- Map source-specific election types to a common taxonomy (e.g., "primary," "general," "special")
- Deduplicate candidates appearing across multiple sources using name + district + party matching
- Normalize dates to **ISO 8601** format

### Intended Consumers
- CivicMirror web app (primary)
- Potential public API endpoint (future)

---

## Roadmap

- [ ] Define canonical data schema / JSON structure
- [ ] Prototype ingestion pipeline for Google Civic API
- [ ] Add OpenStates and Ballotpedia adapters
- [ ] Build normalization / deduplication layer
- [ ] Expose unified REST API
- [ ] CivicMirror integration
- [ ] Public API documentation
