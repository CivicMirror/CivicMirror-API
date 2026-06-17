# CivicMirror Coverage Clarification

## Purpose

This document clarifies what "coverage" means within CivicMirror.

Historically, some discussions interpreted "Full Coverage" as complete support for every election, race, ballot measure, precinct, municipality, and historical record available within a state.

That is not the intended project goal.

## Primary Objective

Provide normalized election and ballot data for Federal and State offices across all 50 states.

## Federal Coverage Feasibility

Federal coverage across all 50 states is considered achievable.

However, no single source currently provides complete nationwide Federal election coverage.

Google Civic API is a useful supplemental source but should not be treated as the sole authoritative source for Federal election discovery.

### Recommended Federal Coverage Strategy

1. State election authority sources (authoritative)
   - Election discovery
   - Candidate discovery
   - Official results

2. Google Civic API (supplemental)
   - Address-based contest lookup
   - Candidate enrichment
   - District validation

3. Federal Election Commission (FEC)
   - Candidate metadata
   - Committee data
   - Campaign finance data

4. Historical and validation sources
   - OpenElections
   - MEDSL
   - MIT Election Data sources

The long-term CivicMirror goal is to normalize these fragmented sources into a single nationwide election data platform.

## Coverage Priorities

### Priority 1 — Federal Offices
- President
- Vice President
- U.S. Senate
- U.S. House of Representatives

### Priority 2 — State Offices
- Governor
- Lieutenant Governor
- Attorney General
- Secretary of State / Commonwealth
- Treasurer
- Auditor
- Other statewide elected offices
- State Senate
- State House / Assembly

### Priority 3 — Local Offices (Enhanced Coverage)
- Mayor
- City Council
- Town Council
- School Board
- County offices
- Special districts

Local coverage is desirable but not required for Full Core Coverage.

## Coverage Definitions

### Full Core Coverage
- Federal elections discovered
- Federal races created
- Federal results ingested
- Statewide elections discovered
- Statewide races created
- Statewide results ingested
- State legislative races created
- State legislative results ingested

### Partial Core Coverage
- Federal coverage working
- State coverage incomplete

### Federal Coverage Only
- Federal contests supported
- State contests incomplete or unavailable

### Enhanced Coverage
- Local elections
- Ballot measures
- Precinct reporting
- Candidate biographies
- Candidate contact information
- GIS boundaries
- Historical backfill
- Live election-night reporting

## Summary

The CivicMirror coverage goal is:
1. Federal coverage in all 50 states.
2. State-level coverage in all 50 states.
3. Local coverage where practical.
4. Historical and advanced analytics as enhancements.