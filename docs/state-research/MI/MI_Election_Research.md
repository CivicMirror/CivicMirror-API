# Michigan Election Research — Stage 1

## Coverage Status

| Stage                       | Status                                                  | Notes                                                                                                                                                                                                                                                                                |
| --------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Stage 1 — Election Creation | ⚠️ **Available through a composite adapter**            | Regular statewide dates come from Michigan law and cycle-specific Bureau of Elections calendars. Historical and special-election instances can be discovered from the official results/data index and candidate reports. No single verified state election-event API was identified. |
| Stage 1 — Race Creation     | ⚠️ **Strong for state, federal, and judicial contests** | The official Entellitrak candidate reports expose office, district, term, number of positions, candidates, party/incumbency, filing method, filing date, withdrawals, and disqualifications. Local contests and local ballot questions remain county or local responsibilities.      |
| Stage 2 — Results Ingestion | Not investigated in this update                         | Outside the requested scope.                                                                                                                                                                                                                                                         |

---

**Primary election site:** `https://www.michigan.gov/sos/elections`
**Results and historical index:** `https://www.michigan.gov/sos/elections/election-results-and-data`
**Official candidate-report system:** `https://mi-boe.entellitrak.com/`
**Operated by:** Michigan Department of State, Bureau of Elections
**Researched:** March 4, 2026
**Updated:** August 5, 2026 — verified official Stage 1 election and race creation sources; identified Entellitrak report parameters, historical candidate coverage, ballot-proposal and recall sources, and local-data gaps
**Access status:** Public; no authentication observed for the sources reviewed
**Accessed:** August 5, 2026

---

## Overview

Michigan does not provide a verified, documented first-party REST API for Stage 1. The best official implementation is a **composite pipeline**:

1. Use Michigan election law and the Bureau of Elections calendar to create expected regular election instances.
2. Use the official results/data index to confirm actual statewide, presidential-primary, and special-election instances.
3. Use the state-operated Entellitrak candidate reports to create state, federal, legislative, and judicial races and candidates.
4. Monitor Board of State Canvassers materials for candidate challenges, statewide proposals, recalls, and final ballot qualification.
5. Use county and local clerk sources for contests and questions not included in statewide reports.

The state results/data page describes its reports as statewide and directs users to county sources for local election data. It categorizes August primaries, November general elections, presidential primaries, special primaries, special general elections, recounts, and other reports.

The nonofficial Citizen Labs API mentioned in the original notes should not be used as authoritative evidence. No official API endpoint or official API documentation was verified during this Stage 1 review.

---

## Recommended Source Ranking

### 1. Official Candidate Listing — Entellitrak

**Integration value:** Highest for race and candidate creation
**Source type:** HTML report / HTML scraping
**Entity:** Michigan Department of State, Bureau of Elections
**Authentication:** None observed
**Machine-readability:** Moderate
**Update behavior:** Reports include generation timestamps; refresh frequency is not documented

#### Confirmed report URLs

Primary:

```text
https://mi-boe.entellitrak.com/etk-mi-boe-prod/page.request.do?electionType=PRI&electionYear=2026&page=page.miboePublicReport
```

General:

```text
https://mi-boe.entellitrak.com/etk-mi-boe-prod/page.request.do?electionType=GEN&electionYear=2026&page=page.miboePublicReport
```

2026 special general:

```text
https://mi-boe.entellitrak.com/etk-mi-boe-prod/page.request.do?electionType=SG1&electionYear=2026&page=page.miboePublicReport
```

The query parameters `electionType`, `electionYear`, and `page` are directly observable. `PRI`, `GEN`, and `SG1` are confirmed values. Other election-type codes should not be guessed; discover them from official index links or other first-party pages.

#### Data contained

The official candidate reports contain race headings and candidate rows with fields such as:

* Office and district
* Term length
* Partial-term ending date, where applicable
* Number of positions to elect
* Filing-jurisdiction notes, such as `Files In OAKLAND County`
* Candidate status, including `DISQ` and `WITHD`
* Party
* Incumbency
* Candidate name
* Filing date
* Filing method, including petition, filing fee, convention, or affidavit

The report footer provides a candidate count and report-generation timestamp.

Special-election reports demonstrate that the system can represent:

* Off-cycle elections
* Partial terms
* Candidates nominated through different filing methods
* Candidate addresses

