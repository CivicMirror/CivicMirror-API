# Wyoming Election Results — Research Notes


### Coverage Status

| Pipeline stage                                | Status                                       | Best official Wyoming source                                                | CivicMirror implication                                                                                                                                           |
| --------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Election creation                             | ✅ **Official source available**              | SOS election calendar / key dates                                           | Primary, general, and scheduled off-cycle election dates can be created from first-party sources rather than relying on Google Civic.                             |
| Race creation — federal/statewide/legislative | ✅ **Source available; adapter not verified** | SOS candidate CSV + Offices Up for Election + Judges Standing for Retention | Enough first-party data exists to create most state-administered 2026 contests before results are published.                                                      |
| Race creation — local/county                  | ⚠️ **Decentralized**                         | County clerks                                                               | SOS explicitly directs local candidate/result inquiries to county clerks.                                                                                         |
| Candidate ingestion                           | ✅ **Structured source**                      | 2026 candidate CSV; PDF roster; withdrawn roster                            | CSV should be primary. PDF rosters are validation/human-review sources.                                                                                           |
| Filing / withdrawal status                    | ✅ **Available**                              | Candidate roster + withdrawn candidate roster                               | Join on candidate/office/party; withdrawn list provides status changes.                                                                                           |
| District / precinct mapping                   | ✅ **Available, partly machine-unfriendly**   | SOS district/precinct PDFs; SOS-linked ArcGIS experiences                   | Precinct-to-legislative-district joins are available; GIS boundary service endpoint still needs verification.                                                     |
| Ballot measures / initiatives                 | ✅ **Available**                              | SOS Initiative & Referendum page + certification/full-text PDFs             | Qualification status and official ballot text are state-sourced.                                                                                                  |
| Results — certified                           | ✅ **Structured bulk files**                  | SOS election results archive, Excel spreadsheets in ZIP                     | Primary Stage 2/backfill path. Wyoming has never been shown to use Clarity — no historical Clarity URL exists for WY in any source reviewed.                     |
| Results — election night/live                 | ⚠️ **Unresolved**                            | No current state-authoritative ENR endpoint verified                        | Issue #180 should remain open until the actual 2026 state results endpoint is identified. Do not resume looking for a Clarity election ID.                       |
| Certification                                 | ✅ **Available**                              | State Canvassing Board minutes/certification                                | Store separately from raw results; useful source of certified status/date.                                                                                        |
| Special elections                             | ✅ **Historical evidence**                    | SOS results archive                                                         | Archive explicitly includes several special elections.                                                                                                            |
| Runoffs                                       | ➖ **No recurring state source identified**   | —                                                                           | No runoff election appears in the current SOS calendar/archive review; do not create a generic Wyoming runoff feed without an actual event.                       |
| Recalls                                       | ➖ **Not a statewide election type**          | SOS FAQ                                                                     | SOS says Wyoming has no recall provision for state elected officials or legislators; limited municipal recall provision currently has no applicable municipality. |
| Campaign finance                              | ✅ **Public database + export**               | WYCFIS                                                                      | Public contribution/expenditure/filing search; text export available; no public API verified.                                                                     |
| Historical archive                            | ✅ **Good**                                   | SOS results index                                                           | Regular primary/general results are indexed back through 1996, plus selected specials.                                                                            |

