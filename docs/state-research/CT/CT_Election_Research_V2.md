# Connecticut Election Research — CivicMirror

## Coverage Status

| Pipeline Stage                  | Status                                                     | Notes                                                                                                                                                                                                    |
| ------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Election Creation               | ✅ Available                                                | Use Connecticut Secretary of the State election calendars, election notices, sample ballots, and the EMS election catalog. Do not rely on the EMS catalog alone for future/off-cycle election discovery. |
| Race / Contest Creation         | ✅ Available once loaded in EMS; ⚠️ fragmented pre-election | EMS `Lookupdata.json` supplies offices, districts, parties, candidates, and election metadata. Official sample ballots and candidate materials are needed before an election appears in EMS.             |
| Candidate Ingestion             | ✅ Partial                                                  | EMS contains candidate IDs, names, party IDs, and an address field. Filing/qualification status remains distributed across SOTS and local election officials.                                            |
| Results Ingestion               | ⚠️ **Source verified; CivicMirror code blocked**           | Versioned static JSON is fully accessible. Current CT adapter supports only one `ct_election_id`, but Connecticut frequently assigns separate EMS IDs to Democratic and Republican primaries.            |
| Ballot Measures                 | ✅ Available                                                | `ballotQuestion_Electiondata.json` plus the Historical Election Database.                                                                                                                                |
| Certification / Official Status | ✅ Partial                                                  | EMS provides `reports_Electiondata.json` with `IR`/`IO`; final legal certification should also be reconciled with Secretary of the State final/certification records.                                    |
| Historical Results              | ✅ Strong                                                   | Historical Election Database plus Statement of Vote/archive material.                                                                                                                                    |
| Campaign Finance                | ✅ Available separately                                     | State Elections Enforcement Commission eCRIS.                                                                                                                                                            |
| District Geography              | ⚠️ Separate system                                         | State GIS resources exist; exact structured district-layer endpoint still needs to be captured and documented.                                                                                           |

---

**Current Election Night Reporting:** https://ctemspublic.tgstg.net/#/home
**Election Catalog:** https://ctemspublic.tgstg.net/ng-app/data/Elections.json
**Legacy EMS hostname:** https://ctemspublic.pcctg.net
**Historical Election Database:** https://electionhistory.ct.gov/eng
**SOTS Election Results:** https://portal.ct.gov/sots/election-services/election-results/election-results
**Election Calendars:** https://portal.ct.gov/sots/election-services/calendars/election-calendars
**Candidate Ballot Access:** https://portal.ct.gov/sots/election-services/candidate-information/candidate-ballot-access
**Campaign Finance:** https://seec.ct.gov/portal/ecris/ecris-search
**Primary responsible entity:** Connecticut Secretary of the State
**Researched:** May 31, 2026
**Updated:** August 10, 2026 — HAR confirmed the 2026 Democratic/Republican primary IDs, versioned JSON request flow, three-minute UI refresh logic, EMS office/category codes, access behavior, candidate fields, and the CivicMirror multi-ID ingestion blocker
**Status:** Public; no application authentication observed

---

## Overview

Connecticut has a strong first-party election-data environment, but the information is distributed across several official systems.

For current election reporting, the most valuable CivicMirror source is the Secretary of the State's public Election Management System / Election Night Reporting application at `ctemspublic.tgstg.net`. The application does not expose a documented REST API. Instead, its AngularJS frontend loads public, versioned JSON files containing elections, offices, candidates, parties, vote totals, reporting status, turnout, districts, precinct data, and ballot questions.

A browser HAR captured on **August 10, 2026** independently confirms this architecture and provides a reproducible network record.

The primary CivicMirror issue is now clearly an **adapter/data-model problem rather than a source-discovery problem**. Connecticut frequently represents a single real-world primary date as multiple source elections, normally one EMS ID per party. CivicMirror's current Connecticut results adapter supports only one `Election.source_metadata["ct_election_id"]`, so it cannot ingest a complete split-party primary.

For historical data, Connecticut also maintains an official Historical Election Database with much deeper coverage than the live EMS. Use the live EMS for recent/current elections and the historical database plus official archive documents for long-term backfill and certification reconciliation.

---

# Current EMS / Election Night Reporting

## Recommended Integration Priority

**Rank: 1 — primary current-results source**

### Source Classification

| Attribute                     | Value                                                                                                    |
| ----------------------------- | -------------------------------------------------------------------------------------------------------- |
| Responsible entity            | Connecticut Secretary of the State                                                                       |
| Source type                   | Versioned static JSON + HTML/AngularJS public application                                                |
| API classification            | **Not a documented public API**                                                                          |
| Authentication                | None observed                                                                                            |
| Machine readability           | High                                                                                                     |
| Update method                 | Version-based refresh                                                                                    |
| Primary use                   | Current election definitions, contests, candidates, results, turnout, reporting status, ballot questions |
| Historical role               | Recent EMS-era results; do not treat as the sole historical archive                                      |
| CivicMirror integration value | Very high                                                                                                |