Candidate addresses should normally be retained only as provenance and not ingested into CivicMirror's core public candidate model.

#### Extraction approach

Treat each office heading as a race definition. Treat each following candidate row as belonging to that race until the next office heading.

Extract from race headings:

* Office family
* District number or statewide scope
* Judicial court or division
* Regular or partial term
* Term-ending date
* Number of available positions
* Filing-county note

Extract from candidate rows:

* Source status
* Party
* Incumbency
* Candidate display name
* Filing date
* Filing method

No JSON request, CSV export, official API documentation, pagination scheme, or stable public record identifier was verified.

A HAR capture was not available. The reproducible request record consists of the direct unauthenticated HTTP GET URLs and their visible query parameters.

#### Normalization cautions

* A blank candidate status must not automatically be interpreted as certified when the overall report is labeled unofficial.
* Preserve `DISQ` and `WITHD` as source states rather than silently deleting the records.
* The same person may appear more than once because of amended or withdrawn filings.
* Store source-row history before resolving which candidacy is active.
* Governor and lieutenant governor may appear as a combined ticket.
* Multi-seat board and judicial contests require the `Positions` value.
* Judicial races distinguish incumbent, non-incumbent, full-term, and partial-term seats.
* “Files In [County]” identifies the filing authority but does not necessarily make the race local-only.

---

### 2. Election Results and Data Index

**URL:**

```text
https://www.michigan.gov/sos/elections/election-results-and-data
```

**Integration value:** High for election discovery and historical backfill
**Source type:** HTML index linking HTML reports, result portals, downloadable files, and PDFs
**Authentication:** None
**Machine-readability:** Moderate

This is the strongest state index for enumerating election instances that actually occurred. It includes categories and links for:

* Regular primaries
* Regular general elections
* Presidential primaries
* Special primaries
* Special general elections
* Candidate listings
* Recounts
* Other election reports

#### Historical coverage

* Regular candidate listings are linked back to 1998.
* Selected special-election candidate listings are available from later cycles.
* Historical coverage is not uniform across election types.
* Presidential-primary and special-election candidate listings appear less consistently indexed than regular primary and general reports.
* Results are identified as available from 1998 to the present through the statewide results system.

Older candidate reports may be static HTML pages instead of the current query-generated interface.

Example static candidate-listing pattern:

```text
https://mi-boe.entellitrak.com/candlist/2024GEN_CANDLIST.html
```

#### Stage 1 use

Use the index to:

* Confirm an election’s official name and category.
* Discover historical Entellitrak or static candidate-list URLs.
* Identify special elections that are not evident from the recurring calendar.
* Backfill elections preceding the current report interface.
* Detect gaps requiring Board, gubernatorial, county, or archival research.

---

### 3. Election Calendar and Michigan Election Law

**Calendar URL:**

```text
https://www.michigan.gov/sos/-/media/Project/Websites/sos/Election-Administrators/Election-Dates.pdf
```

**Relevant law:** Michigan Election Law, including MCL 168.641 and MCL 168.613a
**Integration value:** High for expected election creation
**Source type:** Official PDF and official legislative HTML
**Machine-readability:** PDF is low-to-moderate; legislative HTML is moderate

Michigan election law establishes regular May, August, and November election dates. The regular primary is held on the August regular election date. The presidential primary is governed separately and, under the currently published statute, occurs on the fourth Tuesday in February in presidential-election years.

The Bureau of Elections calendar provides cycle-specific dates and deadlines, including:

* Primary election date
* General election date
* Candidate filing deadlines
* Withdrawal deadlines
* Proposal deadlines
* Recall deadlines
* Ballot-certification deadlines
* Early-voting milestones
* Canvass deadlines
* Other statutory administration dates

The calendar warns that dates may be changed through legislation and that the controlling statute governs.

#### Stage 1 use

Use statutory rules to generate **expected regular election shells**, but confirm each election against the current Bureau of Elections calendar and the results/data index before publication.

Recommended election fields:

* Election date
* State election name
* Election family
* Regular or special status
* Statewide or limited-jurisdiction scope
* Calendar revision
* Confirmation status
* Source access date

Do not use the calendar by itself to discover every local May, August, or November election. It primarily supplies dates and deadlines rather than a complete statewide contest manifest.

---

### 4. Board of State Canvassers

**URL:**

```text
https://www.michigan.gov/sos/elections/bsc
```

