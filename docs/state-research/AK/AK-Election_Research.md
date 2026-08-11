# Alaska Election System — Research Notes

## Coverage Status

| Stage                       | Official source coverage                   | CivicMirror status                            | Notes                                                                                                                                                                                             |
| --------------------------- | ------------------------------------------ | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stage 1 — Election Creation | ✅ **Verified**                             | ⚠️ Current implementation should be reviewed  | Alaska Division of Elections publishes a detailed HTML election calendar and election-information pages. Google Civic API is not needed as the primary source.                                    |
| Stage 1 — Race Creation     | ✅ **Official sources available**           | ⚠️ Runtime integration remains unverified     | DOE candidate pages, filing status, sample ballots, REAA candidate pages, ballot measures, and judicial-retention sources provide enough official data to create most races before results exist. |
| Stage 2 — Results Ingestion | ✅ **Structured official sources verified** | ⚠️ Alaska-specific adapter needed/recommended | Alaska hosts CSV, XML, text, JSON-in-ZIP CVR, HTML, and PDF result files. No public election-results REST API was verified.                                                                       |
| Certification               | ✅ Available                                | ⚠️ Adapter/model mapping needed               | Result pages expose `Official`/`Certified` status; certification PDFs and State Review Board material are also published for some cycles.                                                         |
| Ranked-choice rounds        | ✅ Available                                | ⚠️ Separate RCV normalization needed          | Detailed RCV round reports and CVRs are published for applicable general/special elections.                                                                                                       |
| REAA / recalls / runoffs    | ✅ Available                                | ⚠️ Needs election-type normalization          | DOE directly administers REAA elections and publishes REAA recalls and runoffs in the state results portal.                                                                                       |
| Ballot measures             | ✅ Available                                | ⚠️ Needs source adapter                       | Petition IDs, status, ballot language, pamphlets, audio, and sample-ballot placement are official state sources.                                                                                  |
| Campaign finance            | ✅ Available                                | ⚠️ HTML/database extraction needed            | APOC has a public state database portal; no public API verified.                                                                                                                                  |
| District / precinct GIS     | ✅ **Official GIS API verified**            | ⚠️ Integration not reviewed                   | Alaska DCCED exposes ArcGIS REST Feature Layers supporting JSON/GeoJSON/PBF and query operations.                                                                                                 |
| Historical results          | ✅ 1958–present portal coverage             | ⚠️ Format-specific backfill required          | Historical formats vary substantially; older records can be PDF-only while later elections have HTML/TXT/XML/CSV.                                                                                 |

**Primary election source:** [https://www.elections.alaska.gov/](https://www.elections.alaska.gov/)
**Election results:** [https://www.elections.alaska.gov/election-results/](https://www.elections.alaska.gov/election-results/)
**Election calendar:** [https://www.elections.alaska.gov/calendar/](https://www.elections.alaska.gov/calendar/)
**Operated by:** State of Alaska, Division of Elections
**Researched:** March 4, 2026
**Updated:** August 10, 2026 — verified Alaska-hosted structured result exports and state ENR pages, expanded official candidate/REAA/ballot-measure/judicial/campaign-finance/GIS sources, and corrected the unverified Clarity assumption raised by CivicMirror issue #178.
**Status:** Public; the principal election-information and results sources require no authentication.

---

## Overview

Alaska has a substantially stronger first-party election-data pipeline than the original March 2026 note suggested. The Division of Elections maintains the election calendar, candidate filings, sample ballots, ballot-measure records, REAA election information, election-night reporting, certified results, RCV reports, CVRs, and historical results. Separate state entities provide campaign-finance data and machine-readable election geography. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/)][2])

The original note correctly identified Alaska as running its own election-results publication system and correctly identified historical coverage back to 1958, but it understated the structured formats available and unnecessarily depended on Google Civic for Stage 1. Alaska's own election calendar and candidate systems are sufficient first-party sources for election and much race creation. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/)][2])

No public general-purpose REST API for Alaska election results or candidates was verified. That does **not** mean results require PDF scraping: later elections expose structured CSV, XML, text, and JSON-in-ZIP files in addition to PDFs. A separate official ArcGIS REST API is verified for precinct/election geography. 

---

# Corrections and Additions to the March 2026 Research

| Original finding                                                      | August 2026 research                                                                                                                                                                             | Disposition                                                                     |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| Stage 1 Election Creation: Google Civic API                           | DOE publishes a comprehensive election calendar with election dates, deadlines, certification, recounts, and election-contest dates.                                                             | **Replace Google Civic as primary source.**                                     |
| Stage 1 Race Creation: Google Civic / untested                        | DOE candidate search exposes office, district, candidate, registered affiliation, certification status and incumbent flag before Election Day. Sample ballots confirm actual ballot composition. | **Official Stage 1 sources now identified. Runtime verification still needed.** |
| Stage 2: “No adapter / no Clarity; own system”                        | State-hosted CSV/XML/TXT/JSON/PDF result packages and HTML ENR are verified.                                                                                                                     | **Preserve “own system,” expand structured source findings.**                   |
| Results formats: CSV/PDF/JSON                                         | 2022 also exposes XML and text, including precinct text. 2016/2018 expose HTML/text/precinct text. 2020 exposes XML.                                                                             | **Correct/increase format coverage.**                                           |
| Historical results back to 1958                                       | Verified. The 1958 official returns PDF is still hosted by DOE.                                                                                                                                  | **Confirmed.**                                                                  |
| JSON CVRs valuable for RCV                                            | Correct, but DOE states they represent scanned ballots and do not include hand-count-only ballots; write-in identities may not be resolved.                                                      | **Retain with limitation.**                                                     |
| Supplement with Google Civic, Ballotpedia, OpenStates, OpenFEC, MEDSL | First-party Alaska sources now cover the principal pipeline stages addressed by those recommendations.                                                                                           | **Remove as primary pipeline recommendations.**                                 |
| Investigate Clarity                                                   | Issue #178 assumes a Clarity adapter, but current official evidence does not establish Alaska as a Clarity state.                                                                                | **Do not configure a guessed Clarity URL.**                                     |