The JSON resources return normal `application/json` responses and do not require an API key or application `Authorization` token.

The site does issue `AWSALB` and `AWSALBCORS` cookies. These appear to be infrastructure/load-balancer affinity cookies rather than election-data credentials. CivicMirror should first test direct server-side requests without persisting browser cookies.

Cloudflare and ASP.NET response headers were observed in the HAR.

---

# HAR Capture — August 10, 2026

**Capture:** `ctemspublic.tgstg.net_Archive [26-08-10 12-02-51]`
**Captured:** August 10, 2026, approximately 12:00–12:03 PM Eastern
**Browser:** Firefox 153.0.3
**Target:** `https://ctemspublic.tgstg.net`

The HAR confirms the principal EMS network behavior rather than merely inferring it from page output.

Important HAR-confirmed observations:

* `Elections.json` is the election discovery resource.
* August 11, 2026 Democratic Primary is EMS ID **111**.
* August 11, 2026 Republican Primary is EMS ID **112**.
* September 1, 2026 Democratic Primary is EMS ID **113** and was the `DefaultElection`.
* `Version.json` controls the versioned data directory.
* Election 112 was observed at versions **1147** and **1148** during the capture.
* The frontend explicitly loads all previously identified `*_Electiondata.json` resources.
* The frontend computes its displayed next update as three minutes after the current time.
* Core result resources use ordinary HTTP `GET` requests.
* No application API key or `Authorization` header was observed.
* The site also exposes ASP.NET report-generation requests separate from the core JSON data.

---

# Election Discovery

## Election Catalog

```text
GET https://ctemspublic.tgstg.net/ng-app/data/Elections.json
```

The HAR captured the following leading entries:

```json
[
  {
    "ID": "113",
    "Name": "09/01/2026 -- September 1st Democratic Primary",
    "DefaultElection": "Y"
  },
  {
    "ID": "111",
    "Name": "08/11/2026 -- Democratic Primary",
    "DefaultElection": "N"
  },
  {
    "ID": "112",
    "Name": "08/11/2026 -- Republican Primary",
    "DefaultElection": "N"
  },
  {
    "ID": "110",
    "Name": "06/23/2026 -- Middlebury Special Election Selectman to Fill Vacancy",
    "DefaultElection": "N"
  }
]
```

## Correction to Earlier Research

The May 31 research stated that EMS ID 108 was the November 2026 State Election and was the current default election.

That claim is stale and should be removed.

On August 10, the public catalog identified **ID 113** as the current default election.

`DefaultElection` should therefore be treated only as the election initially selected by the public application. It is **not** a durable CivicMirror identifier and should not be interpreted as:

* the next statewide election;
* the most important election;
* the current general-election cycle;
* the complete state election calendar.

Always match elections using date, official name/type, party where applicable, and the source EMS ID.

---

# Critical CivicMirror Issue — Multi-ID Primaries

## Issue #170

CivicMirror currently stores one Connecticut EMS identifier at:

```text
Election.source_metadata["ct_election_id"]
```

That assumption is incompatible with Connecticut's EMS design.

The August 10 HAR confirms:

| CivicMirror logical election | CT EMS source election |  EMS ID |
| ---------------------------- | ---------------------- | ------: |
| August 11, 2026 Primary      | Democratic Primary     | **111** |
| August 11, 2026 Primary      | Republican Primary     | **112** |

Selecting only `111` retrieves only Democratic primary contests.

Selecting only `112` retrieves only Republican primary contests.

Therefore Stage 2 is **not blocked by unavailable state data**. It is blocked because CivicMirror currently cannot associate multiple CT source-election IDs with one logical election.

## This Is a Recurring Connecticut Pattern

The EMS catalog also contains repeated split-party elections in prior cycles, including:

| Election date/type                            | Democratic ID | Republican ID |
| --------------------------------------------- | ------------: | ------------: |
| August 13, 2024 State Primary                 |            94 |            95 |
| April 2, 2024 Presidential Preference Primary |            92 |            93 |
| September 2023 Primary                        |            84 |            85 |
| August 9, 2022 State Primary                  |            81 |            82 |
| September 14, 2021 Primary                    |            71 |            72 |
| August 11, 2020 State Primary                 |            59 |            58 |
| September 10, 2019 Primary                    |            42 |            43 |

The August 2020 catalog also contains separate Democratic and Republican presidential-preference primary records.

**Conclusion:** multi-ID support must be treated as a permanent Connecticut integration requirement, not as a special fix for election IDs 111/112.

## Recommended Source Metadata Concept

CivicMirror should conceptually allow:

```yaml
ct_election_ids:
  - id: "111"
    party: Democratic
  - id: "112"
    party: Republican
```

Exact application implementation is outside this research document, but researchers should treat these source elections as components of one logical August 11 election.

## Contest Identity

Do not merge contests solely on office name.