The original research file classified election creation as Google Civic, race creation as untested Google Civic, and results ingestion as "No adapter / PDF/Excel (Clarity unverified)." A subsequent follow-up (also captured in issue #180) found no historical evidence Wyoming has ever run its ENR on Clarity — MEDSL's 2018 source list records WY's unofficial results as coming from the SOS's own page, not a `results.enr.clarityelections.com` URL, and the only Clarity match for "Wyoming" is unrelated Wyoming *County, West Virginia*. `results/adapters/wy.py` should be retired in favor of a WY-native adapter against the SOS Excel-ZIP archive rather than kept as a `ClarityAdapter` subclass waiting on a URL. ([[GitHub](https://github.com/CivicMirror/CivicMirror-API/issues/180)][1])

---

**Primary election site:** `https://sos.wyo.gov/Elections/`
**Results archive:** `https://sos.wyo.gov/elections/electionresults.aspx`
**Campaign finance:** `https://www.wycampaignfinance.gov/`
**Operated by:** Wyoming Secretary of State, with county clerks administering local election functions
**Researched:** March 4, 2026
**Updated:** August 10, 2026 — verified first-party 2026 calendar, candidate, filing-status, district, ballot-measure, certified-results, certification, and campaign-finance sources; found no historical evidence Wyoming has ever used Clarity for ENR and recommended retiring the `ClarityAdapter` in favor of a WY-native adapter (issue #180); live 2026 election-night results URL remains unresolved
**Accessed:** August 10, 2026
**Authentication:** Public election information and public WYCFIS search require no login; filer functions are separate

---

## Overview

Wyoming's election data is split between the **Wyoming Secretary of State** and the state's **23 county clerks**. The Secretary of State publishes statewide election calendars, state/federal/legislative candidate information, statewide ballot propositions and initiatives, legislative district information, certified statewide and legislative results, judicial-retention results, canvass certifications, and statewide campaign-finance information. SOS guidance says local-office candidates should contact their county clerk and that local election results are published on county-clerk websites. ([[Wyoming Secretary of State](https://sos.wyo.gov/faqs.aspx?root=ELEC)][4])

For CivicMirror, the strongest discovery from this update is that **race creation does not need to depend on election-night results**. The current 2026 Election Center exposes the candidate roster, a state-linked candidate data file, withdrawn candidates, offices up for election, judges standing for retention, initiatives, and district/precinct mappings before the August 18 primary. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/)][2])

For certified results, Wyoming provides a better machine-readable path than the original notes conveyed. The 2024 general and primary result pages explicitly provide ZIP files containing **Microsoft Excel spreadsheets of the official results**, while retaining PDF reports and precinct-by-precinct summaries. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx)][5])

---

## 1. 2026 Election Calendar and Election Creation

### Official sources

* `https://sos.wyo.gov/Elections/`
* `https://sos.wyo.gov/Elections/Docs/2026/2026_Key_Election_Dates.pdf`
* `https://sos.wyo.gov/Elections/Docs/2026/2026_Election_Calendar.pdf`

The Secretary of State identifies the **2026 Primary Election as August 18, 2026** and the **2026 General Election as November 3, 2026**. The key-dates document also supplies filing, party, initiative, registration, and absentee-voting deadlines. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/)][2])

The broader election calendar is valuable because Wyoming also conducts or schedules town, bond, special-district formation, subsequent-director, and other off-cycle election activity. The SOS maintains a dedicated local-elections page for these events; for example, its 2025 schedule identifies May town/bond/special-district elections, August bond elections, and November bond/director elections when applicable. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/LocalElections.aspx?utm_source=chatgpt.com)][6])

### CivicMirror use

Use the SOS calendar as the first-party election-definition source. Suggested election key:

`WY:{election_date}:{normalized_election_type}`

Normalize at least:

* `primary`
* `general`
* `special`
* `town`
* `bond`
* `special_district_formation`
* `special_district_director`
* other local/off-cycle types exactly as identified by the official notice

Do not assume every scheduled off-cycle date has an election. Some SOS calendar entries are conditional (“if applicable”), so county confirmation is required before creating a local election instance.

---

## 2. Candidate and Race Creation

### 2026 Primary Candidate Data — highest-value Stage 1 source

Official Election Center:

`https://sos.wyo.gov/Elections/2026ElectionInformation.aspx`

Structured candidate file:

`https://sos.wyo.gov/Elections/Docs/2026/2026_WY_Primary_Election_Candidates.csv`

Candidate roster:

`https://sos.wyo.gov/Elections/Docs/2026/2026_WY_Primary_Election_Candidates.pdf`

Withdrawn candidates:

`https://sos.wyo.gov/Elections/Docs/2026/2026_WY_Withdrawn_Primary_Election_Candidates.pdf`

The Election Center labels its structured candidate download an “Excel data file,” but the actual state-linked URL ends in **`.csv`**. The browsing environment could not parse the response because it is served as `application/octet-stream`; therefore the file should be treated as a direct CSV download to inspect in a normal download client rather than inferred to be XLSX. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/)][2])