The current CivicMirror issue explicitly says AK uses the generic `ClarityAdapter`, requires a manually populated `Election.results_url`, and asks researchers to locate a Clarity election ID for the August 2026 primary. That accurately describes the **repository's present implementation**, not the Alaska government's publication system. ([[GitHub](https://github.com/CivicMirror/CivicMirror-API/issues/178)][1])

---

# Alaska Election Architecture

## Primary Elections

Alaska currently uses a **Nonpartisan Top Four Primary**. There is one primary ballot; candidates need not belong to a political party, and the four highest vote-getters advance regardless of affiliation. The state specifically warns that the affiliation printed beside a candidate reflects voter registration and does not mean nomination or endorsement by that party. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-information/)][3])

For CivicMirror, this means `party_affiliation` should not be normalized as `party_nominee` during the primary.

The current 2026 Primary is August 18, 2026. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-information/)][3])

## General Elections and RCV

Alaska's current general-election process uses ranked-choice voting for applicable candidate contests. Election-night reporting first reports first-choice votes; subsequent tabulation is conducted centrally when required. DOE says subsequent general-election RCV rounds occur after the final ballot count on the fifteenth day after Election Day. ([[Alaska Division of Elections](https://www.elections.alaska.gov/ballot-counting-process/counting-system-and-schedule/)][4])

The official 2024 U.S. Representative RCV report demonstrates a separate round-oriented official report rather than a simple plurality result. 

For CivicMirror, first-choice results and final RCV results should therefore be modeled separately rather than overwriting one another.

## REAA Elections

Regional Educational Attendance Area elections are state-administered by the Alaska Division of Elections and occur annually on the first Tuesday in October. DOE also publishes REAA candidate information, district details, sample ballots, runoff information and results. ([[Alaska Division of Elections](https://www.elections.alaska.gov/reaa/)][5])

REAA results should not be discarded as generic “local” elections: they belong in the state-administered pipeline.

## Special, Recall and Runoff Elections

The DOE results index provides separate official records for Special elections and places REAA-related recalls and runoffs in its REAA results category. Recent examples include the 2022 Special Primary and Special General for U.S. Representative, 2022 and 2023 school-district runoffs, 2023 and 2026 Alaska Gateway recalls, and annual REAA elections. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/)][2])

Normalize the underlying subtype rather than treating every record in the DOE “REAA” result category as an ordinary REAA general election.

## Judicial Retention