A Democratic primary and Republican primary for the same office are different contests.

Suggested normalized contest key components:

```text
logical election
+ office
+ district
+ party
+ contest type
```

---

# Version Lookup and Refresh Strategy

For each EMS election:

```text
GET https://ctemspublic.tgstg.net/ng-app/data/election/{electionID}/Version.json
```

Example captured for election 112:

```json
{"Version":1147}
```

The browser subsequently loaded resources from version `1148`, demonstrating that the version can advance while the application is active.

The versioned base path is:

```text
https://ctemspublic.tgstg.net/ng-app/data/election/{electionID}/{version}/
```

## Refresh Behavior

The captured frontend JavaScript calculates:

```text
current time + 3 * 60000
```

for the public interface's displayed “Next Update” time and uses AngularJS interval/update logic to refresh the election data.

Therefore a **three-minute frontend refresh cycle is supported by the captured application code**.

Treat that as observed implementation behavior, not as a formal state SLA.

## Recommended CivicMirror Polling

Researchers should recommend version-based polling:

1. Fetch `Version.json`.
2. Compare the returned version to the most recently ingested version.
3. If unchanged, do not re-download all result files.
4. If changed, fetch the complete required versioned result set.
5. Store:

   * EMS election ID;
   * EMS version;
   * retrieval timestamp;
   * source URLs;
   * official/unofficial state observed at ingestion.

This gives CivicMirror a clean change-detection and provenance mechanism.

---

# HAR-Confirmed Static JSON Files

The frontend explicitly requests:

| File                                  | Content / CivicMirror value                                                                        |
| ------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `Lookupdata.json`                     | Election metadata, offices, candidates, parties, towns, counties, polling places and reference IDs |
| `stateVotes_Electiondata.json`        | Statewide vote totals keyed by office/candidate                                                    |
| `election_Electiondata.json`          | Election-level turnout/reporting metadata                                                          |
| `voterTurnout_Electiondata.json`      | Turnout by jurisdiction                                                                            |
| `townVotes_Electiondata.json`         | Town-level vote totals                                                                             |
| `townStatus_Electiondata.json`        | Reporting status by town                                                                           |
| `reports_Electiondata.json`           | Result-status flags including `IR` and `IO`                                                        |
| `districts_Electiondata.json`         | District-level election data                                                                       |
| `officePrecincts_Electiondata.json`   | Precinct detail by office                                                                          |
| `ballotQuestion_Electiondata.json`    | Ballot-question text and results                                                                   |
| `candidateGrouping_Electiondata.json` | Candidate grouping information, relevant to multi-seat contests                                    |

The earlier single combined `Electiondata.json` approach remains visible in commented frontend code, but the live application loads the split files listed above.

**Use the split resources, not the commented legacy file.**

---

# `Lookupdata.json`

## General Structure

```json
{
  "election": {
    "ID": "...",
    "NM": "...",
    "DT": "...",
    "ET": "...",
    "EC": "...",
    "P": "...",
    "DNM": "..."
  },
  "townIds": {},
  "counties": {},
  "countyTowns": {},
  "officeList": [],
  "partyIds": {},
  "candidateIds": {},
  "townParties": {},
  "pollingplaceIds": {},
  "townPollingPlaces": {}
}
```

## Election 112 — HAR-Confirmed Metadata

```json
{
  "ID": "112",
  "NM": "08/11/2026 -- Republican Primary",
  "DT": "08/11/2026",
  "ET": "P",
  "EC": "SP",
  "P": "Republican Party",
  "DNM": "2026 Republican Primary"
}
```

This provides a useful election normalization layer.

For election 112:

| Field | Observed meaning                                        |
| ----- | ------------------------------------------------------- |
| `ID`  | EMS source election ID                                  |
| `NM`  | EMS election name                                       |
| `DT`  | Election date                                           |
| `ET`  | Election type code; `P` observed for primary            |
| `EC`  | Election category code; `SP` observed for state primary |
| `P`   | Party                                                   |
| `DNM` | Display name                                            |

## Election Category Code

The HAR confirms:

| `EC` | Meaning       |
| ---- | ------------- |
| `SP` | State primary |

The prior research also mapped additional category codes from earlier records, but those should remain documented as prior observations until individually rechecked if they are used for normalization.

Do not build election-type normalization around `EC` alone. Use:

* date;
* election name;
* `ET`;
* `EC`;
* party;
* official election calendar/context.

---

# Office Metadata

## Corrected Office-Type Mapping

The HAR corrects an important error in the May 31 file.

`PD` is **not Presidential**.

Observed `officeList` entries establish:

| `OT` | HAR-supported meaning  | Examples                                                                           |
| ---- | ---------------------- | ---------------------------------------------------------------------------------- |
| `SW` | Statewide              | Presidential Electors, U.S. Senator, Secretary of the State, Treasurer             |
| `C`  | Congressional          | Representative in Congress 1–5                                                     |
| `S`  | State Senate           | State Senator / State Senate district                                              |
| `A`  | State House / Assembly | State Representative district                                                      |
| `SM` | Municipal/local        | Registrar of Voters, Board of Education, Town Council, Representative Town Meeting |
| `PD` | Probate District       | Judge of Probate                                                                   |