**Integration value:** High for ballot qualification and exceptional elections
**Source types:** HTML page, meeting PDFs, petition PDFs, staff reports, minutes, and decisions
**Machine-readability:** Mixed; much of the decisive material is PDF

The Board of State Canvassers is responsible for activities including:

* Canvassing state elections
* Canvassing nominating petitions
* Canvassing state ballot-proposal petitions
* Adopting ballot designations and language for statewide proposals

The official Board page provides:

* Meeting notices
* Agendas
* Minutes
* Staff reports
* Candidate-petition challenge reports
* Statewide petition documents
* Statewide petition-status reports
* Recall procedures
* Historical recall materials
* Board decisions affecting ballot qualification

#### Candidate qualification

Use Board records as a secondary authoritative layer when an Entellitrak report shows:

* Disqualification
* Withdrawal
* Pending challenge
* Petition insufficiency
* Another status requiring explanation

Recommended source precedence:

1. Current official candidate report
2. Final Board decision or signed certification record
3. Staff report or agenda material
4. Earlier or unofficial candidate report

Do not treat a staff recommendation as a final Board decision.

---

### 5. Statewide Ballot-Proposal Sources

The Board’s statewide petition-status report tracks fields such as:

* Petition name
* Petition type
* Form-approval status
* Required signature count
* Signature-submission date
* Sample-posting date

The report may cover:

* Constitutional amendments
* Referenda
* Initiated laws

This is useful for **proposal monitoring**, but a circulated or submitted petition is not yet a ballot contest.

#### Recommended proposal lifecycle

```text
form_approved
→ circulating
→ signatures_submitted
→ under_review
→ sufficient / insufficient
→ ballot_language_adopted
→ qualified_for_ballot
→ withdrawn / defeated_before_ballot
```

#### Creation rule

Create a prospective proposal record when the petition enters official state processing. Activate or create the final ballot race only after official evidence establishes:

* Ballot qualification
* Adopted ballot language
* Official proposal designation, where applicable
* Election assignment

Recommended identifiers:

Prequalification:

```text
MI-PETITION|<normalized petition name>|<petition type>|<final filing date>
```

Final ballot contest:

```text
<election_external_id>|proposal|<official designation>
```

Preserve the petition name separately from the final ballot title.

Not every statewide question originates through a citizen petition. Statutorily required questions and legislative referrals require separate monitoring of Board materials, state law, and official ballot-language records.

---

### 6. Recall Source

**Primary source:** Michigan Bureau of Elections Recall Process Manual
**Source type:** PDF
**Machine-readability:** Low-to-moderate
**Scope:** Process guidance rather than a live election feed

The recall process distinguishes matters filed with the Board of State Canvassers from those handled by county election commissions.

State-level procedures may apply to:

* Statewide elected offices
* State and federal legislative offices
* State education boards
* Certain county offices

Many municipal, school, and other local offices are handled through county-level election commissions.

For a sufficient state-level recall petition, the Secretary of State calls a special election on the next regular election date that satisfies the statutory notice period. The incumbent is automatically listed as a candidate unless the incumbent withdraws. Challenger nomination rules differ for partisan and nonpartisan offices.

#### Stage 1 use

Monitor:

* Board meeting materials for recall-language decisions
* Official petition-sufficiency determinations
* The resulting election call
* Candidate filings after the call
* Entellitrak or county candidate reports when published

No machine-readable recall-election feed was identified.

---

### 7. County and Local Sources

**State directory:**

```text
https://www.michigan.gov/sos/elections/election-results-and-data/candidate-listings-and-election-results-by-county
```

The Michigan Department of State directs users to county election websites for candidate listings and election-night results. City or township clerk sites may also be required.

County and local sources are necessary for:

* County offices absent from the state report
* City offices
* Township offices
* Village offices
* School boards
* Library boards
* Special districts
* Local millages
* Bond proposals
* Charter questions
* Local initiatives
* Local recalls
* Local elections held on regular May, August, or November dates

Michigan therefore cannot achieve complete Stage 1 coverage through one statewide adapter.

---

## Source Inventory

