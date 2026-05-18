# South Carolina Election Results — Research Notes

**Site:** https://www.scvotes.gov/election-results
**Operated by:** South Carolina Election Commission
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

South Carolina provides election results through the SC Election Commission website (SCVotes.gov) with county-level and precinct-level results.

---

## Data Access

### Election Results
- **URL:** https://www.scvotes.gov/election-results
- County-level and precinct-level results
- Historical results archive
- Downloadable files

---

## API Access

No public REST API identified.

---

## Notes

- 46 counties
- SC Election Commission administers elections
---

## Source Coverage Analysis

South Carolina's SCVotes.gov portal provides county- and precinct-level election results in PDF and Excel formats, but the state source has no API, no ballot measure data, no live results feed, and no candidate profile information. **Clarity Elections** (`results.enr.clarityelections.com`) is documented in `concept.md` as a South Carolina-compatible platform, but the SC research file does not confirm this — this should be verified on the next election cycle. Until confirmed, supplement with **Google Civic Information API** (elections, candidates, district lookups), **Ballotpedia** (ballot measures, candidate bios, incumbency), **OpenStates** (SC state legislative data), **OpenFEC** (federal candidates and finance), and **MEDSL** for normalized historical results.