Example:

```json
{
  "ID": "16850",
  "NM": "Judge of Probate 15 To Fill Vacancy",
  "OT": "PD",
  "DT": "Connecticut 15",
  "D": "15"
}
```

This correction should be reflected in any race normalization using `OT`.

## Office Fields

Observed office records use fields including:

| Field | Use                           |
| ----- | ----------------------------- |
| `ID`  | EMS office/contest identifier |
| `NM`  | Office name                   |
| `OT`  | Office type                   |
| `OO`  | Display/order value           |
| `DT`  | District display text         |
| `D`   | District identifier           |

Suggested CivicMirror join:

```text
source election ID
+ office ID
```

Do not assume an office ID is globally immutable across every EMS era until historical stability has been tested.

---

# Candidate Data

`candidateIds` contains more information than the previous gap analysis suggested.

Observed fields include:

```json
{
  "NM": "Candidate Name",
  "LN": "Last",
  "FN": "First",
  "MN": "Middle",
  "P": "6",
  "AD": "candidate address",
  "CO": "0"
}
```

### Candidate fields

| Field | Observed content                                              |
| ----- | ------------------------------------------------------------- |
| `NM`  | Full candidate name                                           |
| `LN`  | Last name                                                     |
| `FN`  | First name                                                    |
| `MN`  | Middle name/initial                                           |
| `P`   | Party ID                                                      |
| `AD`  | Address                                                       |
| `CO`  | Unresolved code; preserve raw value until meaning is verified |

This means the EMS does contain **candidate addresses for at least some records**.

CivicMirror should not describe candidate contact data as wholly absent.

However, no evidence in the HAR shows:

* candidate biography;
* campaign website;
* email;
* phone number;
* incumbent status;
* platform statement;
* filing-history status.

Those remain gaps.

Because `AD` can contain personal mailing/residential-style addresses, preserve provenance and apply CivicMirror's normal handling rules before displaying or redistributing the field.

---

# Party Metadata

`partyIds` is a reference map joining the candidate `P` field to party information.

Observed party entries include:

```json
{
  "1": {
    "CD": "D",
    "NM": "Democratic Party"
  },
  "6": {
    "CD": "R",
    "NM": "Republican Party"
  }
}
```

The reference table also contains minor parties, petitioning candidates, and a write-in category.

Use the EMS party ID as the source join key, but normalize CivicMirror party identity from the official name/code rather than relying on a numeric ID to have the same meaning forever.

---

# Vote Results

## `stateVotes_Electiondata.json`

Observed structure follows the prior research mapping:

```json
{
  "<officeID>": [
    {
      "<candidateID>": {
        "V": "0",
        "TO": "0.00%"
      }
    }
  ]
}
```

Fields:

| Field         | Meaning                |
| ------------- | ---------------------- |
| office key    | Join to `officeList`   |
| candidate key | Join to `candidateIds` |
| `V`           | Vote count             |
| `TO`          | Vote percentage        |

## `townVotes_Electiondata.json`

Use for municipality-level candidate totals.

Expected joins:

```text
town ID
→ townIds

office ID
→ officeList

candidate ID
→ candidateIds

candidate.P
→ partyIds
```

## `officePrecincts_Electiondata.json`

Use when precinct-level results are required.

This should be preferred over attempting to infer precinct results from town totals.

## `districts_Electiondata.json`

Use for district-oriented result views where populated.

Do not treat this resource as authoritative district-boundary geometry. District geography belongs in a separate GIS pipeline.

---

# Election-Level Reporting Data

## `election_Electiondata.json`

The pre-election Republican primary capture returned:

```json
{
  "ID": "112",
  "BC": "0",
  "PR": "0 of 336 (0%)",
  "RV": "0",
  "T": "0 of 169",
  "PT": "0 of 169",
  "TO": "0.00",
  "SVT": true
}
```

The previously mapped interpretation is:

| Field | Research interpretation                                                                |
| ----- | -------------------------------------------------------------------------------------- |
| `ID`  | EMS election ID                                                                        |
| `BC`  | Ballots cast                                                                           |
| `PR`  | Precinct reporting status                                                              |
| `RV`  | Registered voters                                                                      |
| `T`   | Towns reported/completed                                                               |
| `PT`  | Partially reported towns                                                               |
| `TO`  | Turnout percentage                                                                     |
| `SVT` | Boolean feature/status field; exact semantic meaning still needs explicit verification |

For election 112, the pre-election data indicates a reporting universe of:

* **336 precincts**
* **169 towns**

These values are useful for checking completeness after voting begins, but should not be hard-coded as universal Connecticut constants.

---

# Official / Unofficial Result Status

## `reports_Electiondata.json`