Judicial retention contests require special handling. The Alaska Judicial Council publishes the judges standing for retention, their court and judicial district, and its statutory evaluation/recommendation material. The 2026 page includes district, superior, supreme-court and other retention candidates. ([[Alaska Judicial Council](https://www.ajc.state.ak.us/retention/current2026.html)][6])

These should be represented as **retention contests / ballot questions**, not candidate-versus-candidate races. DOE's final ballot and results remain the authoritative source for ballot wording and Yes/No results; the Judicial Council is an authoritative enrichment source for court and judicial-district metadata.

---

# 2026 State-Administered Election Calendar

| Election |             Date | Result-publication note                                                                                  | Certification target |
| -------- | ---------------: | -------------------------------------------------------------------------------------------------------- | -------------------- |
| Primary  |  August 18, 2026 | Zero-results report August 17; refreshed zero report Election Day; first unofficial results after 9 p.m. | August 31            |
| REAA     |  October 6, 2026 | Results after 8 p.m.                                                                                     | October 22           |
| General  | November 3, 2026 | Zero-results report November 2/Election Day; results after 9 p.m.                                        | November 25          |

DOE also records recount and election-contest windows in the same calendar. For the Primary, a recount application is due within five days after certification; an election contest is due within ten days after completion of the State Review. General-election recount and contest deadlines are likewise published. ([[Alaska Division of Elections](https://www.elections.alaska.gov/calendar/)][7])

**Pipeline recommendation:** ingest the calendar itself rather than maintaining hard-coded recurring dates. It provides actual-cycle dates, special-election events, ballot-measure deadlines, candidate deadlines and certification targets.

---

# Ranked Official Source Inventory

## 1. DCCED Election Geography — Official ArcGIS REST GIS Service

**Entity:** Alaska Department of Commerce, Community, and Economic Development (DCCED)
**Source type:** **GIS service / ArcGIS REST API**
**Authentication:** None observed for query access
**Machine readability:** Excellent
**Integration rank:** Highest-format priority, but limited to geography

**Election Precinct Layer:**
[https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/4](https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/4)

**Election Region Layer:**
[https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/3](https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/3)

The precinct service is an official Feature Layer describing Alaska election-precinct boundaries with precinct names, district and election-region identifiers. The service supports queries and machine-readable JSON, GeoJSON and PBF, as well as pagination and advanced query operations. ([[Alaska Commerce Maps](https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/3?utm_source=chatgpt.com)][8])

**CivicMirror use:** districts, precinct geometry, reporting-unit normalization, region mapping.

**Important normalization warning:** precinct and district boundaries change after redistricting. DOE says the current precincts were adopted in April 2024 to conform to the Alaska Redistricting Board's May 15, 2023 Final Proclamation. Do not attach these current polygons automatically to older election returns. ([[Alaska Division of Elections](https://www.elections.alaska.gov/research/district-maps/)][9])

---

## 2. Division of Elections — Election Results

**Entity:** Alaska Division of Elections
**URL:** [https://www.elections.alaska.gov/election-results/](https://www.elections.alaska.gov/election-results/)
**Source types:** **CSV, XML, text, HTML, JSON-in-ZIP bulk download, PDF**
**Authentication:** None
**Machine readability:** High for later cycles; variable historically
**Election scope:** Primary, General, Special, REAA, recalls, runoffs; historical state-administered elections
**Historical coverage:** DOE states 1958 onward. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/)][2])

### 2024 General Election

Official detail page:

[https://www.elections.alaska.gov/election-results/e/?id=24genr](https://www.elections.alaska.gov/election-results/e/?id=24genr)

Verified structured precinct CSV:

[https://www.elections.alaska.gov/results/24GENR/ENRbyPrecinct.csv](https://www.elections.alaska.gov/results/24GENR/ENRbyPrecinct.csv)

Verified CVR ZIP:

[https://www.elections.alaska.gov/results/24GENR/CVR_Export_20241130154411.zip](https://www.elections.alaska.gov/results/24GENR/CVR_Export_20241130154411.zip)

Example official RCV report:

[https://www.elections.alaska.gov/results/24GENR/RCV-USRep.pdf](https://www.elections.alaska.gov/results/24GENR/RCV-USRep.pdf)

The public ENR/map interface also exposes a results-by-precinct CSV download, precinct selection, refresh controls and official-status information. It is hosted under Alaska's own `elections.alaska.gov` domain. ([[Alaska Division of Elections](https://www.elections.alaska.gov/enr/?utm_source=chatgpt.com)][10])

### 2022 General Election

Official detail page:

[https://www.elections.alaska.gov/election-results/e/?id=22genr](https://www.elections.alaska.gov/election-results/e/?id=22genr)

Verified files include:

[https://elections.alaska.gov/results/22GENR/ElectionSummaryReportRPT.xml](https://elections.alaska.gov/results/22GENR/ElectionSummaryReportRPT.xml)

[https://elections.alaska.gov/results/22GENR/ElectionSummaryReportRPT.txt](https://elections.alaska.gov/results/22GENR/ElectionSummaryReportRPT.txt)

[https://elections.alaska.gov/results/22GENR/Results_per_Precinct_2022_11_30T14_17_52_To%20Excel.txt](https://elections.alaska.gov/results/22GENR/Results_per_Precinct_2022_11_30T14_17_52_To%20Excel.txt)

[https://elections.alaska.gov/results/22GENR/rcv/CVR_Export.zip](https://elections.alaska.gov/results/22GENR/rcv/CVR_Export.zip)

The browser research environment cannot render the XML/CSV/ZIP directly because of their content types, but the Alaska-hosted resources resolve as XML, CSV and ZIP rather than HTML pages. 

### 2020 General Election

[https://www.elections.alaska.gov/results/20GENR/](https://www.elections.alaska.gov/results/20GENR/)

The official page provides:

* Summary PDF
* Summary XML
* Results-by-precinct text
* Result map
* Statements of Votes Cast by House District
* Hand-count verification material

([[Alaska Division of Elections](https://www.elections.alaska.gov/results/20GENR/)][11])

### 2018 General Election

[https://www.elections.alaska.gov/results/18GENR/](https://www.elections.alaska.gov/results/18GENR/)

Verified formats:

* HTML
* PDF
* Text
* Text by precinct
* Result map
* Statements of Votes Cast
* Recount records where applicable

([[Alaska Division of Elections](https://www.elections.alaska.gov/results/18GENR/)][12])

### 2016 General Election

[https://www.elections.alaska.gov/results/16GENR/](https://www.elections.alaska.gov/results/16GENR/)

Verified formats include HTML, PDF, text and text by precinct. ([[Alaska Division of Elections](https://www.elections.alaska.gov/results/16GENR/)][13])

### Earliest Verified Historical Result

Official 1958 General Election returns:

[https://www.elections.alaska.gov/Core/Archive/58GENR/1958-genr.pdf](https://www.elections.alaska.gov/Core/Archive/58GENR/1958-genr.pdf)

The scanned report is titled as the official returns of the November 26, 1958 General Election and contains district/precinct-level tabular returns. It is machine-unfriendly compared with modern files and should be treated as a PDF extraction/human-review source. 

### Historical format conclusion

Do **not** use one parser for all Alaska history. The verified examples show:

| Period/example | Verified useful formats                                        |
| -------------- | -------------------------------------------------------------- |
| 2024           | CSV + HTML/map + PDFs + CVR JSON ZIP + RCV reports             |
| 2022           | XML + text + precinct text + PDFs + CVR JSON ZIP + RCV reports |
| 2020           | XML + precinct text + PDF + HTML/map                           |
| 2018           | HTML + text + precinct text + PDF                              |
| 2016           | HTML + text + precinct text + PDF                              |
| Older archive  | Heterogeneous; some records are PDF/scanned-report oriented    |
| 1958           | PDF verified                                                   |

A complete historical backfill should first enumerate each election through the DOE historical-results search and store the files exactly as published before normalization. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/)][2])

---

# CVR and Ranked-Choice Data

Alaska's CVR publication is an especially valuable source, but it is not the complete official result by itself. DOE's published description says the CVR contains ballot information from scanned ballots and does not include ballots from hand-count-only precincts; unresolved write-in identity is another limitation.

That matters because DOE currently states that Alaska has 271 ImageCast scanner precincts and 131 hand-count precincts. ([[Alaska Division of Elections](https://www.elections.alaska.gov/ballot-counting-process/counting-system-and-schedule/)][4])

**Recommended use:**

* Preserve raw CVR separately from certified aggregate results.
* Use it for ballot-ranking transparency and independent RCV analysis.
* Do not derive statewide totals solely from the CVR.
* Store `round_number`, continuing ballots, exhausted ballots and candidate status separately from first-choice results.
* Use official final RCV reports/certification as the final outcome authority.

---

# Current Election-Night Reporting / Clarity Investigation

## Confirmed

Alaska hosts its election-results discovery and ENR interfaces on `elections.alaska.gov`. The 2024 Primary map is:

[https://www.elections.alaska.gov/results/24PRIM/map/](https://www.elections.alaska.gov/results/24PRIM/map/)

The page is titled Alaska 2024 Primary Election Results, displays certified status, exposes summary/precinct downloads and has a “Refresh Results” control. ([[Alaska Division of Elections](https://www.elections.alaska.gov/results/24PRIM/map/?utm_source=chatgpt.com)][14])

The 2024 General ENR interface similarly exposes PDF and CSV download actions and credits its visualization to Chris Benshoof, Wostmann & Associates, Inc. ([[Alaska Division of Elections](https://www.elections.alaska.gov/enr/?utm_source=chatgpt.com)][10])

## Not confirmed

No official Alaska source reviewed in this research identified `enr.clarityelections.com`, Clarity, Scytl or a Clarity election ID as the Alaska results publication system.

Accordingly:

> **Clarity is not verified as an Alaska authoritative source.**

Issue #178 should be treated as describing CivicMirror's current adapter configuration rather than proving Alaska's upstream vendor. ([[GitHub](https://github.com/CivicMirror/CivicMirror-API/issues/178)][1])

## 2026 Primary

As of August 10, the exact 2026 Primary ENR/result-package URL cannot be verified from an official published result page because the election is August 18. DOE's calendar says it will post a zero-results report August 17, replace it with an Election Day zero report August 18, and post first unofficial results after 9 p.m. ([[Alaska Division of Elections](https://www.elections.alaska.gov/calendar/)][7])

Do **not** manufacture a path such as `26PRIM` merely because older state directories use similar naming. It is a reasonable discovery hint, not a confirmed URL.

## Network/HAR record

A HAR capture is **not available in this research environment**. Therefore no hidden AJAX/XHR endpoint is claimed.

Observable information from the state-hosted ENR pages:

* State-hosted HTML interface.
* Precinct-selection control.
* Refresh-results control.
* Direct PDF summary download.
* Direct CSV results-by-precinct download.
* Wostmann & Associates visualization credit on the 2024 interface. ([[Alaska Division of Elections](https://www.elections.alaska.gov/enr/?utm_source=chatgpt.com)][10])

If CivicMirror eventually requires sub-file election-night polling rather than polling the published CSV, a browser HAR from the live state ENR page should be preserved. Until that exists, the structured official downloads are the reproducible source.

---

# Candidate Filing and Race Creation

**URL:**
[https://www.elections.alaska.gov/election-candidates/](https://www.elections.alaska.gov/election-candidates/)

Current 2026 Primary query:

[https://www.elections.alaska.gov/election-candidates/?election=26prim](https://www.elections.alaska.gov/election-candidates/?election=26prim)

**Source type:** HTML page / HTML scraping
**Authentication:** None
**Update behavior:** DOE says records update as filings are received and processed.

The current page allows filtering by election, contest and district. For the 2026 Primary, it publishes the election date, filing and withdrawal deadlines, a last-updated timestamp, and rows containing office/contest, district, candidate name, registered affiliation, certification status and incumbent flag. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-candidates/?election=26prim)][15])

Example source row structure is effectively:

`office | district | candidate | registered affiliation | filing status | incumbent | ...`

The page also publishes addresses, phone numbers, email and OEP links. CivicMirror should normally ingest only the election-relevant fields unless contact information has a defined product use.

### Recommended race-creation fields

* Election
* Office
* District
* Candidate ballot/display name
* Registered political affiliation
* Filing/certification status
* Incumbent indicator
* Candidate/OEP source URL
* Source last-updated timestamp

### Suggested candidate join key

No stable statewide candidate identifier was observed in the public candidate listing.

Use a provisional natural key such as:

`AK + election_external_key + normalized_office + district + normalized_ballot_name`

Preserve the original displayed name separately and do not rely on normalized name alone.

### Important affiliation normalization

The 2026 official sample ballot states that a candidate's designated affiliation does **not** mean the candidate was nominated or endorsed by the party. 

Store something like:

`affiliation_type = voter_registration`

rather than:

`nominee_party = ...`

for Top Four Primary candidates.

---

# Sample Ballots

**Index:**
[https://www.elections.alaska.gov/sample-ballots/](https://www.elections.alaska.gov/sample-ballots/)

**Source type:** PDF collection
**Machine readability:** Medium; text is generally extractable, but layout and ballot style matter
**Pipeline role:** Final ballot qualification, office/contest confirmation, ballot ordering, ballot measures

Verified 2026 example:

[https://www.elections.alaska.gov/election/2026/Primary/SampleBallots/HD1.pdf](https://www.elections.alaska.gov/election/2026/Primary/SampleBallots/HD1.pdf)

The House District 1 sample ballot confirms the August 18, 2026 election date, statewide federal contests, Governor/Lieutenant Governor, Senate District A, House District 1 and Ballot Measure No. 1. 

Sample ballots should be used as a **ballot-finalization cross-check**, not as the primary candidate database, because extracting many ballot styles is more expensive than scraping the candidate listing.

---

# Ballot Measures and Initiative Pipeline

**URL:**
[https://www.elections.alaska.gov/petitions-and-ballot-measures/](https://www.elections.alaska.gov/petitions-and-ballot-measures/)

**Source types:** HTML database-like pages, PDF, audio
**Authentication:** None
**Machine readability:** High for petition metadata; medium/low for official-language PDFs

The active-petition page currently includes stable petition identifiers such as:

* `25USCV`
* `25ANMA`
* `24ESEG`
* `23RCF2`

and status labels including “Petition properly filed” and “Petition booklets circulating.” ([[Alaska Division of Elections](https://www.elections.alaska.gov/petitions-and-ballot-measures/)][16])

These petition IDs are valuable permanent identifiers. The ballot number, such as “Ballot Measure No. 1,” should be stored separately because it is specific to the ballot/election.

### 2026 Primary example

The official House District 1 sample ballot confirms:

**Ballot Measure No. 1 — 23RCF2 — An Act Limiting Contributions to Campaigns.** 

Recommended measure key:

`AK + petition_id`

with election-specific linkage containing:

* Election ID
* Ballot measure number
* Official ballot title/question
* Yes/No choices
* Placement/status
* Sample ballot URL
* Official pamphlet URL

Do not infer future ballot placement solely from “petition properly filed.” Confirm it from final ballot/sample-ballot/OEP material.

---

# REAA Pipeline

**Main page:**
[https://www.elections.alaska.gov/reaa/](https://www.elections.alaska.gov/reaa/)

The Division explicitly states that REAA elections are administered by DOE and occur annually on the first Tuesday in October. The REAA site links candidate filing, candidate lists, sample ballots, runoff guidance, past runoffs, election results and district-level information. ([[Alaska Division of Elections](https://www.elections.alaska.gov/reaa/)][5])

The general results portal confirms that the state-administered REAA family includes ordinary REAA elections as well as recalls and runoffs. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/)][2])

### 2026 Alaska Gateway Recall

Official detail page:

[https://www.elections.alaska.gov/election-results/e/?id=26reaa-16rc](https://www.elections.alaska.gov/election-results/e/?id=26reaa-16rc)

The June 30, 2026 recall is marked `Official` and currently exposes a summary PDF and Statements of Votes Cast rather than the richer CSV/XML package found in recent statewide elections. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/e/?id=26reaa-16rc)][17])

This is evidence that the Alaska adapter must retain a **PDF fallback** for smaller/off-cycle elections.

Suggested REAA keys:

`election_date + REAA_district + seat`

For recall elections also preserve the state's own external code when exposed, such as `26REAA-16RC`.

---

# Certification, Recounts and Election Contests

Do not infer certification from `100% reporting`.

DOE distinguishes election-night results from official certified results on its main results page, and individual detail pages can display `Official` or `Certified` status. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/)][2])

The election calendar provides expected State Review Board/certification dates as well as recount and court-contest windows. ([[Alaska Division of Elections](https://www.elections.alaska.gov/calendar/)][7])

Recommended fields:

* `results_status`
* `certification_date`
* `certification_source_url`
* `recount_status`
* `recount_source_url`
* `contest_status`
* `last_source_update`

Treat certification PDFs and recount reports as provenance documents even when the numeric results have already been ingested from a structured file.

---

# Campaign Finance — Alaska Public Offices Commission

**Entity:** Alaska Public Offices Commission, Department of Administration
**Portal:** [https://aws.state.ak.us/ApocReports/Home.aspx](https://aws.state.ak.us/ApocReports/Home.aspx)
**Campaign index:** [https://aws.state.ak.us/ApocReports/Campaign/](https://aws.state.ak.us/ApocReports/Campaign/)
**Disclosure search:** [https://aws.state.ak.us/ApocReports/CampaignDisclosure/CDForms.aspx](https://aws.state.ak.us/ApocReports/CampaignDisclosure/CDForms.aspx)
**Source type:** Database portal / dynamic HTML
**Authentication for reading:** None observed
**Public REST API:** **Not verified**

APOC's public portal includes candidate registrations, letters of intent, state candidate lists, group/entity registrations, campaign disclosure reports, income, expenditures, transactions, debt, independent expenditures, statements of contribution and other filings. ([[AWS Alaska](https://aws.state.ak.us/apocreports/)][18])

The Campaign Disclosure interface exposes fields including filer, report year, report type, filer type, name, dates, income, expenses, debt, election name, submission date and status. It requires the user to run a search before rows are loaded. ([[AWS Alaska](https://aws.state.ak.us/ApocReports/CampaignDisclosure/CDForms.aspx)][19])

APOC states that reports prior to 2010 should be obtained from APOC staff; the online portal also contains categories for paper-filed candidate/group material. ([[AWS Alaska](https://aws.state.ak.us/apocreports/)][18])

### Extraction recommendation

Classify this as **database portal / HTML scraping**, not an API.

No HAR capture is available from this research environment, so no hidden service endpoint, request payload or pagination contract is asserted.

### Candidate joins

Do not assume DOE candidate names perfectly match APOC filer names. Store any APOC filer identifier discovered on the detail page and maintain an explicit crosswalk. Where no identifier is exposed, match using:

`candidate name + election/year + office`

and flag ambiguous matches for review.

---

# Judicial Retention Source

**Entity:** Alaska Judicial Council
**2026 URL:**
[https://www.ajc.state.ak.us/retention/current2026.html](https://www.ajc.state.ak.us/retention/current2026.html)

**Source type:** HTML page
**Authentication:** None
**Machine readability:** Good

The page identifies each 2026 retention judge's court, judicial district and Judicial Council recommendation. ([[Alaska Judicial Council](https://www.ajc.state.ak.us/retention/current2026.html)][6])

Recommended use:

* Enrich DOE retention contests with court/judicial-district metadata.
* Preserve the Council recommendation as separate metadata.
* Do not treat the recommendation as an election result.
* Use DOE's official ballot/results for Yes/No choices and certified outcome.

Suggested key:

`election_date + court + judicial_district + judge_name`

---

# District and Precinct Sources

## DOE District Maps

[https://www.elections.alaska.gov/research/district-maps/](https://www.elections.alaska.gov/research/district-maps/)

DOE states that current voting precincts were adopted in April 2024 and conform to the Redistricting Board's May 15, 2023 Final Proclamation. The DOE map page itself primarily exposes PDF maps. ([[Alaska Division of Elections](https://www.elections.alaska.gov/research/district-maps/)][9])

## DCCED Machine-Readable Precinct Layer

[https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/4](https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/4)

This should be preferred for machine ingestion because it is a verified Feature Layer with query operations and machine-readable geometry. ([[Alaska Commerce Maps](https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/4?utm_source=chatgpt.com)][20])

## REAA GIS

[https://maps.commerce.alaska.gov/server/rest/services/Education_Related/REAA/MapServer](https://maps.commerce.alaska.gov/server/rest/services/Education_Related/REAA/MapServer)

DCCED documents this official service as representing REAA geography and notes that REAA elections are administered by the Division of Elections. ([[Alaska Commerce Maps](https://maps.commerce.alaska.gov/server/rest/services/Education_Related/REAA/MapServer?utm_source=chatgpt.com)][21])

---

# Election Law

**Official statute portal:**
[https://www.akleg.gov/basis/statutes.asp](https://www.akleg.gov/basis/statutes.asp)

The Alaska Legislature publishes Title 15, Elections, through its official statute database. ([[Alaska Legislature](https://www.akleg.gov/basis/statutes.asp?utm_source=chatgpt.com)][22])

Use statute references to define rules and deadlines, but use DOE's calendar for actual-cycle operational dates because DOE maps those statutes to concrete dates and includes administrative milestones.

---

# CivicMirror Pipeline Map

| Pipeline stage           | Preferred official source                                   | Extraction                      | Suggested identifiers / join keys                        | Update strategy                                    | Important normalization / gap                                          |
| ------------------------ | ----------------------------------------------------------- | ------------------------------- | -------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------- |
| Election calendar        | DOE Election Calendar                                       | HTML table                      | `AK + election_date + normalized_type`                   | Refresh routinely in active year; snapshot changes | Includes administrative events as well as elections; filter carefully. |
| Election definition/type | DOE Election Information + Calendar + Results index         | HTML                            | State election code where available; otherwise date/type | Low frequency                                      | Distinguish Primary, General, Special, REAA, Recall, Runoff.           |
| Offices                  | Candidate page + sample ballots                             | HTML; PDF validation            | normalized office + district                             | During filing/ballot period                        | Governor/LG is a joint ticket.                                         |
| Districts                | DCCED ArcGIS + DOE maps                                     | GIS REST API                    | House/Senate/region/precinct IDs                         | After boundary changes                             | Version geography by effective election cycle.                         |
| Contests/races           | Candidate listing before election; result exports afterward | HTML + structured result files  | election + office + district                             | Candidate period and election night                | Retention and measures are not ordinary candidate races.               |
| Candidates               | DOE Candidate Search                                        | HTML scraping                   | election + office/district + ballot name                 | Poll during filing/withdrawal period               | No stable public candidate ID verified.                                |
| Filing status            | DOE Candidate Search                                        | HTML scraping                   | same candidate key                                       | Poll until ballot finalization                     | Preserve state's `Certified` terminology.                              |
| Incumbent                | DOE Candidate Search                                        | HTML                            | same candidate key                                       | Filing period                                      | Explicit field exists.                                                 |
| Party affiliation        | DOE Candidate Search/sample ballot                          | HTML/PDF                        | same candidate key                                       | Filing period                                      | Store as registered affiliation, not nomination.                       |
| Ballot qualification     | Candidate `Certified` status + sample ballot                | HTML + PDF                      | candidate/race key                                       | After withdrawal/ballot certification              | Sample ballot is final cross-check.                                    |
| Ballot measures          | Petition page + sample ballot/OEP                           | HTML + PDF                      | petition ID, e.g. `23RCF2`                               | Petition events and ballot finalization            | Preserve petition ID separately from ballot number.                    |
| Judicial retention       | Judicial Council + DOE ballot/results                       | HTML                            | election + court + district + judge                      | General-election cycle                             | Yes/No retention contest, not candidate race.                          |
| Results                  | DOE structured result package                               | CSV/XML/TXT; HTML; PDF fallback | election + contest + choice + reporting unit             | Election night through certification               | Format varies by cycle/election type.                                  |
| Precinct results         | DOE CSV/TXT + GIS                                           | CSV/TXT + ArcGIS                | precinct code/name + geography vintage                   | Results updates                                    | Historical precinct names may not match current GIS.                   |
| RCV first choice         | DOE summary/precinct file                                   | CSV/XML/TXT                     | contest + candidate + reporting unit                     | Election night/counting period                     | Keep separate from later rounds.                                       |
| RCV final rounds         | DOE RCV reports                                             | PDF/TXT where available         | contest + round + candidate                              | After final count                                  | Round normalization required.                                          |
| CVR                      | DOE ZIP/JSON                                                | Bulk download                   | ballot/CVR identifiers as published                      | When DOE releases updated package                  | Scanned ballots only; not statewide totals source.                     |
| Certification            | DOE result status + certificate                             | HTML/PDF                        | election                                                 | At State Review/certification                      | Do not equate 100% reporting with certified.                           |
| Recounts                 | Result detail pages + calendar                              | HTML/PDF                        | election + contest                                       | Event-driven                                       | Preserve original and recount result provenance.                       |
| Runoffs                  | Results index + REAA                                        | HTML/PDF/other published files  | election date + district/seat                            | Event-driven                                       | Normalize separately from annual REAA.                                 |
| Recalls                  | Results index + calendar                                    | HTML/PDF                        | state election code, district                            | Event-driven                                       | Recall question may not resemble standard candidate contest.           |
| Campaign finance         | APOC Online Reports                                         | Database portal / HTML scraping | APOC filer ID if available; candidate crosswalk          | Depends on reporting periods                       | Public API not verified.                                               |
| Historical archive       | DOE Historical Results                                      | HTML discovery + mixed files    | DOE election path/code                                   | One-time backfill plus audit                       | Parser must be format-aware by cycle.                                  |

---

# Suggested Core Identifiers

## Election

Prefer a state-published election identifier when one is exposed in the DOE URL, for example:

* `24genr`
* `24prim`
* `26reaa-16rc`

Store it as a source identifier, not as a globally meaningful semantic code.

Fallback:

`AK:{YYYY-MM-DD}:{normalized_election_type}`

## Contest

Suggested natural key:

`election_source_id + office_or_measure + district_or_scope`

Do not use display name alone.

## Candidate / Choice

Suggested provisional key:

`contest_key + normalized_ballot_name`

Preserve:

* Exact ballot name
* Registration affiliation
* Write-in flag when available
* Filing status
* Incumbent flag

## Ballot Measure

Use the petition ID as the durable source key where available:

`AK:23RCF2`

Then attach election-specific ballot number separately.

## Precinct

Prefer explicit precinct identifiers from the result export/GIS when available. Where only names exist, preserve the raw name and create a versioned crosswalk tied to the applicable district plan.

---

# Update Strategy

### Pre-election

Use the election calendar to create upcoming elections. Once candidate filing begins, ingest the DOE candidate listing and update it through filing, withdrawal and ballot-certification milestones. Use sample ballots for a final race/choice validation.

### Election night

Discover the result URL through the official DOE site rather than guessing a vendor or directory. Snapshot each structured file and its retrieval time. Poll only as frequently as operationally necessary; DOE does not publish an API polling contract.

### Post-election

Continue snapshots while absentee/questioned ballots and, for general elections, RCV rounds are processed. DOE says absentee/questioned counts may continue for days after Election Day and general-election subsequent RCV rounds follow the final count. ([[Alaska Division of Elections](https://www.elections.alaska.gov/ballot-counting-process/counting-system-and-schedule/)][4])

### Certification

Capture the official status and certificate/recount material separately. Mark certified only from explicit official evidence.

### Historical backfill

Enumerate each election from the official historical-results interface, preserve the original files, then choose the best parser in this order:

1. Structured API/service where applicable.
2. CSV/XML.
3. Plain/precinct text.
4. Stable HTML.
5. PDF text extraction.
6. Scanned-PDF/manual review.

---

# Issue #178 — Recommended Resolution

Issue #178 currently treats the missing `results_url` as missing per-election Clarity configuration and proposes finding an Alaska Clarity election ID. ([[GitHub](https://github.com/CivicMirror/CivicMirror-API/issues/178)][1])

The state-source research changes that diagnosis.

### Finding 1 — Do not populate a guessed Clarity URL

There is no official evidence from the Alaska sources reviewed that the DOE's current results publication is Clarity.

### Finding 2 — The Alaska adapter should target Alaska DOE outputs

Recent DOE elections already provide state-hosted structured files. The most reproducible Stage 2 path is therefore an **Alaska-specific DOE result adapter**, with format-specific handling for CSV/XML/text and PDF fallback.

### Finding 3 — 2024/2022 can be used immediately for adapter verification

There is no need to wait for the August 18 election to determine whether Alaska results can bootstrap races and candidates. The 2024 General/Primary and 2022 General provide completed official fixtures now. ([[Alaska Division of Elections](https://www.elections.alaska.gov/results/24PRIM/map/?utm_source=chatgpt.com)][14])

### Finding 4 — Race creation need not depend on results

Alaska's candidate listing already exposes certified candidates, office, district, affiliation and incumbent status before Election Day. Race creation can therefore be sourced directly from DOE rather than waiting for an election-night result adapter. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-candidates/?election=26prim)][15])

This separates two concerns:

* **Stage 1:** calendar/candidate/sample-ballot ingestion.
* **Stage 2:** result ingestion.

That is a more reliable fit for Alaska than using a results vendor as the source for both.

### Finding 5 — 2026 live verification remains pending by calendar, not by research failure

The precise 2026 result URL is a legitimate unresolved item on August 10 because DOE says its first zero-results publication begins August 17. ([[Alaska Division of Elections](https://www.elections.alaska.gov/calendar/)][7])

Recommended issue language:

> Alaska's official Division of Elections sources do not currently verify a Clarity ENR endpoint. DOE publishes state-hosted ENR pages and structured election files, including CSV/XML/text and RCV/CVR material. Replace or bypass the AK `ClarityAdapter` with an Alaska DOE adapter. Use 2024/2022 results for immediate adapter/race-bootstrap testing. Discover and record the 2026 Primary URL only from the DOE's official link when the zero-results report is published August 17–18; do not guess a Clarity election ID.

---

# Known Gaps / Human Review

1. **2026 Primary live result URL:** not yet officially published as of August 10. DOE's calendar establishes when it should appear. ([[Alaska Division of Elections](https://www.elections.alaska.gov/calendar/)][7])
2. **Hidden ENR network endpoint:** no HAR is available, so no undocumented endpoint is asserted.
3. **Result REST API:** none verified.
4. **Candidate REST API:** none verified.
5. **APOC API:** none verified; extraction currently classifies as a dynamic HTML/database portal.
6. **Historical file inventory:** the official portal reaches 1958, but each cycle's available individual files still needs systematic enumeration for a complete backfill.
7. **Older scanned PDFs:** require extraction and human QA; the 1958 archive demonstrates the difficulty. 
8. **Small/off-cycle election formats:** structured files are not guaranteed. The 2026 Alaska Gateway Recall currently exposes PDF-oriented results. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-results/e/?id=26reaa-16rc)][17])
9. **Historical geography:** current precinct polygons must not be projected backward without a versioned crosswalk.
10. **CVR completeness:** CVR should not substitute for official totals because hand-count-only ballots are outside scanner CVRs. ([[Alaska Division of Elections](https://www.elections.alaska.gov/ballot-counting-process/counting-system-and-schedule/)][4])
11. **General-election 2026 candidates:** the August 18 primary has not yet determined the complete advancing field; use current primary filings as current data and refresh after certification/withdrawal milestones.
12. **Municipal elections:** DOE provides information links for city/borough elections, but CivicMirror should not infer that Alaska DOE centrally administers every municipal election. REAA elections are explicitly state-administered and are the confirmed state-level exception. ([[Alaska Division of Elections](https://www.elections.alaska.gov/election-information/)][3])

---

# Source Coverage Analysis

Alaska should no longer be characterized as a weak “results only” state. The state has first-party coverage for election scheduling, election type, candidate filings, candidate status, incumbency, ballot qualification, measures, REAA contests, judicial retention, precinct geography, election-night results, certified results, recount documentation, RCV rounds, CVRs, campaign finance and historical results.

The largest integration challenge is **format variation rather than data absence**. There is no verified general election-results API, but modern Alaska results are often available in strong machine-readable downloads, while smaller off-cycle and older elections can fall back to PDF.

For CivicMirror, the recommended Alaska architecture is:

**DOE Calendar → DOE Candidates → Sample Ballot validation → DOE structured Result Package → Certification/RCV/Recount documents**, with **DCCED GIS**, **APOC**, **DOE Ballot Measures/REAA**, and the **Alaska Judicial Council** supplying specialized stages.

The most immediate repository correction is to stop treating an unverified Clarity URL as the blocker for Alaska. The official Alaska source evidence supports an Alaska-native ingestion path, and historic 2022/2024 elections provide usable fixtures for testing that path now. ([[GitHub](https://github.com/CivicMirror/CivicMirror-API/issues/178)][1])

---

**Access date for web verification:** August 10, 2026.

I cannot directly commit this replacement into the GitHub repository with the available tools, but the content above is structured as the consolidated `docs/state-research/AK/AK-Election_Research.md` replacement and preserves the original March 4 research date while adding the required August 10 update line.

[1]: https://github.com/CivicMirror/CivicMirror-API/issues/178 "AK & WY: results_url not set — Race Creation still unverified · Issue #178 · CivicMirror/CivicMirror-API · GitHub"
[2]: https://www.elections.alaska.gov/election-results/ "Election Results - Division of Elections"
[3]: https://www.elections.alaska.gov/election-information/ "Election Information - Division of Elections"
[4]: https://www.elections.alaska.gov/ballot-counting-process/counting-system-and-schedule/ "Alaska’s Ballot Counting System - Division of Elections"
[5]: https://www.elections.alaska.gov/reaa/ "REAA - Division of Elections"
[6]: https://www.ajc.state.ak.us/retention/current2026.html "2026 Alaska Judges Standing for Retention | Alaska Judicial Council"
[7]: https://www.elections.alaska.gov/calendar/ "Election Calendar - Division of Elections"
[8]: https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/3?utm_source=chatgpt.com "Layer: Alaska Election Regions (ID: 3)"
[9]: https://www.elections.alaska.gov/research/district-maps/ "District Maps - Division of Elections"
[10]: https://www.elections.alaska.gov/enr/?utm_source=chatgpt.com "Election Results Map"
[11]: https://www.elections.alaska.gov/results/20GENR/ "Alaska Division of Elections- 2020 Official Results"
[12]: https://www.elections.alaska.gov/results/18GENR/ "Alaska Division of Elections"
[13]: https://www.elections.alaska.gov/results/16GENR/ "Alaska Division of Elections"
[14]: https://www.elections.alaska.gov/results/24PRIM/map/?utm_source=chatgpt.com "Election Results Map"
[15]: https://www.elections.alaska.gov/election-candidates/?election=26prim "Election Candidates - Division of Elections"
[16]: https://www.elections.alaska.gov/petitions-and-ballot-measures/ "Petitions and Ballot Measures - Division of Elections"
[17]: https://www.elections.alaska.gov/election-results/e/?id=26reaa-16rc "Election - Division of Elections"
[18]: https://aws.state.ak.us/apocreports/ "APOC Reports Home Page"
[19]: https://aws.state.ak.us/ApocReports/CampaignDisclosure/CDForms.aspx "Campaign Disclosure: Forms"
[20]: https://maps.commerce.alaska.gov/server/rest/services/Govt_Related/Govt_House_and_Senate_Districts/MapServer/4?utm_source=chatgpt.com "Layer: Alaska Election Precincts (ID: 4)"
[21]: https://maps.commerce.alaska.gov/server/rest/services/Education_Related/REAA/MapServer?utm_source=chatgpt.com "Education_Related/REAA (MapServer)"
[22]: https://www.akleg.gov/basis/statutes.asp?utm_source=chatgpt.com "Alaska Statutes 2025"
