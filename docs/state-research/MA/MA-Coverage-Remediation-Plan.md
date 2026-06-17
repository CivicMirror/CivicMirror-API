# Massachusetts Coverage Remediation Plan

## Executive Summary

After reviewing the CivicMirror concept and project goals, Massachusetts should be evaluated against **Core Coverage**, not perfect coverage.

### CivicMirror Coverage Goal

Priority order:

1. Federal offices
   - President / Vice President
   - U.S. Senate
   - U.S. House

2. State offices
   - Governor / Lieutenant Governor
   - Statewide executive offices
   - State Senate
   - State House
   - Other statewide elected offices

3. Local offices (enhanced coverage)
   - Mayor
   - Town Council
   - School Board
   - County offices
   - Special districts

Local coverage is desirable but is **not required** for Massachusetts to be considered fully covered.

Historical backfill is also not required for full coverage. Historical data should accumulate naturally as elections are ingested over time.

---

# Revised Coverage Assessment

## Current Assessment

Federal Coverage: Likely Complete
State Coverage: Likely Complete
Results Ingestion: Working
Race Creation: Working
Election Discovery: Working

Enhanced Coverage Areas:

- Ballot question result ingestion
- Local election coverage
- Precinct-level reporting
- Historical backfill
- Additional metadata enrichment

Based on the project's stated goals, Massachusetts appears much closer to Full Coverage than originally assessed.

---

# High Priority Items (Core Coverage)

These items should be verified because they directly impact the Federal + State coverage goal.

## 1. Verify Federal Race Discovery

Confirm the system consistently discovers:

- President / Vice President
- U.S. Senate
- U.S. House districts

Acceptance Criteria:

- Elections created
- Races created
- Candidates linked
- Results imported

---

## 2. Verify State Race Discovery

Confirm the system discovers:

- Governor
- Lieutenant Governor
- Attorney General
- Secretary of the Commonwealth
- Treasurer
- Auditor
- Governor's Council
- State Senate
- State House

Acceptance Criteria:

- Elections created
- Races created
- Candidates linked
- Results imported

---

## 3. Improve Primary Discovery

Current implementation appears to search:

```python
["General", "Primaries"]
```

Massachusetts may expose party-specific primary stages.

Recommendation:

Add support for additional primary stage names to avoid missing state and federal primary contests.

---

## 4. Improve Election Date Accuracy

Election dates should come directly from ElectionStats whenever possible.

Preferred order:

1. ElectionStats
2. OCPF
3. Fallback logic

This is a quality improvement rather than a coverage blocker.

---

# Enhanced Coverage Items (Not Required for Full Coverage)

The following items are valuable but should not determine whether Massachusetts is considered fully covered.

## Ballot Question Results

Current implementation appears to create ballot question races but does not fully ingest vote totals.

Future enhancement:

- Yes votes
- No votes
- Blank votes
- Total votes cast

---

## Local Elections

Municipal and local office coverage.

Examples:

- Mayor
- City Council
- School Committee
- Select Board
- Town Clerk

Useful but not required for Core Coverage.

---

## Precinct-Level Results

Precinct-level reporting provides additional analytics but is not required for state/federal coverage.

---

## Historical Backfill

PD43+ contains extensive historical information.

Recommendation:

Treat historical backfill as a separate project.

Do not block Massachusetts Full Coverage status on historical imports.

---

# Recommended Massachusetts Status

## Current Recommendation

```text
MA — Full Core Coverage
Federal offices: Covered
State offices: Covered
Results ingestion: Covered
```

## Enhanced Coverage Status

```text
Ballot Questions: Partial
Local Elections: Partial
Precinct Reporting: Not Implemented
Historical Backfill: Not Implemented
```

---

# Completion Criteria

Massachusetts should be considered fully covered when:

- Federal elections are discovered.
- Federal races are created.
- Federal results are ingested.
- Statewide elections are discovered.
- Statewide races are created.
- Statewide results are ingested.
- State legislative races are created.
- State legislative results are ingested.

Everything else should be tracked as Enhanced Coverage rather than a blocker to Full Coverage.