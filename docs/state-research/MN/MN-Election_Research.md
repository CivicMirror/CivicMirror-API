# Minnesota Election Results — Research Notes

## Coverage Status

| Stage                           |                           Source Availability |              Adapter Status | Notes                                                                                                                                                                                     |
| ------------------------------- | --------------------------------------------: | --------------------------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stage 1 — Election Creation     | ⚠️ Available across multiple official sources |      ❌ No Minnesota adapter | Use the SOS election calendar, special-election resources, Candidate Finder, and election-results index. No single public election-manifest API was identified.                           |
| Stage 1 — Race Creation         |                                   ✅ Available |      ❌ No Minnesota adapter | Official candidate filing files and election-specific supporting tables identify offices, districts, candidates, parties, and ballot questions.                                           |
| Stage 1 — Candidate Information |                                   ✅ Available |      ❌ No Minnesota adapter | Official identity, office, party, jurisdiction, address, phone, website, and email data are available. Biographies and policy positions require enrichment.                               |
| Stage 2 — Unofficial Results    |                                   ✅ Available |      ❌ No Minnesota adapter | Application-ready, semicolon-delimited text files are updated every 15 minutes or less on election night.                                                                                 |
| Stage 2 — Official Results      |    ⚠️ Available through certification records |  ❌ No certification adapter | State Canvassing Board reports certify applicable state and federal results. County and local contests may require certification records from the responsible local canvassing authority. |
| Geographic Mapping              |                                   ✅ Available |      ❌ No Minnesota adapter | Precinct spreadsheets, shapefiles, and GeoJSON are available but should be treated as geographic enrichment, not as the results source.                                                   |
| Ranked-Choice Results           |                                    ⚠️ Partial | ❌ No municipal RCV adapters | The statewide portal may show initial rankings, but final round-by-round results for ranked-choice municipal elections come from the applicable city or county.                           |

---

**Primary agency:** Minnesota Secretary of State
**Main elections site:** https://www.sos.mn.gov/elections-voting/
**Election administration and data:** https://www.sos.mn.gov/election-administration-campaigns/
**Candidate filings:** https://candidates.sos.mn.gov/
**Election results portal:** https://electionresults.sos.mn.gov/
**Originally researched:** March 4, 2026
**Updated and verified:** July 12, 2026
**Access:** Public; no authentication required for the verified sources

---

## Overview

Minnesota is a strong candidate for direct integration into CivicMirror.

Although the state does not expose a conventional public REST API, the Minnesota Secretary of State provides structured official sources for:

* Election dates and election types
* Candidate filings
* Office and race definitions
* Candidate party and contact information
* Ballot-question text
* Election-night vote totals
* Precinct reporting statistics
* Supporting party and geographic lookup tables
* Official canvassing and certification records
* Precinct and district GIS data

The primary results source is not a standard CSV API. Minnesota publishes flat ASCII text files separated by semicolons. These files are explicitly intended for downloading into applications.

Official Minnesota sources should be treated as canonical. Google Civic, Ballotpedia, OpenStates, and OpenFEC should be used only for validation or enrichment.

---

# Stage 1 — Election Creation

## Status

**⚠️ Official sources are available, but election discovery is distributed across several systems.**

No single public REST endpoint or downloadable election manifest was identified that lists every upcoming statewide, county, municipal, school, hospital-district, and special election.

## Official Sources

### Elections Calendar

https://www.sos.mn.gov/election-administration-campaigns/elections-calendar/

The calendar identifies Minnesota’s normal election schedule, including:

* Presidential nomination primaries
* State primaries
* State general elections
* March township elections
* Future election dates
* Major categories of offices expected on the ballot

For 2026, the calendar lists:

* August 11, 2026 — Primary Election
* November 3, 2026 — General Election

### Special Elections

https://www.sos.mn.gov/election-administration-campaigns/elections-calendar/special-elections/

Special elections may occur during the year and may be held with regular elections.

Minnesota notes that many special elections held on regular primary or general-election dates will not be listed individually on the special-election page. The state directs users to:

* What’s on My Ballot
* Candidate Finder
* The official ballot-question list