The August 10 pre-election capture returned:

```json
{
  "IR": "False",
  "IO": "False"
}
```

The public frontend uses these report-status values to control result-state presentation.

The earlier project research interpreted:

* `IR` as informal-results publication status;
* `IO` as official-results status.

The HAR confirms the fields and the application's official/unofficial presentation behavior, but CivicMirror should distinguish **EMS display status** from statutory/legal certification.

### Recommended rule

Use `IO` as the EMS's own official-results indicator, but do not set final CivicMirror certification solely because:

* all precincts report;
* turnout reaches a final-looking number;
* `IO` changes.

For final certification provenance, reconcile with official Secretary of the State final/certification records or the Historical Election Database / Statement of Vote as applicable.

**100% reporting is not the same thing as legal certification.**

---

# Ballot Questions

`ballotQuestion_Electiondata.json` is loaded directly by the public application.

The earlier mapping shows structures containing:

* official question text;
* YES votes;
* NO votes;
* statewide results;
* town-level results.

Suggested normalized fields:

```text
logical election
source EMS election ID
question text
question identifier if available
scope
town/jurisdiction
yes votes
no votes
other response values
official-status provenance
source version
```

The Historical Election Database should be used for long-term ballot-question backfill and final historical reconciliation.

---

# Candidate Grouping

`candidateGrouping_Electiondata.json` is explicitly loaded by the frontend.

This is relevant for:

* multi-seat contests;
* candidate groupings;
* ballot structures where a simple one-office/one-candidate-list model may be insufficient.

Preserve the raw grouping relationship even if CivicMirror does not initially use it.

Do not discard this file during ingestion merely because statewide single-winner contests do not need it.

---

# Access Behavior and Authentication

## HAR-Observed Core Request Pattern

Typical request:

```text
GET /ng-app/data/election/112/1148/stateVotes_Electiondata.json
Accept: application/json, text/plain, */*
```

Observed characteristics:

* HTTP GET
* same-origin
* no core query parameters
* JSON response
* no API key
* no application `Authorization` header
* Cloudflare delivery
* ASP.NET origin/application headers
* `AWSALB` / `AWSALBCORS` cookies

### Classification

**Public, no application authentication observed.**

Do not describe the service as authenticated simply because AWS load-balancer cookies are present.

Do not hard-code those cookies in a CivicMirror adapter unless independent direct-request testing demonstrates that they are required.

---

# Additional HTML / Report Endpoints

The HAR exposes report-generation behavior in addition to the static JSON data.

Example frontend request:

```text
POST Default.aspx/GetVotingDistrictValuesByOfficeID
```

with parameters conceptually containing:

```text
electionID
townID
officeId
```

The frontend then navigates to:

```text
Default.aspx?action=VotingDistrictByOfficeID
```

A ballot/report route was also observed:

```text
Default.aspx?action=Ballot
    &electionID=...
    &electionName=...
    &townName=...
    &townID=...
```

### Classification

These are **HTML/report-generation endpoints**, not a documented public API.

They may be useful for:

* human-readable reports;
* spot checking;
* reproducing public UI output;
* fallback review.

They are **not required for the preferred CivicMirror result-ingestion path**.

Use static JSON first.

---

# Election Coverage

## EMS Catalog

The public catalog contains elections dating back at least to 2016, including:

* presidential/general elections;
* state elections;
* state primaries;
* presidential-preference primaries;
* municipal elections;
* municipal primaries;
* special elections;
* probate-related elections;
* other off-cycle elections.

However, the Secretary of the State's official election-results materials describe electronic EMS results as beginning in **August 2018**.

### CivicMirror normalization rule

Treat:

* **August 2018–present** as the state-described EMS coverage period;
* earlier catalog entries as **legacy/imported records that happen to be exposed by the EMS**.

Do not claim guaranteed complete EMS coverage for all Connecticut elections beginning in 2016 solely because some 2016–2017 records are present.

---

# Historical Election Database

**URL:** https://electionhistory.ct.gov/eng

**Responsible entity:** Connecticut Secretary of the State

**Rank: 2 — preferred historical source**

Previously verified official coverage:

* state elections for which records exist from **1787 to present**;
* municipal elections from **2001 to present**.

The system provides searchable historical:

* elections;
* contests;
* candidates;
* ballot questions;
* town results;
* source documents.

Structured CSV downloads have been observed for individual historical contests and ballot-question records.

### Classification

| Attribute           | Value                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------- |
| Source type         | Database portal + HTML + CSV export + source documents                                |
| API                 | No documented public API verified                                                     |
| Machine readability | High where CSV export exists                                                          |
| Authentication      | None observed                                                                         |
| Best use            | Historical results, candidate/contest backfill, ballot measures, final reconciliation |

Some download URLs may contain an `/api/` path internally. Do **not** label this as an official public API unless Connecticut publishes an API contract or documentation.

Call these **CSV export endpoints**.

### Recommended extraction priority