| Rank | Source                                     | Entity                                          | Scope                                                                       | Source type                                      | Access             | Machine-readability | Historical coverage                                         | Primary CivicMirror use                                            |
| ---: | ------------------------------------------ | ----------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------ | ------------------ | ------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------ |
|    1 | Entellitrak official candidate reports     | Michigan Bureau of Elections                    | State, federal, legislative, judicial, and selected county-filed races      | HTML report / scraping                           | Public GET request | Moderate            | Current reports plus static historical candidate pages      | Races, candidates, filing status, party, incumbency, qualification |
|    2 | Election Results and Data index            | Michigan Department of State                    | Statewide regular and special elections, results, candidate links, recounts | HTML index and linked files                      | Public             | Moderate            | Generally 1998-present, with uneven coverage by report type | Election discovery, historical backfill, source routing            |
|    3 | Election Dates calendar                    | Michigan Bureau of Elections                    | Cycle-specific election and filing dates                                    | PDF                                              | Public             | Low-to-moderate     | Current and archived calendars when retained                | Expected election creation, deadlines, polling schedule            |
|    4 | Michigan Election Law                      | Michigan Legislature                            | Statutory election dates and procedures                                     | HTML                                             | Public             | Moderate            | Current law; historical versions require separate review    | Election definitions and recurrence rules                          |
|    5 | Board of State Canvassers page and records | Michigan Department of State                    | Candidate challenges, proposals, certification, recalls                     | HTML and PDF                                     | Public             | Mixed               | Current and selected historical records                     | Ballot qualification, proposal lifecycle, exception handling       |
|    6 | Statewide petition-status report           | Board of State Canvassers                       | Statewide initiative, referendum, and amendment petitions                   | PDF                                              | Public             | Low-to-moderate     | Current cycle; older reports vary                           | Prospective proposals and qualification monitoring                 |
|    7 | Recall Process Manual and Board materials  | Bureau of Elections / Board of State Canvassers | State and local recall procedures                                           | PDF and HTML                                     | Public             | Low-to-moderate     | Process-oriented                                            | Recall election creation and workflow                              |
|    8 | County and local election sites            | County, city, township, and local clerks        | Local races and proposals                                                   | HTML, PDF, CSV, vendor portals, or other formats | Varies             | Varies              | Varies by jurisdiction                                      | Complete local contest coverage                                    |

---

## CivicMirror Pipeline Map

| Pipeline stage       | Primary official source                                                         | Extraction and normalization                                                                    |
| -------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Election calendar    | MCL 168.641, MCL 168.613a, BOE calendar PDF                                     | Generate expected regular events and confirm against current BOE publications.                  |
| Election discovery   | Results/data index, report titles and dates, Board and special-election records | Upsert actual statewide and special-election instances.                                         |
| Election type        | Calendar title, results/data category, candidate-report title                   | Normalize primary, general, presidential primary, special primary, special general, and recall. |
| Offices              | Entellitrak race headings                                                       | Separate office family from district, judicial division, term, and seat count.                  |
| Districts            | Entellitrak headings and official district sources                              | Preserve office family with district number; never join on district number alone.               |
| Contests             | Entellitrak headings                                                            | Create one race for each distinct office, district, term class, and seat count.                 |
| Candidates           | Entellitrak candidate rows                                                      | Preserve source name, party, incumbency, filing date, and filing method.                        |
| Filing status        | Entellitrak status and Board decisions                                          | Map withdrawals and disqualifications while retaining status history.                           |
| Ballot qualification | Official candidate report and final Board action                                | Do not infer final qualification from filing alone or from staff recommendations.               |
| Party affiliation    | Entellitrak                                                                     | Preserve source party text and normalize separately.                                            |
| Ballot measures      | Board petition status, decisions, and adopted language                          | Maintain a petition lifecycle and activate the ballot race only after qualification.            |
| Special elections    | Results/data index, official call, candidate reports, Board records             | Create distinct primary and general instances linked by vacancy and office.                     |
| Recalls              | Recall manual, Board records, official election call                            | Model incumbent and challenger rules; local recalls require county research.                    |
| Historical archives  | Results/data index and static candidate HTML                                    | Backfill regular candidate listings to 1998 and indexed special elections.                      |
| Local contests       | County and local clerk sites                                                    | Use jurisdiction-specific adapters or documented manual review.                                 |

---

## Suggested Identifiers and Join Keys

### Election identifier

```text
MI|<YYYY-MM-DD>|<normalized election type>|<jurisdiction or special-office scope>
```

Examples:

```text
MI|2026-08-04|primary|statewide
MI|2026-05-05|special-general|state-senate-35
```

Do not rely on year and Entellitrak `electionType` alone. Multiple special elections may occur in the same year.