The PDF roster exposes useful fields including candidate name, party affiliation, office sought, mailing/contact information, filing date, and withdrawal information where applicable. A separate withdrawn-candidate roster gives CivicMirror an authoritative way to detect candidates who should no longer be considered active. The state also says candidates for state office, including the legislature, may file online or submit the nomination form; local-office filings go through county clerks. ([[Wyoming Secretary of State](https://sos.wyo.gov/faqs.aspx?root=ELEC)][4])

### Extraction recommendation

**Primary:** CSV
**Validation/fallback:** candidate PDF
**Status changes:** withdrawn-candidate PDF

Recommended natural join before a stable source identifier is verified:

`election + normalized_office + district + candidate_name + party`

Do not use email or mailing address as a durable candidate identifier.

During the filing period, refresh frequently. After filing closes, continue checking through ballot certification because withdrawals and qualification changes can alter the roster.

### Known gap

The SOS state-level candidate source is strongest for federal, statewide, and legislative races. Local/county/municipal/school/college races remain decentralized; the SOS directs those candidates to county clerks. ([[Wyoming Secretary of State](https://sos.wyo.gov/faqs.aspx?root=ELEC)][4])

---

## 3. Offices, Judicial Retention and Contest Definitions

Official PDFs:

`https://sos.wyo.gov/Elections/Docs/2026/2026_Offices_Up_for_Election.pdf`

`https://sos.wyo.gov/Elections/Docs/2026/2026_Judges_Standing_for_Retention.pdf`

The offices-up document provides an authoritative checklist for expected 2026 contests, while the judges document supplies the judicial-retention contests that should not be modeled as ordinary candidate-versus-candidate races. The offices document also identifies an unexpired-term Senate contest, demonstrating why CivicMirror should preserve `term_type` or an equivalent “unexpired term” marker instead of identifying contests only by district. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/)][2])

Recommended contest key components:

`election + office_type + office_name + district + seat/term qualifier`

For judicial retention use:

`election + court + judicial_office + judge_name + retention`

---

## 4. District and Precinct Sources

### PDF crosswalks

`https://sos.wyo.gov/Elections/Docs/2026/2026_Districts_and_Precincts_by_County.pdf`

`https://sos.wyo.gov/Elections/Docs/2026/2026_Districts_and_Precincts_by_Legislative_District.pdf`

The reports explicitly map **county → Senate/House district → precinct code** and the reverse legislative-district-oriented view. This is valuable for normalizing precinct-level result files and checking whether a precinct result belongs in the expected legislative contest. 

### GIS

SOS legislative-district page:

`https://sos.wyo.gov/Elections/LegislativeDistrictsHome.aspx`

Official SOS-linked ArcGIS experiences:

`https://experience.arcgis.com/experience/f086f052f28b4185a785f19344a057be/page/House-Districts-for-2022-Election/`

`https://experience.arcgis.com/experience/f086f052f28b4185a785f19344a057be/page/Senate-Districts-for-2022-Election/`

The SOS identifies these as current legislative district information based on the 2022 redistricting cycle. The ArcGIS Experience pages were reachable, but this research did **not** verify a downloadable FeatureServer, shapefile, GeoJSON endpoint, or documented GIS API. Accordingly, classify them as **GIS web applications**, not APIs.

### Pipeline use

Suggested precinct key:

`county_fips_or_name + precinct_code`

Keep the original precinct code as published. Do not coerce values such as `01-02` into numbers because leading zeroes and hyphen structure are meaningful.

---

## 5. Certified Election Results

### Main archive

`https://sos.wyo.gov/elections/electionresults.aspx`

The state archive currently indexes regular primary/general elections from **1996 through 2024**. It also contains explicit historical special-election entries, including House District 36 in 2002, House District 22 in 2008, a Teton County Circuit Court special election in 2014, and a Sweetwater County House District 18 precinct-level Republican special election in 2016. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/electionresults.aspx?utm_source=chatgpt.com)][7])

This is stronger historical evidence than treating the archive as primary/general only.

### Verified 2024 General structure

`https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx`

The page provides:

* statewide candidate summaries;
* Senate and House summaries;
* judicial-retention results;
* constitutional-amendment results;
* ballots-cast and provisional-ballot summaries;
* State Canvassing Board minutes/certification;
* a ZIP containing official Microsoft Excel spreadsheets;
* a combined PDF;
* county precinct-by-precinct reports for statewide and legislative contests, judicial retention, and ballot issues. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx)][5])

The SOS explicitly says local and county results must be obtained from the individual county websites. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx)][5])

### Bulk download example

2024 General:

`https://sos.wyo.gov/Elections/Docs/2024/Results/General/2024_Wyoming_General_Results.zip`

The state describes the contents as Microsoft Excel spreadsheets. Do **not** retain the old research file's stronger claim that the format is necessarily “XLSX” until the archive's contents/extensions are inspected directly. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx)][5])

### Result subjects

Verified current result structure supports:

* candidate votes;
* party/candidate labels;
* statewide totals;
* legislative district totals;
* county totals;
* precinct totals;
* write-ins;
* overvotes;
* undervotes;
* judicial retention;
* statewide ballot issues;
* turnout/ballots-cast summaries;
* provisional-ballot summaries.