1. CSV export
2. structured HTML
3. linked official source document
4. manual/PDF extraction as last resort

Preserve:

* source election ID;
* source contest ID if present;
* export URL;
* election date;
* office;
* district;
* candidate/choice;
* party;
* geography;
* votes;
* attached source-document URL;
* access date.

---

# Statement of Vote / Election Results Archive

**Results landing page:**
https://portal.ct.gov/sots/election-services/election-results/election-results

Connecticut also maintains historical Statement of Vote and election-result archive materials.

These should be treated as high-value provenance and certification sources rather than the preferred first extraction source when structured EMS JSON or historical CSV is available.

### Classification

* PDF
* Excel
* HTML archive
* other downloadable historical files

### CivicMirror use

Use for:

* certified result reconciliation;
* historical gaps;
* validation of older structured records;
* general-election final totals;
* human review.

For every PDF used, preserve:

```text
document title
election date
official URL
offices/election types covered
certification/finality context
machine-extraction difficulty
access date
```

---

# Election Calendars and Election Creation

**Official source:**
https://portal.ct.gov/sots/election-services/calendars/election-calendars

The official SOTS calendar and election-notice pages should be the primary Stage 1 source for future elections.

Do **not** use `Elections.json` as Connecticut's complete master calendar.

An election may exist officially before an EMS ID has been published.

### Recommended Stage 1 sequence

1. Create the logical election from SOTS calendar/notice material.
2. Record:

   * date;
   * official name;
   * election type;
   * jurisdiction;
   * party restriction where applicable.
3. Monitor EMS discovery.
4. Attach one or more EMS IDs when they appear.
5. Preserve the mapping rather than replacing the logical election with the EMS source record.

This approach handles primaries, special elections, municipal contests, and other off-cycle elections more safely.

---

# Candidates, Filing Status, and Ballot Qualification

**Official starting point:**
https://portal.ct.gov/sots/election-services/candidate-information/candidate-ballot-access

Candidate information is fragmented across:

* SOTS candidate ballot-access materials;
* endorsement/certification material;
* official candidate lists when published;
* official sample ballots;
* EMS once the election is loaded;
* local registrars/town clerks for some town-only offices.

The EMS is valuable for **results-era candidate identity**, but it should not be assumed to contain the complete filing workflow.

### Suggested candidate pipeline

Pre-election:

```text
official candidate/filing source
→ office
→ district
→ party
→ filing/endorsement status
→ ballot qualification
```

After EMS publication:

```text
normalized candidate
↔ EMS candidate ID
↔ EMS office ID
↔ party ID
```

### Known candidate gaps

No single verified statewide machine-readable source was identified for all of:

* filing status;
* petition status;
* endorsement status;
* ballot qualification;
* withdrawal;
* disqualification;
* incumbency;
* contact information;
* biography.

Manual review may still be required for local offices.

---

# Campaign Finance

**Official source:**
https://seec.ct.gov/portal/ecris/ecris-search

**Responsible entity:** Connecticut State Elections Enforcement Commission

The eCRIS public portal supports campaign-finance research involving:

* candidate committees;
* party committees;
* PACs;
* filings;
* receipts;
* expenditures;
* independent expenditures;
* summary data.

### Classification

| Attribute             | Value                  |
| --------------------- | ---------------------- |
| Source type           | Database/search portal |
| Public access         | Yes                    |
| Documented public API | Not verified           |
| Pipeline stage        | Campaign finance       |
| Integration value     | Medium                 |

Campaign-finance data should remain a separate CivicMirror source relationship rather than being inferred from EMS party/candidate result records.

---

# Districts / GIS

Connecticut's official GIS resources should be used for district geometry.

EMS `DT` and `D` values are useful district identifiers but are **not geographic boundary data**.

Suggested join keys:

```text
office type
+ district number
+ election cycle/redistricting era
```

Exact machine-readable state GIS service URLs should be captured in a separate research update before GIS automation is treated as resolved.

---

# CT Open Data Portal — Correction

The earlier research treated:

```text
https://data.ct.gov/Government/Election-Results-and-Voter-Turnout/2cta-kxuv
```

as a standalone structured Socrata election-results dataset suitable for SODA ingestion.

That assessment should be retired.

The state catalog item points users toward Connecticut's election-results service rather than providing a separately verified structured historical election-results dataset.

### CivicMirror recommendation

Do **not** treat `2cta-kxuv` as a separate Stage 2 election-results API.

For structured historical data, prioritize:

1. Historical Election Database CSV exports;
2. EMS JSON;
3. official archive files.

---

# TotalVote / KNOWiNK — Correction

The May 31 file treated Connecticut's TotalVote purchase as evidence that the existing PCC-style EMS result reporting would be replaced by a TotalVote/TotalResults election-results system and suggested reusing Arkansas's TotalResults API patterns.

That conclusion was too strong.

Official Connecticut material reviewed during the August 10 research describes TotalVote in the context of Connecticut's **centralized voter-registration system**.