Most Minnesota special elections are held on one of five uniform election dates:

* Second Tuesday in February
* Second Tuesday in April
* Second Tuesday in May
* Second Tuesday in August
* First Tuesday after the first Monday in November

### Candidate Finder

https://candidates.sos.mn.gov/

Candidate filings provide an additional election-discovery signal. When Minnesota begins accepting candidate filings for a special or regular election, the relevant offices and candidates appear in this system.

### Election Results Index

https://www.sos.mn.gov/elections-voting/election-results/

The historical results index identifies elections that have been initialized in Minnesota’s results system. Each results instance has an election-specific identifier used by the results portal.

## Recommended Election Discovery Flow

A Minnesota election-discovery adapter should combine:

1. The regular Minnesota elections calendar.
2. The special-election page.
3. Candidate Finder changes.
4. The official ballot-question list.
5. Newly discovered election IDs in the results portal.
6. Optional Google Civic validation.

## Recommended Election Fields

Store at least:

```text
source_state
source_election_id
election_name
election_type
election_date
jurisdiction_type
jurisdiction_name
filing_start
filing_end
results_url
discovery_source
discovered_at
last_verified_at
```

The internal election key should not be derived solely from the election date. Multiple special or local elections may occur on the same date.

## Election Creation Assessment

```text
Source availability: PARTIAL / DISTRIBUTED
Adapter feasibility: GOOD
Main risk: Discovering every local and special election
```

---

# Stage 1 — Race Creation

## Status

**✅ Official race and contest information is available.**

Minnesota provides enough official information to create most races without relying on Google Civic.

## Candidate Filing Sources

https://candidates.sos.mn.gov/

The Candidate Finder supports offices in these categories:

* Federal
* State executive
* State Senate
* State House
* Judicial
* County
* City and township
* School district
* Hospital district

The site also provides downloadable text files for:

* Federal, state, and county candidate filings
* Local candidate filings
* Federal, state, and county candidates appearing in the primary
* Local candidates appearing in the primary

## Election-Specific Supporting Tables

Example:

https://electionresults.sos.mn.gov/Select/MediaFiles/Index?ersElectionId=170

For an initialized election, Minnesota publishes supporting files for:

* Parties
* Counties
* Precincts
* Federal, state, and county candidates
* Municipal, hospital-district, and school-district candidates
* Ballot questions
* School districts
* Municipalities

The election-specific candidate tables provide stable source candidate identifiers:

* Eight-character candidate IDs for federal, state, and county candidates
* Thirteen-character candidate IDs for local candidates

## Ballot Questions

Ballot measures are covered by official Minnesota sources.

The results package may include:

* Constitutional amendments
* County questions
* Municipal questions
* Hospital-district questions
* School referenda
* Bond questions

The ballot-question supporting table can include:

* County
* Office or question identifier
* Municipality
* School district
* Question number
* Question title
* Full question text

Ballotpedia is therefore not required to create an official ballot-question record. It may still provide summaries, arguments, campaign information, and historical context.

## Recommended Race Key

Do not assume an office title alone is unique.

A normalized race key should account for:

```text
source_election_id
office_id
office_title
district
county_id
municipal_fips
school_district_number
jurisdiction_type
```

## Race Creation Assessment

```text
Source availability: AVAILABLE
Adapter feasibility: STRONG
Canonical source: Minnesota candidate and election supporting files
```

---

# Candidate Information

## Status

**✅ Minnesota provides substantial official candidate information.**

The original research understated candidate coverage.

## Official Candidate Fields

Minnesota’s downloadable candidate filing files may include:

* Candidate name
* Office ID
* Office title
* County ID
* Party abbreviation
* Municipal FIPS code, where applicable
* School-district number, where applicable
* Residence address
* Campaign address
* Campaign telephone
* Campaign website
* Campaign email
* Running-mate website, email, and telephone where applicable

Candidate file layout:

https://candidates.sos.mn.gov/Media/MediaFileFormat.txt

Local candidates are represented as nonpartisan.

## Candidate Lifecycle

Minnesota states that:

