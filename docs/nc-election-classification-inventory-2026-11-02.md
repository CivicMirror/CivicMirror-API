# NC election classification evidence inventory — 2026-11-02

Issue: [#188](https://github.com/CivicMirror/CivicMirror-API/issues/188). Companion: [machine-readable inventory](nc-election-classification-inventory-2026-11-02.json).

This is a refreshed evidence inventory for the legacy `integrations/nc_sbe` pipeline. It assigns no replacement election types and makes no production changes. Ambiguous cases remain held. The separate CM2 pipeline is outside the repair scope.

## Snapshot and coverage

- Local production was read at `2026-11-02T13:19:34.653135+00:00` in a PostgreSQL `REPEATABLE READ, READ ONLY` transaction; `transaction_read_only=on` was confirmed.
- **55 Elections**: 25 `special`, 13 `primary`, 17 `general`. The August issue comment's 25-special count still matches, but excludes affected primary/general dates.
- **19,029 race rows**, including **680 superseded audit rows**; 18,349 excluding superseded rows. These are database counts, not an assertion that every remaining race is unique.
- Dependent records: 45,924 candidates, 50,840 official-result records, 171 source records linked through candidates, zero linked through races, and zero mock votes. Candidate/result counts include superseded records.
- **All 17 annual filing CSVs, 2010–2026, exist and contain `is_unexpired`, `has_primary`, `is_partisan`, and `party_contest`.** No year-wide pre-2016 signal gap was found. The nine pre-2016 stored `special` Elections all have filing rows.
- The CSVs contain 137,094 raw rows across 66 dates. **54/55 stored dates have filing rows**; 2022-12-06 is the exception. Twelve additional CSV dates have no stored Election.
- **67 results URLs checked**: 52 readable archives (11 legacy comma-delimited layouts, 41 modern TSV layouts), two official `Data Unavailable` placeholders, and 13 HTTP 404s. Twelve 404s are the filing-only dates; the remaining one is the stored 2024-05-14 date.
- 29 stored dates contain both TRUE and FALSE unexpired flags, including 26 dates currently labeled primary/general. This is evidence of mixed term attributes, not an automatic count of mixed election types.

The official [Candidate Lists page](https://www.ncsbe.gov/results-data/candidate-lists) links the historical files. Directory listing, rather than guessing `Candidate_Listing_YEAR.csv`, is necessary: 2010–2013 and 2015 use lowercase `listing`; 2014 uses `_rev1`. Raw CSVs include candidate contact fields and remain in `/tmp/nc188-evidence`; the repository inventory stores aggregates, public contest evidence, URLs, timestamps, ETags and SHA-256 hashes only.

## Corrections and classification limits

1. **Historical coverage starts at least as early as 2010 in this audit.** The published filenames differ from the uniform pattern in the August comment. A 404 for a constructed filename does not establish that the year has no filing data. All requested years now have usable signal columns; individual date/contest coverage must still be checked.
2. **The four filing fields do not identify election phase.** Both the May 6, 2014 first primary and July 15 second primary include `(is_unexpired=FALSE, has_primary=TRUE, is_partisan=TRUE, party_contest=DEM/REP)`. The legacy results field named `runoff_status` is also `0` throughout the 2010-06-22 second-primary file; its name must not be treated as a decoded phase signal.
3. **`is_unexpired` is a term attribute, not an election-type classifier.** The July 9, 2019 CD03 special second primary has 34 TRUE rows, all REP nomination rows. The issue comment incorrectly calls it a special general date. On September 10, CD03 has 68 TRUE rows, CD09 has 32 FALSE rows, and municipal primary contests contribute another 32 FALSE rows. Both congressional contests were special general elections. Dobson's March 7, 2023 rerun has three FALSE rows.
4. **Municipal prefixes are incomplete historical evidence.** For example, the 2013 filing CSV uses `MURPHY MAYOR` and `WINSTON-SALEM MAYOR`, while results may use `CITY OF ...`. A zero prefix count does not mean no municipal contests. `is_partisan` also cannot distinguish municipal primaries from municipal general elections or runoffs.
5. **An ENRS folder or readable ZIP is not proof of occurred/certified results.** The 2026-11-03 ZIP already exists on November 2 and contains 141,466 precinct-choice rows, all with zero total votes. No completeness or certification claim is made from these files.

## Schedule evidence requiring explicit treatment

These are source-supported event descriptions, not final assignments to the existing single `Election.election_type` field. They show that phase, special/rerun context and municipal scope can overlap.

| Date | Stored type | Evidence and implication |
| --- | --- | --- |
| 2012-07-17 | `special` | Official second-primary date; local non-nomination rows also occur. Do not classify every contest from the date alone. [Official source](https://www.ncsbe.gov/blog/2012/05/14/numbered-memo-2012-14-voter-registration-and-voting-process-second-primaries). |
| 2014-07-15 | `special` | Official second primary. Filing flags overlap first-primary flags. [Official source](https://www.ncsbe.gov/news/press-releases/2014/07/15/nc-voters-finalize-primary-picks-november). |
| 2016-06-07 | `special` | Separate congressional primary, with other contests possible. Not a generic special or an assumed second primary. [Official source](https://www.ncsbe.gov/blog/2016/02/26/numbered-memo-2016-03-information-regarding-march-15-and-june-7-primaries). |
| 2019-04-30 | `special` | CD03 special primary; unexpired TRUE does not determine nomination phase. [Official source](https://www.fec.gov/updates/north-carolina-special-election-reporting-3rd-district-2019/). |
| 2019-05-14 | `primary` | CD09 special-primary schedule; current type primary hides its special context. [Official source](https://www.fec.gov/updates/north-carolina-special-election-reporting-9th-district-2019/). |
| 2019-07-09 | `special` | CD03 special second primary: the feed contains only the REP CD03 contest. The August audit incorrectly called this a special general date. [Official source](https://www.fec.gov/updates/north-carolina-special-election-reporting-3rd-district-2019/). |
| 2019-09-10 | `special` | Mixed date: CD03 special general, CD09 special general, and municipal primary contests. CD09 filings are unexpired FALSE. [Official source](https://www.fec.gov/updates/north-carolina-special-election-reporting-9th-district-2019/). |
| 2020-06-23 | `special` | Official memo identifies a CD11 second primary and a new primary in Columbus County on the same date. [Official source](https://www.ncsbe.gov/blog/2020/06/01/numbered-memo-2020-12-covid-19-response-planning-person-voting). |
| 2022-07-26 | `special` | Municipal elections and local second primaries share the date; unexpired FALSE does not resolve phase. [Official source](https://www.ncsbe.gov/news/events/one-stop-early-voting-period-ends-july-26-elections-municipals-and-local-second-primaries-where). |
| 2022-12-06 | `special` | Nash County school-board District 8 runoff. No rows for this date in the annual filing CSV; result and schedule evidence exist. [Official source](https://www.ncsbe.gov/news/press-releases/2022/12/19/state-board-orders-new-election-dobson-certifies-runoff-nash-and-edgecombe-counties). |
| 2023-03-07 | `primary` | Board-ordered Dobson municipal rerun; stored as primary although all three filing rows have no primary signal and unexpired FALSE. [Official source](https://www.ncsbe.gov/news/press-releases/2022/12/19/state-board-orders-new-election-dobson-certifies-runoff-nash-and-edgecombe-counties). |
| 2024-05-14 | `primary` | Official second-primary date; stored as primary. Results ZIP currently 404; 420 filing rows remain available. [Official source](https://www.ncsbe.gov/blog/2024/03/14/numbered-memo-2024-02-second-primary-preparations). |

The 2019 FEC schedules include conditional dates. For July 9, the downloaded results contain the REP CD03 contest only; the filing rows also all carry `party_contest=REP`. The event is therefore the special second primary described in the schedule, not its conditional general-election alternative. For September 10, CD03 and CD09 general contests and Charlotte nomination contests must be represented without treating all FALSE rows as ordinary municipal/general contests.

## Every stored NC Election

`Races` excludes `nc_superseded_by` audit rows. `Filings / TRUE` counts raw filing rows and their TRUE unexpired subset. `Legacy CSV` and `TSV` indicate source layouts only. A placeholder or 404 is an explicit source state, not a zero-contest election. All rows remain unclassified by this inventory.

| ID | Date | Stored type | Races | Filings / TRUE | Results evidence |
| --- | --- | --- | ---: | ---: | --- |
| 1948 | 2010-05-04 | `primary` | 2 | 3,610 / 15 | Legacy CSV |
| 1949 | 2010-06-22 | `special` | 1 | 272 / 0 | Legacy CSV |
| 1950 | 2010-11-02 | `general` | 1 | 5,481 / 20 | Legacy CSV |
| 1951 | 2011-09-13 | `special` | 0 | 32 / 0 | Legacy CSV |
| 1952 | 2011-10-11 | `special` | 0 | 246 / 3 | Legacy CSV |
| 1953 | 2011-11-08 | `general` | 0 | 3,003 / 30 | Legacy CSV |
| 1954 | 2012-05-08 | `primary` | 110 | 8,148 / 10 | Legacy CSV |
| 1955 | 2012-07-17 | `special` | 10 | 1,126 / 0 | Legacy CSV |
| 1956 | 2012-11-06 | `general` | 183 | 5,615 / 29 | Legacy CSV |
| 1957 | 2013-09-10 | `special` | 0 | 78 / 0 | Legacy CSV |
| 1958 | 2013-10-08 | `special` | 0 | 290 / 0 | Legacy CSV |
| 1959 | 2013-11-05 | `general` | 0 | 3,079 / 56 | Data Unavailable |
| 1960 | 2014-05-06 | `primary` | 451 | 3,632 / 44 | TSV |
| 1961 | 2014-07-15 | `special` | 19 | 84 / 0 | TSV |
| 1962 | 2014-11-04 | `general` | 1,392 | 6,408 / 37 | TSV |
| 1963 | 2015-05-12 | `primary` | 0 | 3 / 3 | Data Unavailable |
| 1964 | 2015-09-15 | `special` | 10 | 37 / 0 | TSV |
| 1965 | 2015-10-06 | `special` | 60 | 252 / 0 | TSV |
| 1966 | 2015-11-03 | `general` | 1,135 | 3,211 / 69 | TSV |
| 1967 | 2016-03-15 | `primary` | 364 | 8,131 / 4 | TSV |
| 1968 | 2016-06-07 | `special` | 45 | 841 / 0 | TSV |
| 1969 | 2016-11-08 | `general` | 996 | 6,497 / 13 | TSV |
| 1970 | 2017-09-12 | `special` | 10 | 44 / 0 | TSV |
| 1971 | 2017-10-10 | `special` | 79 | 410 / 0 | TSV |
| 1972 | 2017-11-07 | `general` | 1,079 | 3,110 / 47 | TSV |
| 1973 | 2018-05-08 | `primary` | 418 | 1,646 / 6 | TSV |
| 1974 | 2018-06-26 | `special` | 2 | 4 / 0 | TSV |
| 1975 | 2018-11-06 | `general` | 1,465 | 3,799 / 17 | TSV |
| 1976 | 2019-04-30 | `special` | 6 | 425 / 425 | TSV |
| 1977 | 2019-05-14 | `primary` | 4 | 85 / 0 | TSV |
| 1978 | 2019-07-09 | `special` | 2 | 34 / 34 | TSV |
| 1979 | 2019-09-10 | `special` | 12 | 132 / 68 | TSV |
| 1980 | 2019-10-08 | `special` | 63 | 244 / 6 | TSV |
| 1981 | 2019-11-05 | `general` | 1,070 | 2,930 / 57 | TSV |
| 1982 | 2020-03-03 | `primary` | 472 | 11,442 / 14 | TSV |
| 1983 | 2020-06-23 | `special` | 3 | 37 / 0 | TSV |
| 1984 | 2020-11-03 | `general` | 1,283 | 7,380 / 26 | TSV |
| 1985 | 2021-10-05 | `special` | 13 | 98 / 0 | TSV |
| 1986 | 2021-11-02 | `general` | 919 | 2,689 / 63 | TSV |
| 1987 | 2022-05-17 | `primary` | 734 | 6,037 / 22 | TSV |
| 1988 | 2022-07-26 | `special` | 55 | 111 / 0 | TSV |
| 1989 | 2022-11-08 | `general` | 1,477 | 4,620 / 42 | TSV |
| 1990 | 2022-12-06 | `special` | 1 | No rows | TSV |
| 1991 | 2023-03-07 | `primary` | 1 | 3 / 0 | TSV |
| 1992 | 2023-09-12 | `special` | 7 | 21 / 0 | TSV |
| 1993 | 2023-10-10 | `special` | 47 | 262 / 0 | TSV |
| 1994 | 2023-11-07 | `general` | 981 | 2,940 / 76 | TSV |
| 1995 | 2024-03-05 | `primary` | 401 | 9,616 / 15 | TSV |
| 1996 | 2024-05-14 | `primary` | 1 | 420 / 0 | 404 |
| 1997 | 2024-11-05 | `general` | 1,216 | 7,024 / 61 | TSV |
| 1998 | 2025-09-09 | `special` | 10 | 35 / 0 | TSV |
| 1999 | 2025-10-07 | `special` | 50 | 235 / 0 | TSV |
| 2000 | 2025-11-04 | `general` | 951 | 2,849 / 63 | TSV |
| 1909 | 2026-03-03 | `primary` | 553 | 3,761 / 19 | TSV |
| 1910 | 2026-11-03 | `general` | 185 | 4,527 / 64 | TSV |

## Filing-only dates: held

These dates occur in the annual filing CSVs but have no stored Election and no results ZIP at the standard URL. Some may reflect planned, rerun, local or cancelled events. The inventory does not decide which occurred and does not create Elections.

| Date | Filing rows | TRUE unexpired rows | Results ZIP |
| --- | ---: | ---: | --- |
| 2010-02-23 | 2 | 0 | 404 |
| 2010-03-09 | 2 | 0 | 404 |
| 2010-03-16 | 2 | 0 | 404 |
| 2011-04-05 | 2 | 2 | 404 |
| 2011-04-26 | 10 | 0 | 404 |
| 2011-05-24 | 2 | 0 | 404 |
| 2012-06-26 | 8 | 0 | 404 |
| 2013-03-19 | 1 | 1 | 404 |
| 2014-03-11 | 8 | 2 | 404 |
| 2014-12-02 | 6 | 0 | 404 |
| 2019-01-29 | 2 | 2 | 404 |
| 2019-07-23 | 3 | 3 | 404 |

## Boundaries for a later design

- Separate sourced phase (primary / second primary / general / runoff), special or rerun context, and municipal scope before choosing how to represent them in the current enum. Do not use `unexpired TRUE => special` or month-only rules.
- Resolve classifications at contest level and retain explicit unknown/conflicting evidence. Filing county repetition and results `(title, type, group ID)` combinations are reporting evidence, not proof of a shared electorate.
- Inventory routing changes together: date discovery, candidate selection (currently one Election per date), result filtering before bootstrap, source links, and dependent race keys. Classification changes must converge across every ingestion path.
- Preserve NC contest identities and `nc_superseded_by` records from the earlier repair. The five previously held conflict components and boundary-unknown local splits are not resolved by this audit; no historical repair is applied or reopened.
- A future migration needs a new source-qualified dry-run, reviewed target mapping/fingerprint, backup and rollback, transactional relationship preservation, and repeated-sync/idempotency checks. This inventory is not an approved repair report.

## Method and limitations

The production transaction exported Election IDs, keys, statuses, review flags, source-link summaries, and selected race identity fields; it did not export candidate names, contact fields, votes by user or raw source payloads. Source records and candidate/result counts are reported separately from active race counts. Per-election race fingerprints in the JSON cover the inspected identity state and are not a substitute for a future repair fingerprint.

For each year, S3 ListObjectsV2 was paginated until complete. Every CSV under the Candidate Filing prefix was fetched; exactly one was found per audited year. The CSVs were decoded as UTF-8 with BOM handling and replacement for malformed bytes, then grouped by parsed election date and exact normalized title/county/party. Strict UTF-8 validation found malformed bytes only in omitted street-address fields: two rows in 2020 and one in 2025. Date, contest, county and classification fields contain no replacement characters. Results were fetched for the union of stored dates, 2010–2026 ENRS folders, and filing dates. Both historical comma-delimited and modern tab-delimited text members were inspected; missing source group IDs remain absent. Counts intentionally distinguish raw rows, unique names, reporting groups and stored races. No fuzzy name matching or electorate inference was used.

This is a point-in-time snapshot. A filing CSV's existence does not prove completeness or that every planned date occurred; source flags require conflict checks before use. Official schedule pages were checked for selected exceptional dates, not every historical municipal contest. Remaining phase/jurisdiction distinctions stay held. The zero-vote November 2026 archive is pre-election evidence only. No sync, derivation, database write, rekey, deletion, or deployment was performed.

Production snapshot SHA-256: `d6105bf8a051abbff009a5c02469a996ac4dc29f36b4864a29cc3ab22b8ce6fe`. Every downloaded filing/results file has its URL, retrieval timestamp, ETag, last-modified value and SHA-256 in the companion JSON. Schedule-page captures record their own HTTP status, digest and timestamp. A source digest identifies captured bytes; it does not certify the source content.