No official Connecticut source reviewed establishes that:

* `ctemspublic.tgstg.net` is being replaced by TotalResults;
* Connecticut will expose an Arkansas-style TotalResults REST API;
* the current CT results adapter should be designed around a future TotalResults migration.

### Revised recommendation

Monitor Connecticut's official results infrastructure, but do not plan an adapter migration until an actual Connecticut election-results replacement endpoint is published or observed.

TotalVote remains relevant to voter registration/district-management research, not presently as a verified Stage 2 results replacement.

---

# Source Inventory

| Rank | Source                                    | Responsible entity      | Type                  | Coverage                               | Machine readability | Authentication | Primary CivicMirror role                                 |
| ---: | ----------------------------------------- | ----------------------- | --------------------- | -------------------------------------- | ------------------- | -------------- | -------------------------------------------------------- |
|    1 | `ctemspublic.tgstg.net` EMS               | CT SOTS                 | Static JSON + HTML    | Current/recent EMS elections           | High                | None observed  | Results, contests, candidates, turnout, ballot questions |
|    2 | Historical Election Database              | CT SOTS                 | Database + CSV + HTML | State historical; municipal historical | High/medium         | None observed  | Historical elections/results/ballot questions            |
|    3 | SOTS Calendars / Candidate / Ballot pages | CT SOTS                 | HTML/PDF/files        | Current/future elections               | Medium/low          | None           | Election creation, filing, qualification                 |
|    4 | Statement of Vote / Results Archive       | CT SOTS                 | PDF/Excel/HTML        | Historical/final results               | Medium/low          | None           | Certification/reconciliation                             |
|    5 | SEEC eCRIS                                | SEEC                    | Database portal       | Campaign finance                       | Medium              | Public         | Campaign finance                                         |
|    6 | State GIS resources                       | State GIS Office        | GIS/PDF               | District geography                     | Potentially high    | TBD by service | District geometry                                        |
|    — | CT Open Data `2cta-kxuv`                  | State open-data catalog | Catalog/link entry    | Points toward election results         | Low                 | Public         | Provenance/discovery only                                |

---

# CivicMirror Pipeline Map

| Pipeline Stage       | Primary CT Source                               | Suggested IDs / Join Keys                           | Update Strategy                  | Known Gap                                      |
| -------------------- | ----------------------------------------------- | --------------------------------------------------- | -------------------------------- | ---------------------------------------------- |
| Election calendar    | SOTS calendars/notices                          | date + official title + jurisdiction                | Monitor official notices         | Primarily HTML/PDF                             |
| Election definition  | Calendar + EMS catalog                          | logical election ↔ EMS ID(s)                        | Attach EMS IDs after publication | EMS is not a complete future calendar          |
| Election type        | SOTS + EMS `ET`/`EC`                            | date + type + party                                 | Normalize from multiple fields   | Category code vocabulary not fully documented  |
| Offices              | `Lookupdata.officeList`                         | EMS office ID                                       | Refresh each source version      | ID stability across long periods needs testing |
| Districts            | EMS IDs + state GIS                             | office type + district                              | Update by redistricting era      | GIS endpoint unresolved                        |
| Contests             | EMS office/result structures                    | logical election + source election + office + party | Upsert each version              | Multi-ID primaries                             |
| Candidates           | `candidateIds` + SOTS candidate sources         | EMS candidate ID + normalized identity              | Reconcile pre-election and EMS   | Filing-status feed fragmented                  |
| Filing status        | SOTS/local filing sources                       | candidate + office + district                       | Deadline/event driven            | Local fragmentation                            |
| Ballot qualification | Official ballots                                | candidate + office + district + party               | Finalize from ballot             | Often document-based                           |
| Party                | `partyIds` + source election party              | source party ID/code                                | Preserve source party            | Cross-endorsement requires care                |
| Ballot measures      | EMS + Historical DB                             | election + question                                 | Poll EMS; historical CSV         | Older formats vary                             |
| Results              | EMS JSON                                        | EMS election ID + version + office/candidate IDs    | Version polling                  | Adapter currently one ID                       |
| Reporting status     | `election_Electiondata.json`                    | EMS ID + version                                    | Poll with results                | Field semantics partly undocumented            |
| Official status      | `reports_Electiondata.json` + final SOTS source | EMS ID/version + certification artifact             | Reconcile after election         | Do not equate 100% with certification          |
| Recounts/recanvasses | SOTS notices/final records                      | contest + official notice                           | Event driven                     | No structured feed identified                  |
| Special elections    | Calendars + EMS                                 | date + jurisdiction + EMS ID                        | Monitor continuously             | Off-cycle discovery required                   |
| Campaign finance     | SEEC eCRIS                                      | committee ID + candidate                            | Filing driven                    | No documented public API verified              |
| Historical archive   | Historical DB + SOV                             | election/contest/source document IDs                | Backfill/reconcile               | Older docs can be machine-unfriendly           |