The official 2024 page states that its summaries include write-ins, undervotes, and overvotes for each covered race. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx)][5])

### Recommended certified-results pipeline

1. Discover election pages from the SOS results index.
2. Prefer the official Excel ZIP when available.
3. Parse every workbook/sheet while preserving source sheet names.
4. Normalize contest/candidate names against the pre-election candidate roster.
5. Join precinct rows through the district/precinct crosswalk.
6. Ingest write-in, undervote, and overvote values as explicit result categories rather than discarding them.
7. Treat State Canvassing Board certification as a separate provenance event.
8. Retain PDF summaries for human validation.

This provides a viable **certified-results adapter independent of Clarity**.

---

## 6. Certification

Current result pages publish a dedicated State Canvassing Board section. For the 2024 general election the official minutes record the board's review and certification of the state abstract. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx)][5])

Example:

`https://sos.wyo.gov/Elections/Docs/2024/Results/General/2024_General_State_Canvassing_Board_Minutes.pdf`

Recommended CivicMirror fields:

* `certification_status`
* `certification_date`
* `certification_source_url`
* `canvassing_body`
* `source_election`
* `supersedes_unofficial_results`

Do not infer “certified” solely from 100% precinct reporting. Use the official canvass/certification artifact.

---

## 7. Issue #180 — Clarity Adapter Is the Wrong Adapter

CivicMirror's `results/adapters/wy.py` (`WyomingAdapter`) currently subclasses the generic `ClarityAdapter`. The commit that added it (`cdfb46e`, "feat(results): add Tier A Clarity adapters for 20 states") claimed Wyoming was "confirmed on Clarity ENR via probe on 2026-05-31," but no probe artifact or log backing that claim exists in the repo, and it appears to have been a false positive: `Election.results_url` has sat blank since the adapter was added, because nobody has ever found a real Wyoming Clarity URL. ([[GitHub](https://github.com/CivicMirror/CivicMirror-API/issues/180)][1])

### What this research could verify

* No official Wyoming source — current SOS pages, the SOS results archive, or Clarity's own search — exposes a Wyoming-state Clarity election URL. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/)][2])
* MEDSL's 2018 election-night scraper source list records WY's unofficial-results source as the SOS's own results page, not a `results.enr.clarityelections.com` URL — unlike states that genuinely use Clarity (AR, CO, GA, IA, WV, etc.), which appear in that list with explicit Clarity URLs.
* The Wyoming SOS results archive is itself the state's authoritative ENR-equivalent system, currently indexing elections through 2024. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/electionresults.aspx?utm_source=chatgpt.com)][7])
* Searches against Clarity surfaced **Wyoming County, West Virginia**, which must not be confused with the State of Wyoming. For example, the searchable Clarity URL has `/WV/Wyoming/`, not a Wyoming-state jurisdiction. ([[Clarity Elections](https://results.enr.clarityelections.com/WV/Wyoming/126264/web.345435/?utm_source=chatgpt.com)][8])

### CivicMirror recommendation

**Do not populate `results_url` by guessing a Clarity election ID — there is no evidence a Wyoming Clarity instance exists.**

Retire `WyomingAdapter(ClarityAdapter)` and build a WY-native adapter against the SOS Excel-ZIP results archive for certified/backfill results, and the candidate CSV for Stage 1 race/candidate creation. That path is already verified and removes Clarity entirely as a Stage 2 blocker.

Leave live/election-night 2026 results as the one genuinely open item (issue #180) — monitor the SOS for an actual results-publication URL rather than guessing one.

---

## 8. Ballot Measures, Initiatives and Referenda

Official portal:

`https://sos.wyo.gov/elections/initiativereferenduminfo.aspx`

The portal identifies a completed 2026 initiative, **People's Initiative to Limit Property Tax in Wyoming through a Homeowner's Property Exemption**, with status “Complete; Filed with the Secretary of State's Office,” and links both its ballot certification and full text. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/initiativereferenduminfo.aspx)][9])

### Relevant official PDFs

Certification:

`https://sos.wyo.gov/Elections/Docs/Property_Tax_Initiative_Certificate.pdf`

Full text:

`https://sos.wyo.gov/Elections/Docs/Peoples_Initiative_to_Limit_Property_Tax_in_Wyoming-Homeowners.pdf`

Historical initiative/referendum summary:

`https://sos.wyo.gov/Elections/Docs/IRSum.pdf`

The historical summary provides useful qualification history—including proposals that qualified, failed signature requirements, expired, or were withdrawn—and therefore belongs in a ballot-measure historical pipeline rather than being treated only as explanatory documentation. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/Docs/IRSum.pdf)][10])

### Recommended measure identifiers

`election + measure_type + official_title`

Store separately:

* filing/application status;
* circulation status;
* qualification/certification status;
* official title;
* full text;
* sponsoring committee/applicants where published;
* election/ballot placement;
* final result.

---

## 9. Special, Off-Cycle, Runoff and Recall Treatment

### Special elections

Special elections are confirmed as a real Wyoming source category by the historical SOS result archive. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/electionresults.aspx?utm_source=chatgpt.com)][7])