### Race identifier

```text
<election_external_id>|<office_family>|<district_or_statewide>|<term_end_or_term_length>|<seat_count>
```

Include judicial division and incumbent/non-incumbent seat class where applicable.

### Candidate identifier

No stable public candidate ID was visible in the reviewed report. Use a provisional composite:

```text
<race_external_id>|<normalized source name>|<party>|<filed_on>|<filing_method>
```

Also retain:

* Exact source name
* Full source-row hash
* Report-generation timestamp
* Source URL
* Status history

This helps prevent destructive merging when amended, duplicate, withdrawn, or disqualified filings appear.

### Ballot-proposal identifiers

Before qualification:

```text
MI-PETITION|<normalized petition name>|<petition type>|<filing date>
```

After qualification:

```text
<election_external_id>|proposal|<official designation>
```

---

## Update Strategy

### Regular primary

1. Create the expected election from statute and the BOE calendar.
2. Begin polling the candidate report near the filing period.
3. Poll daily during filing, withdrawal, petition-challenge, and Board-decision windows.
4. Preserve every full-report version, or at minimum its timestamp and content hash.
5. Freeze a qualified candidate snapshot only after the report is official and relevant Board actions are final.

### General election

An early general-election report may be labeled unofficial and may exist before the primary is complete. Treat it as an evolving pre-election manifest, not as the final ballot.

Continue polling after:

* Primary certification
* Party conventions
* Independent-candidate deadlines
* Withdrawal deadlines
* Judicial filing events
* Write-in filing events
* Final Board decisions

### Special elections and recalls

1. Monitor the results/data index and Board records for newly called elections.
2. Create the election immediately from an official call or official candidate report.
3. Do not assume or invent special-election URL codes.
4. Link special primary and special general elections through the vacant office and partial-term ending date.

### Ballot measures

1. Poll the Board page and petition-status reports.
2. Preserve all linked petition, staff-report, and decision PDFs.
3. Require human review when:

   * The Board deadlocks
   * Litigation is pending
   * Signature sufficiency remains unresolved
   * Final ballot language has not been adopted

---

## Corrections and Additions to the Original Research File

1. **Third-party API classification:** `michiganelections.io` may be useful for comparison but is not an official Michigan source and should not be part of the primary evidence chain.
2. **Official Stage 1 source identified:** The Michigan Department of State Entellitrak candidate-report system is the principal official race and candidate source.
3. **Historical candidate coverage clarified:** Regular candidate-list links extend back to 1998, with selected special-election listings also available.
4. **Local completeness clarified:** The statewide index does not cover every local election, contest, or ballot question.
5. **Ballot-measure workflow added:** Board petition-status and meeting records provide the authoritative statewide proposal-qualification path.
6. **Recall workflow added:** The state recall manual and Board records describe a separate election-creation path not covered by the regular candidate adapter.
7. **API classification corrected:** No official Michigan REST API was verified. Entellitrak should be classified as HTML scraping, not API access.

---

## Known Gaps and Human-Review Items

* No official JSON, CSV, or documented API was found for candidate listings.
* Entellitrak exposes no visible stable race or candidate identifiers.
* A complete official inventory of Entellitrak election-type codes was not found.
* Michigan does not publish one master list containing every local election and proposal.
* Special-election discovery remains distributed across results indexes, official calls, candidate reports, Board records, and sometimes other official notices.
* Historical presidential-primary and special-election candidate coverage is inconsistently indexed.
* Candidate qualification can change because of withdrawals, petition challenges, Board decisions, or court action.
* Petition-status reports describe proposals in process, not necessarily proposals qualified for the ballot.
* Much of the Board and recall evidence is PDF-only and should be retained for human review.
* No HAR was captured.
* No hidden or undocumented network endpoint is asserted.

---

## Stage 1 Recommendation

Implement Michigan Stage 1 through two coordinated layers:

1. **State election and race adapter**

   * Bureau of Elections calendar
   * Michigan election law
   * Results/data index
   * Entellitrak candidate listings
   * Board of State Canvassers records

2. **County and local discovery layer**

   * County election sites
   * City, township, and village clerk sites
   * School and special-district sources where necessary
   * Local ballot-question sources

Michigan is viable for automated Stage 1 creation of statewide, federal, legislative, and judicial elections and races. It should remain classified as **composite/partial** until county-level coverage and reliable special-election discovery are implemented.