* Candidate names are added during filing periods.
* Petition candidates may appear after petitions are reviewed.
* Candidates who withdraw are removed from Candidate Finder.
* Candidate information is subject to correction before Election Day.

The adapter must therefore use snapshot and upsert behavior.

When a previously imported candidate disappears:

1. Do not permanently delete the candidate.
2. Mark the filing as inactive, removed, or possibly withdrawn.
3. Record when the record disappeared.
4. Retain the previous source payload.
5. Reconcile the status against later election-specific candidate tables.

## Candidate Enrichment Gaps

Minnesota’s official files do not appear to provide:

* Narrative biography
* Candidate photograph
* Policy platform
* Issue positions
* Endorsements
* Campaign profile or questionnaire responses

Those fields may be enriched from:

* Candidate campaign websites
* Ballotpedia
* OpenStates
* OpenFEC for federal candidates

Enrichment data must not overwrite official Minnesota identity, office, party, or contact records without explicit provenance.

## Candidate Information Assessment

```text
Official identity and contact information: AVAILABLE
Biography and policy enrichment: THIRD-PARTY SOURCE NEEDED
Adapter feasibility: STRONG
```

---

# Stage 2 — Unofficial Results

## Status

**✅ Comprehensive machine-readable unofficial results are available.**

This is the strongest Minnesota integration source.

## Results Portal

https://electionresults.sos.mn.gov/

The portal provides:

* Election-night reporting
* Historical election results
* Contest-level result pages
* Geographic result breakdowns
* Downloadable application files
* Precinct reporting information

## Downloadable Results Files

Example for the November 5, 2024 general election:

https://electionresults.sos.mn.gov/Select/MediaFiles/Index?ersElectionId=170

Minnesota states that these files:

* Contain results in text format for downloading into applications
* Are updated every 15 minutes or less on election night
* Include separate contest and geographic result files
* Include supporting lookup tables

## Result Coverage

Depending on the election, files may cover:

* U.S. President
* U.S. Senate
* U.S. House
* Governor and state executive offices
* State Senate
* State House
* Supreme Court
* Court of Appeals
* District courts
* County races
* County questions
* Municipal races
* Municipal questions
* Hospital-district races
* School-board races
* School referenda and bond questions
* Constitutional amendments
* Precinct reporting statistics

## Data Format

File-layout documentation:

https://electionresults.sos.mn.gov/Results/MediaFileLayout/Index?erselectionId=170

The files are:

* ASCII text
* Semicolon-delimited
* Flat positional records
* Usually one row per candidate or question response in each geographic area
* Not guaranteed to contain header rows

A typical results record includes:

```text
state
county_id
precinct_name
office_id
office_name
district
candidate_order_code
candidate_name
suffix
incumbent_code
party_abbreviation
precincts_reporting
total_precincts
candidate_votes
candidate_percentage
total_office_votes
```

## Parser Requirements

The parser must:

* Split on semicolons, not commas or whitespace.
* Preserve empty positional fields.
* Treat all identifiers as strings unless safely normalized.
* Recognize candidate order code `9901` as a write-in entry.
* Treat local candidates as nonpartisan.
* Handle caret characters used to replace semicolons in some free-text fields.
* Handle files appearing at different times.
* Store the raw downloaded file.
* Compute a content hash to avoid reprocessing unchanged files.
* Preserve every fetch timestamp.
* Allow results to change after initial reporting.

Minnesota warns that:

* Supporting information may change before Election Day.
* Results may change after initially being reported.
* Precinct-level result files may not be available until the morning after Election Day.

## Recommended Polling Strategy

During active election reporting:

```text
Poll interval: approximately 15 minutes
Download only known files for the election
Hash each response
Skip unchanged files
Store raw snapshots
Upsert totals transactionally
Record retrieval time and source URL
```

## Recommended Result Statuses

```text
scheduled
polls_open
live_unofficial
unofficial_partial
unofficial_complete
canvass_pending
certified
recount_pending
certified_amended
```

## Unofficial Results Assessment

```text
Source availability: AVAILABLE
Machine readability: STRONG
Election-night suitability: STRONG
Canonical election-night source: Minnesota downloadable result files
```