Do not assume special contests always have a separate statewide election event. Some may involve a single district, court, or precinct.

### Local/off-cycle elections

The SOS local-election materials identify town, bond, special-district formation and subsequent-director election schedules. Actual applicability is local, making the state calendar a discovery source and county clerks the confirming/result source. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/LocalElections.aspx?utm_source=chatgpt.com)][6])

### Runoffs

No recurring Wyoming state runoff election was identified in the current SOS election calendar or results archive during this review. A legislative search surfaced a historical **working draft** proposing runoff elections, which is not evidence of an enacted/current statewide runoff process. Therefore CivicMirror should not create a Wyoming runoff source based on that draft. ([[Wyoming Legislature](https://wyoleg.gov/InterimCommittee/2021/07-2021090222LSO-0093v0.4.pdf?utm_source=chatgpt.com)][11])

### Recalls

The Secretary of State FAQ states that there is **no recall provision for state elected officials or legislators**. It identifies a municipal recall provision for commission-form governments but says no Wyoming municipality currently has that form of government. ([[Wyoming Secretary of State](https://sos.wyo.gov/faqs.aspx?root=ELEC)][4])

For the statewide pipeline, mark recall as `not_applicable_currently` rather than `missing_source`.

---

## 10. Campaign Finance — WYCFIS

Public system:

`https://www.wycampaignfinance.gov/`

Public search:

`https://www.wycampaignfinance.gov/WYCFWebApplication/GSF_SystemConfiguration/PublicSearch.aspx`

Filed-report search:

`https://www.wycampaignfinance.gov/WYCFWebApplication/GSF_SystemConfiguration/SearchFilingPublic.aspx`

WYCFIS provides public searches for contributions, expenditures and filed reports covering candidates, candidate committees, PACs, organizations and political parties. Statewide filers use the system for online disclosure, while public access does not require filer authentication. ([[Wyoming Campaign Finance](https://www.wycampaignfinance.gov/WYCFWebApplication/GSF_Authentication/default.aspx/1000?utm_source=chatgpt.com)][12])

The official help documentation states that successful contribution and expenditure searches can be **exported to a text file** and can also be printed to PDF. This makes the public system meaningfully more machine-readable than a PDF-only finance archive. ([[Wyoming Campaign Finance](https://www.wycampaignfinance.gov/wycfwebapplication/Docs/WY%20HTML%20FILES/PUBLIC%20HTML/public_search_contributions.htm?utm_source=chatgpt.com)][13])

### Classification

**Source type:** database portal / HTML search forms / text export
**API:** no public REST API verified
**Authentication:** none for public search; filer login is separate
**Machine-readability:** medium-high when export is used
**Historical key:** election-year cycle

### Extraction approach

Prefer the public export function over scraping rendered result rows.

No HAR capture was available in this research environment, and no undocumented backend API was verified. Do not invent POST endpoints or treat ASP.NET form behavior as an API. If automation is required, capture a real browser session and document form parameters/network requests before implementing it.

### Local limitation

SOS guidance distinguishes state campaign-finance information from local candidate information, which may require county-clerk sources. ([[Wyoming Secretary of State](https://sos.wyo.gov/faqs.aspx?root=ELEC)][4])

---

## 11. Voter Registration and Turnout Statistics

Official statistics page:

`https://sos.wyo.gov/Elections/Statistics.aspx`

The SOS publishes monthly voter-registration reports by county/party and historical primary/general voter-turnout statistics. This source is supplemental to contest/results ingestion but useful for turnout validation and election metadata.

Recommended use:

`election + county + registration_date/party`

Do not use registration totals as vote-result totals.

---

## 12. Source Inventory

| Rank | Source                       | Entity                | Type                              | Coverage                                                             | Machine readability | Auth         | CivicMirror use                                          |
| ---- | ---------------------------- | --------------------- | --------------------------------- | -------------------------------------------------------------------- | ------------------- | ------------ | -------------------------------------------------------- |
| 1    | 2026 candidate data file     | WY SOS                | **CSV** direct download           | 2026 primary state/federal/legislative candidates                    | High                | None         | Candidates, races, party, filing                         |
| 2    | Certified result ZIPs        | WY SOS                | **Bulk ZIP / Excel**              | Verified for 2024 primary/general; archive page extends through 1996 | High                | None         | Certified results/backfill                               |
| 3    | WYCFIS public exports        | WY SOS/WYCFIS         | **Database portal / text export** | Campaign-finance cycles                                              | Medium-high         | None public  | Campaign finance                                         |
| 4    | Election results pages       | WY SOS                | **HTML pages**                    | 1996–2024 index + specials                                           | Medium              | None         | Election discovery, source URLs, certification discovery |
| 5    | Election Center              | WY SOS                | **HTML page**                     | Current cycle                                                        | Medium              | None         | Source discovery/current-cycle metadata                  |
| 6    | Initiative & Referendum      | WY SOS                | **HTML + PDF**                    | Current + historical initiative information                          | Medium              | None         | Measures, qualification, provenance                      |
| 7    | ArcGIS legislative maps      | SOS-linked GIS        | **GIS web application**           | 2022-redistricting legislative boundaries                            | Medium              | None         | District verification                                    |
| 8    | District/precinct crosswalks | WY SOS                | **PDF**                           | 2026                                                                 | Low-medium          | None         | Precinct/district joins                                  |
| 9    | Candidate/withdrawn rosters  | WY SOS                | **PDF**                           | 2026                                                                 | Low-medium          | None         | CSV validation, withdrawal status                        |
| 10   | Offices/judges lists         | WY SOS                | **PDF**                           | 2026                                                                 | Low-medium          | None         | Contest completeness                                     |
| 11   | State canvass documents      | WY SOS                | **PDF**                           | Election-specific                                                    | Low                 | None         | Certification                                            |
| 12   | County clerk sites           | Wyoming county clerks | **Varies**                        | Local/county races/results                                           | Varies              | Usually none | Local coverage                                           |

The rankings favor structured first-party data over PDFs. The candidate CSV and official result Excel files should therefore be the principal CivicMirror ingestion targets. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/)][2])

---

## 13. CivicMirror Pipeline Map

| Stage                     | Primary source                           | Identifier / join                  | Update strategy                                | Known gap                                                     |
| ------------------------- | ---------------------------------------- | ---------------------------------- | ---------------------------------------------- | ------------------------------------------------------------- |
| Election calendar         | SOS calendar/key dates                   | election date + type               | Refresh when cycle calendar changes            | Conditional local dates require confirmation                  |
| Election definitions/type | SOS calendar/results index               | date + official label              | Normalize cautiously                           | Local terminology varies                                      |
| Offices                   | Offices Up for Election                  | office + district + term           | Refresh each general cycle                     | Local offices county-managed                                  |
| Districts                 | precinct PDFs + GIS                      | district number; county + precinct | Update after redistricting/official changes    | No GIS service endpoint verified                              |
| Contests                  | offices + candidate CSV                  | election + office + district       | Rebuild during filing/certification            | Local contests fragmented                                     |
| Candidates                | candidate CSV                            | office/district/name/party         | Frequent during filing period                  | Stable candidate ID not verified                              |
| Filing status             | candidate + withdrawn rosters            | candidate/office                   | Monitor through certification                  | Qualification states beyond withdrawal may need manual review |
| Party                     | candidate CSV + SOS political-party page | official party label               | Normalize to controlled vocabulary             | Minor/provisional status can change                           |
| Judicial retention        | judges PDF                               | court + judge                      | Per general election                           | PDF                                                           |
| Ballot measures           | initiative page/certification            | title + election                   | Monitor qualification → ballot → results       | Historical formats heterogeneous                              |
| Live results              | **unresolved**                           | —                                  | Do not ingest until official endpoint verified | Issue #180 / missing `results_url`                            |
| Certified results         | SOS Excel ZIP                            | contest + candidate + jurisdiction | Fetch after publication/canvass                | Workbook layouts may vary by year                             |
| Precinct results          | Excel/PDF + crosswalk                    | county + precinct code             | Same as certified results                      | State excludes local/county contests                          |
| Certification             | canvass PDF                              | election                           | Store once official board acts                 | PDF-only evidence                                             |
| Special elections         | results archive + notices                | date + affected office/district    | Event-driven                                   | Older archive may be incomplete                               |
| Recounts                  | election-specific SOS/county notices     | original election/contest          | Event-driven                                   | No centralized structured recount feed verified               |
| Campaign finance          | WYCFIS export                            | election cycle + filer             | Around filing deadlines + periodic refresh     | No API/HAR verified                                           |
| Historical archive        | SOS results index                        | year + election type               | Backfill oldest→newest                         | State result index currently reaches 1996                     |
| Local results             | county clerks                            | county + election + contest        | Separate county adapters                       | 23 decentralized sources                                      |

---

## 14. Corrections to the Original Research File

The following portions of the March 4 file should be changed:

| Original finding                                  | Updated finding                                                                                                                                                     |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| “Stage 2 — No adapter”                            | **Stale, and the intermediate fix was also wrong.** A `ClarityAdapter` subclass exists (`results/adapters/wy.py`), but no evidence supports Wyoming ever using Clarity; retire it in favor of a WY-native adapter against the SOS Excel-ZIP archive (issue #180). ([[GitHub](https://github.com/CivicMirror/CivicMirror-API/issues/180)][1])                        |
| Race creation depends on Google Civic             | **Replace as primary recommendation.** SOS candidate CSV, offices list and judges list provide first-party Stage 1 material. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/)][2])      |
| Excel (XLSX)                                      | **Narrow claim to “Microsoft Excel spreadsheets inside ZIP.”** XLSX extension was not independently verified. ([[Wyoming Secretary of State](https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx)][5])                     |
| “No district boundary files”                      | **Partially stale.** SOS supplies district/precinct reports and links official ArcGIS district experiences; downloadable GIS service/API remains unverified.        |
| “No candidate profiles”                           | **Refine.** No biography/profile system identified, but official candidate rosters contain significant candidate/filing metadata.                                   |
| Historical coverage unspecified                   | Official result index currently reaches **1996**, with primary/general and selected special elections. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/electionresults.aspx?utm_source=chatgpt.com)][7])                            |
| Ballot-measure coverage only from results         | SOS also has a dedicated initiative/referendum qualification, certification, full-text and historical system. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/initiativereferenduminfo.aspx)][9])                     |
| Campaign finance absent                           | WYCFIS is an official public database with contribution/expenditure/report search and text export. ([[Wyoming Campaign Finance](https://www.wycampaignfinance.gov/WYCFWebApplication/GSF_SystemConfiguration/PublicSearch.aspx?utm_source=chatgpt.com)][14])                                 |
| Third-party sources recommended to fill core gaps | For CivicMirror, first exhaust SOS candidate, results, initiative, GIS and WYCFIS sources plus county clerks. Third-party sources should not be primary provenance. |

---

## 15. PDF / Human-Review Queue

These official PDFs should be retained in source manifests even where a structured source exists:

| Document                                    | URL                                                                                                     | Purpose                                  | Extraction difficulty |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------- | --------------------- |
| 2025–2026 Election Calendar                 | `https://sos.wyo.gov/Elections/Docs/2026/2026_Election_Calendar.pdf`                                    | Dates/types/off-cycle schedule           | Medium                |
| 2026 Key Election Dates                     | `https://sos.wyo.gov/Elections/Docs/2026/2026_Key_Election_Dates.pdf`                                   | Primary/general + deadlines              | Low                   |
| 2026 Candidate Roster                       | `https://sos.wyo.gov/Elections/Docs/2026/2026_WY_Primary_Election_Candidates.pdf`                       | Candidate validation                     | Medium                |
| Withdrawn Candidates                        | `https://sos.wyo.gov/Elections/Docs/2026/2026_WY_Withdrawn_Primary_Election_Candidates.pdf`             | Filing-status changes                    | Low-medium            |
| Offices Up for Election                     | `https://sos.wyo.gov/Elections/Docs/2026/2026_Offices_Up_for_Election.pdf`                              | Contest completeness                     | Low                   |
| Judges Standing for Retention               | `https://sos.wyo.gov/Elections/Docs/2026/2026_Judges_Standing_for_Retention.pdf`                        | Retention contests                       | Low                   |
| Districts/Precincts by County               | `https://sos.wyo.gov/Elections/Docs/2026/2026_Districts_and_Precincts_by_County.pdf`                    | District crosswalk                       | Medium-high           |
| Districts/Precincts by Legislative District | `https://sos.wyo.gov/Elections/Docs/2026/2026_Districts_and_Precincts_by_Legislative_District.pdf`      | Reverse crosswalk                        | Medium-high           |
| 2026 Initiative Certification               | `https://sos.wyo.gov/Elections/Docs/Property_Tax_Initiative_Certificate.pdf`                            | Ballot qualification provenance          | Low                   |
| 2026 Initiative Full Text                   | `https://sos.wyo.gov/Elections/Docs/Peoples_Initiative_to_Limit_Property_Tax_in_Wyoming-Homeowners.pdf` | Official measure text                    | Medium                |
| Initiative/Referendum Summary               | `https://sos.wyo.gov/Elections/Docs/IRSum.pdf`                                                          | Historical measure qualification/results | Medium-high           |
| State Canvassing Board certification        | Election-specific result page                                                                           | Certified-result provenance              | Low                   |

---

## Source Coverage Analysis

Wyoming should no longer be treated as simply a **“PDF/Excel results-only”** state. The Secretary of State now provides enough first-party material to support most of CivicMirror's state-administered pipeline:

**Stage 1:** official calendar, offices, candidate CSV, withdrawals, judges and district mappings.
**Stage 2 certified:** official Excel bulk results plus precinct summaries and canvass certification.
**Ballot measures:** official qualification/status, certifications, text and historical summaries.
**Campaign finance:** public WYCFIS database with exports.
**Historical:** state result archive from 1996 through 2024 with selected special elections. ([[Wyoming Secretary of State](https://sos.wyo.gov/elections/)][2])

The remaining high-priority gap is **live/election-night 2026 results**. No evidence found in this research, or in follow-up MEDSL/Clarity-domain checks, supports Wyoming having ever used Clarity for ENR — retire the `ClarityAdapter` subclass rather than keep waiting on a URL for it. Until the Wyoming SOS or another first-party state election page publishes an actual live-results endpoint, treat live 2026 results as unresolved and monitor for one rather than guessing (issue #180). ([[GitHub](https://github.com/CivicMirror/CivicMirror-API/issues/180)][1])

For CivicMirror, the recommended order is therefore: **(1)** ingest the official candidate CSV for pre-election race/candidate creation; **(2)** build certified-result backfill around the SOS Excel ZIPs; **(3)** retain canvass PDFs as certification evidence; **(4)** map precincts through the official district reports; **(5)** use WYCFIS exports for campaign finance; and **(6)** separately monitor the SOS for publication of the actual 2026 election-night result endpoint rather than guessing a Clarity election ID.

[1]: https://github.com/CivicMirror/CivicMirror-API/issues/180 "AK & WY: results_url not set — Race Creation still unverified · Issue #180 · CivicMirror/CivicMirror-API · GitHub"
[2]: https://sos.wyo.gov/elections/ "Wyoming Secretary of State"
[3]: https://github.com/CivicMirror/CivicMirror-API/blob/main/docs/state-research/WY/WY-Election_Research.md "CivicMirror-API/docs/state-research/WY/WY-Election_Research.md at main · CivicMirror/CivicMirror-API · GitHub"
[4]: https://sos.wyo.gov/faqs.aspx?root=ELEC "Wyoming Secretary of State"
[5]: https://sos.wyo.gov/Elections/Docs/2024/2024GeneralResults.aspx "Wyoming Secretary of State | 2024 General Election Results"
[6]: https://sos.wyo.gov/Elections/LocalElections.aspx?utm_source=chatgpt.com "Local Elections"
[7]: https://sos.wyo.gov/elections/electionresults.aspx?utm_source=chatgpt.com "Election Results"
[8]: https://results.enr.clarityelections.com/WV/Wyoming/126264/web.345435/?utm_source=chatgpt.com "Election Night Reporting - SOE Software"
[9]: https://sos.wyo.gov/elections/initiativereferenduminfo.aspx "Wyoming Secretary of State"
[10]: https://sos.wyo.gov/Elections/Docs/IRSum.pdf "Initiative and Referendum Summary Sheet"
[11]: https://wyoleg.gov/InterimCommittee/2021/07-2021090222LSO-0093v0.4.pdf?utm_source=chatgpt.com "22LSO-0093 v0.4 Runoff elections."
[12]: https://www.wycampaignfinance.gov/WYCFWebApplication/GSF_Authentication/default.aspx/1000?utm_source=chatgpt.com "WYCFIS - Home"
[13]: https://www.wycampaignfinance.gov/wycfwebapplication/Docs/WY%20HTML%20FILES/PUBLIC%20HTML/public_search_contributions.htm?utm_source=chatgpt.com "Search Contributions"
[14]: https://www.wycampaignfinance.gov/WYCFWebApplication/GSF_SystemConfiguration/PublicSearch.aspx?utm_source=chatgpt.com "PublicSearch"
