# Kentucky observed live-schema fixture

Extracted from official `https://vrsws.sos.ky.gov/liveresults/Data/` XML captured
2026-11-01. Includes legislative, county, municipal multi-seat, school, judicial,
measure and ambiguous state-scoped local examples. Metadata and results were
filtered by ContestId and reporting-unit IDs; names, child elements, wrappers,
and namespaces remain as captured (ElementTree rewrites namespace prefixes).
The source snapshot had 208137 rows, 3333 reported contests, and 293 additional
metadata-only contests. These counts apply only to that snapshot.
