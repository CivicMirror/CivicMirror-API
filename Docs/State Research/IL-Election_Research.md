# Illinois Election Results — Research Notes

**Site:** https://www.elections.il.gov/electionoperations/ElectionVoteTotals.aspx
**Results Search:** https://www.elections.il.gov/electionoperations/votetotalsearch.aspx
**Operated by:** Illinois State Board of Elections
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Illinois provides election results through the State Board of Elections website with searchable results, downloadable vote totals, and historical data. County-by-county results are available for federal, statewide, legislative, and judicial offices from 1998 onward. Local election results are handled by 108 individual election authorities.

---

## Data Access

### Vote Total Search
- **URL:** https://www.elections.il.gov/electionoperations/votetotalsearch.aspx
- Search by office name or candidate last name
- Downloadable vote totals
- Includes ballots cast and voter registration totals
- Elections available: 2009–2025 (Primaries, Generals, Consolidateds, Specials)

### Election Results Page
- **URL:** https://www.elections.il.gov/electionoperations/ElectionResults.aspx
- Election authority contact information for unofficial results
- Links to local jurisdiction websites

### Official Vote Total Book
- Published for each election cycle
- Contains comprehensive results data

### Voter File
- Available in Microsoft Access and comma-delimited text formats
- Single-file format (voter + voting history combined)
- Multi-file normalized format (three tables: voter, subdivision, history)
- Includes up to last 15 elections of voting history per voter

---

## API Access

No public REST API identified. Data access is through:
1. Searchable results database on SBE website
2. Downloadable vote totals
3. Official Vote Total Book (PDF)
4. 108 individual election authority websites for local results

---

## Notes

- 108 election authorities: 102 county clerks + 6 municipal (Chicago, Bloomington, Rockford, Galesburg, Danville, East St. Louis)
- Local/unofficial results not reported to State Board
- County-by-county data available from 1998 onward
- Voter file available with history for qualified requestors
---

## Source Coverage Analysis

Illinois's State Board of Elections is one of the stronger state sources in this batch, explicitly covering all four required election types (Primary, General, Consolidated, Special) from 2009 onward with county-level results and a voter file with 15-election history. However, ballot measures, candidate biographical/contact data, official/incumbent records, and geographic boundary data are entirely absent, and live results are fragmented across 108 independent election authorities. **Ballotpedia** and **Google Civic Information API** are the primary recommended supplements for candidate profiles, ballot measures, and district boundaries; **OpenStates** covers state legislative incumbents; and individual election authority websites (or a **Clarity Elections** aggregation) should be evaluated for live result ingestion.
