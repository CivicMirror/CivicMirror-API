# ADR-005: CivicMirror Coverage Definition

## Status

Accepted

## Context

The term "Full Coverage" has been used inconsistently throughout CivicMirror documentation.

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

Priority 1
- President
- Vice President
- U.S. Senate
- U.S. House

Priority 2
- Governor
- Statewide executive offices
- State Senate
- State House / Assembly

Priority 3
- Local elections
- Municipal offices
- County offices
- School boards
- Special districts

### Federal Coverage Strategy

Federal coverage across all 50 states is considered achievable.

No single source currently provides complete nationwide Federal election coverage.

State election authorities remain the authoritative source for:

- Election discovery
- Candidate discovery
- Official results

Supplemental sources include:

- Google Civic API
- Federal Election Commission (FEC)
- OpenElections
- MEDSL
- MIT Election Data resources

Google Civic API should be treated as a supplemental source rather than the sole authoritative source.

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

Federal coverage across all 50 states remains the primary CivicMirror objective.

Future state reviews should evaluate Federal and State office support first before considering enhancement areas.