---

# Recommended CT Results Ingestion Workflow

## Election Discovery

Use:

```text
Elections.json
```

to discover EMS source elections.

Do not assume:

```text
one logical CivicMirror election = one EMS election
```

Instead group compatible source elections by:

```text
date
election type
jurisdiction
party/component
official election-calendar context
```

## Per Source Election

For each EMS ID:

```text
1. GET Version.json
2. GET Lookupdata.json
3. GET stateVotes_Electiondata.json
4. GET election_Electiondata.json
5. GET voterTurnout_Electiondata.json
6. GET townVotes_Electiondata.json
7. GET townStatus_Electiondata.json
8. GET reports_Electiondata.json
9. GET districts_Electiondata.json
10. GET officePrecincts_Electiondata.json
11. GET ballotQuestion_Electiondata.json
12. GET candidateGrouping_Electiondata.json
```

## Normalize

Join:

```text
office ID
→ officeList

candidate ID
→ candidateIds

candidate party ID
→ partyIds

town ID
→ townIds
```

Then add the source-election context:

```text
EMS election ID
EMS election party
EMS version
logical CivicMirror election ID
```

## Multi-ID Merge

For August 11, 2026:

```text
logical election
├── EMS 111 Democratic Primary
└── EMS 112 Republican Primary
```

Merge them at the **election** level, not at the race level.

Keep Democratic and Republican office contests distinct.

---

# August 11–12, 2026 Validation Plan

Issue #170's scheduled post-election check remains useful, but the HAR changes what needs to be verified.

The existence of IDs 111 and 112 is now resolved.

The post-election check should instead confirm:

1. election 111 returns Democratic live/final results;
2. election 112 returns Republican live/final results;
3. both retain the expected `SP`/primary metadata;
4. both version numbers change during reporting;
5. vote totals resolve correctly through office/candidate/party joins;
6. precinct/town reporting reaches expected completion;
7. `reports_Electiondata.json` transitions as expected;
8. CivicMirror has added multi-ID support;
9. contests from the two parties remain distinct;
10. final results can be reconciled with official SOTS final/certified material.

Do not close the CivicMirror blocker simply because either `111` **or** `112` works independently.

Full statewide primary ingestion requires both.

---

# Known Gaps / Human Review

1. **CivicMirror multi-ID adapter support remains the primary current blocker.**
2. Exact semantic meaning of every EMS election/category code has not been formally documented.
3. `SVT` and candidate `CO` require explicit interpretation before normalization.
4. `IR` should remain preserved raw until its exact state transition semantics are reconfirmed.
5. EMS official-status behavior should be reconciled with statutory certification.
6. Candidate filing/qualification data is fragmented, especially for local offices.
7. No verified statewide structured candidate-filing API was found.
8. GIS machine-readable district endpoint still needs to be captured.
9. No dedicated structured recount/recanvass feed was identified.
10. EMS catalog coverage should not be assumed complete for every off-cycle election without comparing SOTS calendars/notices.
11. Older historical records may require PDF/manual review.
12. TotalVote should not be treated as a confirmed election-results replacement.
13. CT Open Data item `2cta-kxuv` should not be treated as a separate results API.

---

# Source Coverage Analysis

Connecticut is a strong CivicMirror state for results ingestion.

The current Election Night Reporting application exposes a predictable, public, machine-readable static-JSON architecture with:

* election discovery;
* version/change detection;
* office metadata;
* district identifiers;
* candidate identity;
* candidate party;
* candidate address fields;
* statewide vote totals;
* town vote totals;
* precinct detail;
* turnout;
* reporting status;
* ballot questions;
* multi-seat candidate grouping.

The August 10 HAR turns the most important EMS assumptions into reproducible network observations.

The principal Stage 2 weakness is **inside CivicMirror, not Connecticut's public data**. Connecticut's primary-election model routinely assigns separate EMS election IDs by party, while the current CT adapter expects one source ID per logical election.

For 2026 the state-source mapping is now confirmed:

```text
August 11, 2026 Primary
  Democratic → EMS 111
  Republican → EMS 112
```

Historical evidence in `Elections.json` shows this design recurring across multiple prior cycles. CivicMirror should therefore implement multi-ID source-election mapping as a normal Connecticut adapter capability.

The May 31 research correctly identified the EMS's versioned static-data architecture and most of its data files, but several earlier conclusions required correction. In particular:

* `PD` means probate district, not presidential;
* `DefaultElection` is not a stable current-cycle identifier;
* the 2026 primary is split across IDs 111 and 112;
* the EMS contains candidate address data;
* the CT Open Data catalog item should not be treated as an independent SODA results feed;
* TotalVote is not currently verified as the replacement for Connecticut's election-results reporting system.

**Recommended CivicMirror priority:** implement multi-ID CT ingestion first, validate it against the August 11, 2026 primary, then use the Historical Election Database for systematic backfill and official archive material for final reconciliation.