---

# Stage 2 — Official Results

## Status

**⚠️ Official certification is available, but it is separate from the election-night result feeds.**

Minnesota labels the election-results portal and downloadable result files as unofficial.

The result files should not automatically be relabeled as official merely because all precincts have reported.

## State Canvassing Board

For applicable state and federal contests, the Minnesota State Canvassing Board certifies the official results.

Example for the November 5, 2024 general election:

https://www.sos.mn.gov/elections-voting/election-results/2024/2024-general-election-results/2024-state-canvassing-board-general/

The State Canvassing Board certified the official 2024 general-election report on November 21, 2024. The certification page links to the official State Canvassing Board report.

## County and Local Certification

County, municipal, school-district, and other local contests may be certified by the responsible county or local canvassing authority.

The Minnesota statewide portal may continue to describe local results as unofficial even after the responsible local board has canvassed them.

Official-result support therefore has two parts:

1. Preserve and display the latest unofficial vote totals.
2. Attach a certification event or certified report from the responsible canvassing authority.

## Recommended Certification Model

```text
certification_id
election_id
race_id
certifying_authority
authority_type
certification_date
certification_status
certification_document_url
source_report_hash
notes
created_at
updated_at
```

Possible authority types:

```text
state_canvassing_board
county_canvassing_board
municipal_canvassing_board
school_district_canvassing_board
other_local_authority
```

## Recommended Result Architecture

```text
result_snapshot
  source: Minnesota election-results files
  status: unofficial
  fetched_at: timestamp
  raw_file_hash: hash

certification
  source: canvassing authority
  status: certified
  certified_at: timestamp
  certification_document: URL or stored document
```

The certified status should be associated with the relevant election or race without destroying the unofficial snapshot history.

## Recounts and Amendments

The model must support:

* Recount pending
* Recount completed
* Amended certification
* Corrected official totals
* Superseded certification reports

## Official Results Assessment

```text
State and federal certification: AVAILABLE
Unified machine-readable certification feed: NOT IDENTIFIED
County and local certification: DISTRIBUTED
Adapter feasibility: MODERATE
Main risk: Determining certification for every local contest
```

---

# GIS and Geographic Data

## Status

**✅ GIS data is available but should not be used as the primary results source.**

Minnesota provides geographic data through:

https://www.sos.mn.gov/election-administration-campaigns/data-maps/

Available products include:

* Precinct spreadsheets
* Shapefiles
* GeoJSON
* KML
* Election-district information
* District maps
* Voter-registration statistics

## Recommended Use

GIS data should support:

* Address-to-precinct lookup
* Address-to-district lookup
* Map rendering
* Geographic validation
* Linking precincts to congressional and legislative districts

It should not be used to create vote totals.

## Historical Versioning Requirement

Precinct names, identifiers, boundaries, and district assignments can change.

Do not overwrite historical precinct geography with the newest GIS release.

Store:

```text
geography_version
effective_date
election_id
county_id
precinct_id
precinct_name
geometry
source_url
source_hash
retrieved_at
```

---

# Ranked-Choice Voting

## Status

**⚠️ The statewide source is not sufficient for final ranked-choice outcomes in every municipality.**

Minnesota municipalities using ranked-choice voting have included:

* Minneapolis
* St. Paul
* Bloomington
* Minnetonka
* St. Louis Park

The statewide results portal may provide election-day candidate rankings or initial totals, but final winners and round-by-round tabulation may be published by the applicable city or county.

## Initial Adapter Recommendation

For the first Minnesota implementation:

1. Import available first-choice or initial totals.
2. Mark the contest as `partial_ranked_choice`.
3. Do not infer or declare a final winner from initial totals.
4. Link to the responsible local results source.
5. Add dedicated municipal RCV adapters in a later phase.

---

# Source Priority

## Canonical Minnesota Sources

1. **Election discovery**

   * Minnesota Elections Calendar
   * Minnesota Special Elections page
   * Candidate Finder
   * Election Results index

2. **Race and candidate creation**

   * Candidate filing text files
   * Election-specific candidate tables
   * Official ballot-question tables

