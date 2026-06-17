# Massachusetts Coverage Remediation Plan

## Executive Summary

Massachusetts is currently marked as "Full Coverage" in the CivicMirror state index. After reviewing the implementation, the state is close to full coverage but still has several gaps that prevent it from being considered fully complete.

Current assessment:

- Election discovery: Good, but incomplete.
- Race creation: Good.
- Candidate result ingestion: Good.
- Ballot question result ingestion: Incomplete.
- Historical coverage: Incomplete.
- Precinct-level coverage: Incomplete.
- Election date accuracy: Needs improvement.

Recommended status until remediation is complete:

> MA — Candidate elections mostly complete; ballot questions, historical backfill, date accuracy, and precinct-level ingestion pending.

---

# Findings

## 1. Historical Coverage Is Limited

Current sync logic only searches the current year and previous year.

Impact:

- Does not leverage the full historical depth available through Massachusetts ElectionStats (PD43+).
- Historical election coverage is significantly underutilized.

Recommendation:

Implement configurable historical backfill support.

Example:

```python
MA_SYNC_YEAR_FROM = 1970
MA_SYNC_YEAR_TO = current_year
```

Provide:

- Daily sync mode (recent years only)
- Full backfill command (1970-present)

---

## 2. Primary Discovery May Be Incomplete

Current implementation searches:

```python
["General", "Primaries"]
```

Massachusetts ElectionStats exposes party-specific primary stages.

Recommendation:

Expand stage discovery to include:

```python
[
  "General",
  "Democratic Primaries",
  "Republican Primaries",
  "Green-Rainbow Primaries",
  "Libertarian Primaries",
  "Working Families Primaries",
  "United Independent Primaries"
]
```

This reduces the risk of missing elections that are categorized by party rather than a generic primary stage.

---

## 3. Election Dates Should Come From ElectionStats

Current mapping logic derives election dates primarily from OCPF schedules.

Problem:

- OCPF dates are useful for filing schedules.
- OCPF is not necessarily the best source of truth for election dates.
- Special elections can be assigned incorrect dates.

Recommendation:

Election date resolution order:

1. ElectionStats election date
2. OCPF schedule date
3. Year-only fallback with warning log

Implementation:

Enhance ElectionStats parsers to extract election dates directly from search results or election detail pages.

---

## 4. Ballot Question Results Are Not Fully Ingested

Current state:

- Ballot question races are created.
- Yes/No options are created.
- Vote totals are not fully imported.

Impact:

Stage 2 results coverage is incomplete for ballot measures.

Recommendation:

Use ballot question CSV downloads:

```python
csv_bytes = client.download_bq_csv(bq_id)
totals = parsers.parse_bq_csv(csv_bytes)
```

Store:

- Yes votes
- No votes
- Blank votes
- Total votes cast

---

## 5. Results Adapter Needs Ballot Question Support

Current MA results adapter focuses on candidate-election CSV exports.

Gap:

Ballot question downloads are not processed through the results ingestion path.

Recommendation:

Extend the MA adapter to:

- detect ballot question races
- download ballot-question CSVs
- ingest Yes/No totals
- create result rows consistent with candidate races

---

## 6. Add Precinct-Level Coverage

Current implementation uses municipality-level aggregation.

Precinct support exists at the source level but is not fully ingested.

Recommendation:

Add support for:

```python
granularity = "municipality" | "precinct"
```

Store:

```python
{
  "locality": "...",
  "ward": "...",
  "precinct": "...",
  "granularity": "precinct"
}
```

Example jurisdiction labels:

```text
Boston Ward 03 Precinct 01
Springfield Ward 05 Precinct A
```

Benefits:

- Precinct-level analysis
- Future district mapping
- Local election support

---

## 7. Improve Official vs Unofficial Status Handling

Current implementation generally treats ElectionStats results as official.

Recommendation:

Use explicit certification handling.

Example:

```python
if election.status in completed_or_certified:
    result_type = "official"
else:
    result_type = "unofficial"
```

Or:

```python
source_metadata["pd43_certified"] = True
```

when certification can be verified.

---

## 8. Improve Source Metadata

Current metadata is minimal.

Recommendation:

Store additional normalized metadata:

```python
{
  "electionstats_id": election_id,
  "office": office,
  "district": district,
  "stage": stage,
  "locality": locality,
  "county": county
}
```

Benefits:

- Easier debugging
- Better deduplication
- Simpler future migrations

---

# Testing Plan

Add tests for:

## Election Discovery

- Historical backfill ranges
- Party-specific primary stages
- Special election discovery

## Election Mapping

- ElectionStats date extraction
- OCPF fallback behavior

## Ballot Questions

- Statewide ballot questions
- Local ballot questions
- Yes/No result imports

## Results

- Candidate CSV imports
- Ballot-question CSV imports
- Official vs unofficial result states

## Geography

- Municipality parsing
- Precinct parsing
- Ward parsing

## Regression Protection

- Hash/version change detection
- CSV format drift
- ElectionStats layout changes

---

# Completion Criteria

Massachusetts can be considered fully covered when all of the following are true:

- Historical election backfill implemented.
- Party-specific primary discovery implemented.
- Election dates sourced from ElectionStats.
- Ballot question vote totals imported.
- Ballot question results adapter implemented.
- Precinct-level results supported.
- Certification handling improved.
- Expanded metadata available.
- Test coverage added.

---

# Recommended Status Changes

Current:

```text
MA — Full Coverage
```

Interim:

```text
MA — Candidate elections mostly complete; ballot questions, historical backfill, date accuracy, and precinct-level ingestion pending.
```

Final:

```text
MA — Full Coverage: candidate elections, ballot questions, historical backfill, municipality and precinct results via PD43+ CSV.
```
