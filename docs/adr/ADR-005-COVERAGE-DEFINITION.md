# ADR-005: CivicMirror Coverage Definition

## Status

Accepted

## Context

The term "Full Coverage" has been used inconsistently throughout CivicMirror documentation.

In some places it referred to:

- Election discovery
- Race creation
- Results ingestion

In other places it implied:

- Local election support
- Historical backfill
- Precinct-level reporting
- Candidate biographies
- GIS boundaries
- Ballot measure enrichment

This created confusion when evaluating state completion.

## Decision

CivicMirror state completion shall be measured using Full Core Coverage.

### Full Core Coverage

A state has Full Core Coverage when CivicMirror can:

- Discover federal elections
- Create federal races
- Ingest federal results
- Discover statewide elections
- Create statewide races
- Ingest statewide results
- Create state legislative races
- Ingest state legislative results

### Coverage Priorities

Priority 1:
- President
- Vice President
- U.S. Senate
- U.S. House

Priority 2:
- Governor
- Statewide executive offices
- State Senate
- State House / Assembly

Priority 3:
- Local elections
- Municipal offices
- County offices
- School boards
- Special districts

### Enhanced Coverage

The following capabilities are enhancements and are not required for Full Core Coverage:

- Local elections
- Ballot measures
- Precinct reporting
- Historical backfill
- Candidate biographies
- Candidate contact information
- GIS boundaries
- Live reporting enhancements

## Consequences

States may be considered complete even when enhanced features remain incomplete.

Massachusetts, Arizona, Colorado, South Carolina, Virginia, and West Virginia currently meet the intended definition of Full Core Coverage.

Future state reviews should evaluate Federal and State office support first before considering enhancement areas.