3. **Unofficial results**

   * Election-specific downloadable result files
   * Precinct reporting statistics

4. **Official certification**

   * State Canvassing Board reports
   * County and local canvassing records

5. **Geography**

   * SOS precinct spreadsheets
   * Shapefiles
   * GeoJSON

## Optional Enrichment Sources

### Google Civic Information

Use for:

* Address-based ballot validation
* Polling-place information
* Cross-checking contests for a particular voter address

Do not use as the canonical statewide election, race, candidate, or result source.

### Ballotpedia

Use for:

* Candidate biographies
* Candidate issue positions
* Ballot-measure explanations
* Supporting and opposing campaign information

### OpenStates

Use for:

* Legislative incumbent matching
* Legislative biography enrichment
* Bill and voting-history links

### OpenFEC

Use for:

* Federal candidate identifiers
* Federal committee records
* Campaign-finance enrichment

All third-party data must retain its own source and retrieval metadata.

---

# Recommended Implementation Sequence

## Phase 1 — Historical Proof of Concept

Use the November 5, 2024 general election.

Implement parsers for:

* Parties
* Counties
* Precincts
* Federal, state, and county candidates
* Local candidates
* Ballot questions
* District-level results
* County-level results
* Precinct-level results
* Precinct reporting statistics

Validate imported totals against the public SOS portal.

## Phase 2 — Election and Race Discovery

Implement:

* Election-calendar ingestion
* Candidate filing polling
* Special-election discovery
* Election-results ID discovery
* Ballot-question discovery
* Candidate withdrawal detection

## Phase 3 — Election-Night Ingestion

Implement:

* Approximately 15-minute polling
* File hashing
* Raw snapshot retention
* Transactional result upserts
* Precinct reporting progress
* Unofficial result lifecycle states

## Phase 4 — Official Certification

Implement:

* State Canvassing Board discovery
* Certification-document storage
* Race-level certification status
* Recount and amendment handling
* County and local certification adapters where practical

## Phase 5 — Geographic and Ranked-Choice Support

Implement:

* Election-versioned precinct geography
* Address-to-precinct matching
* Address-to-district matching
* Municipal ranked-choice result adapters

---

# Known Risks and Exceptions

1. There is no single verified election-manifest API.
2. Candidate records can change or disappear after withdrawal.
3. Supporting tables can change before Election Day.
4. Precinct-level files may be delayed until the morning after Election Day.
5. Election-night totals are explicitly unofficial.
6. Local official certification is distributed across multiple authorities.
7. Ranked-choice results may require separate municipal adapters.
8. Precinct and district geography must be versioned historically.
9. Office IDs may require jurisdiction and district context to be globally unique.
10. Local candidates are nonpartisan in the official files.
11. Result files are positional, semicolon-delimited text—not ordinary header-based CSV files.
12. The consolidated Excel precinct product should be treated as supplemental and not assumed to contain every candidate in every race.

---

# Final Assessment

Minnesota is ready for direct adapter development.

The Secretary of State provides strong official coverage for:

* Election scheduling
* Race creation
* Candidate identity and contact information
* Ballot questions
* Unofficial election-night results
* Precinct reporting
* Supporting lookup tables
* GIS boundaries
* State-level official certification

The main implementation challenges are:

* Discovering every local and special election
* Tracking changing candidate filings
* Separating unofficial totals from official certification
* Finding county and local certification records
* Versioning historical precinct geography
* Supporting municipal ranked-choice elections

The recommended architecture is:

```text
Election creation
  SOS calendar
  + special-election resources
  + Candidate Finder
  + election-results index

Race and candidate creation
  Candidate filing files
  + election-specific candidate tables
  + ballot-question tables

Unofficial results
  Semicolon-delimited election result files
  + precinct reporting statistics

Official results
  State Canvassing Board reports
  + county or local canvassing records

Geographic matching
  Election-versioned SOS GIS data
```

**Recommendation:** Proceed with Minnesota as the next state integration. Begin with the complete November 5, 2024 general-election files, then add 2026 election discovery and candidate synchronization before implementing live election-night polling.
