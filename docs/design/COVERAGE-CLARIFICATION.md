# CivicMirror Coverage Clarification

## Purpose

This document clarifies what "coverage" means within CivicMirror.

Historically, some discussions interpreted "Full Coverage" as complete support for every election, race, ballot measure, precinct, municipality, and historical record available within a state.

That is not the intended project goal.

---

# Primary Objective

The primary objective of CivicMirror is:

> Provide normalized election and ballot data for Federal and State offices across all 50 states.

Local election coverage is valuable and should be pursued when practical, but it is not required for a state to be considered fully covered.

---

# Coverage Priorities

## Priority 1 — Federal Offices

Federal coverage is the highest priority.

Required offices:

- President
- Vice President
- U.S. Senate
- U.S. House of Representatives

A state cannot be considered fully covered if federal contests cannot be reliably discovered and ingested.

---

## Priority 2 — State Offices

Required state-level coverage:

### Statewide Offices

- Governor
- Lieutenant Governor
- Attorney General
- Secretary of State / Commonwealth
- Treasurer
- Auditor
- Other statewide elected offices

### Legislative Offices

- State Senate
- State House / Assembly

Coverage includes:

- Election discovery
- Race creation
- Candidate creation
- Results ingestion

---

## Priority 3 — Local Offices (Enhanced Coverage)

Examples:

- Mayor
- City Council
- Town Council
- School Board
- County offices
- Special districts

Because local elections are frequently decentralized across thousands of jurisdictions, local coverage is considered an enhancement rather than a requirement.

---

# Historical Data

Historical data is useful for research and analytics.

However:

- Historical backfill is not required for Full Coverage.
- Elections should be preserved once ingested.
- Historical imports may be completed as separate projects.

A state should not lose Full Coverage status simply because historical records have not been backfilled.

---

# Ballot Measures

Ballot measures should be tracked independently from office coverage.

Examples:

- Constitutional amendments
- Referendums
- Initiatives
- Resolutions

Ballot measure support should improve a state's coverage rating, but lack of ballot measures alone should not prevent Full Coverage status when Federal and State offices are fully supported.

---

# Precinct-Level Reporting

Precinct-level reporting is an advanced feature.

Benefits:

- Detailed analysis
- Geographic reporting
- Local election support

Not required for Full Coverage.

---

# Coverage Definitions

## Full Core Coverage

Requirements:

- Federal elections discovered
- Federal races created
- Federal results ingested
- Statewide elections discovered
- Statewide races created
- Statewide results ingested
- State legislative races created
- State legislative results ingested

This is the primary target for all 50 states.

---

## Partial Core Coverage

Requirements:

- Federal coverage working
- State coverage incomplete

Examples:

- Missing legislative races
- Missing statewide offices
- Missing results ingestion

---

## Federal Coverage Only

Requirements:

- Federal contests supported
- State contests incomplete or unavailable

---

## Enhanced Coverage

Additional capabilities beyond Core Coverage:

- Local elections
- Ballot measures
- Precinct reporting
- Candidate biographies
- Candidate contact information
- GIS boundaries
- Historical backfill
- Live election-night reporting

---

# Summary

The CivicMirror coverage goal is:

1. Federal coverage in all 50 states.
2. State-level coverage in all 50 states.
3. Local coverage where practical.
4. Historical and advanced analytics as enhancements.

A state should be considered Fully Covered when Federal and State election information can be reliably discovered, normalized, and ingested into CivicMirror.