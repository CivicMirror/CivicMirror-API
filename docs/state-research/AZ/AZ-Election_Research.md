# Arizona Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ **Direct from source** | Hard-code July 21, 2026 from AZSOS calendar; no Google Civic dependency |
| Stage 1 — Race Creation | ✅ **Open HTML scrape** | **AZ Clean Elections `CandidateList`** — no auth, no bot wall, all races + candidates live now |
| Stage 1 — Candidate Detail | ✅ **Open HTML scrape** | **AZ Clean Elections `CandidateDetail`** — bio, party, website, social, funding type per candidate ID |
| Stage 2 — Results Ingestion | ✅ **Open XML Feed** | **AZSOS HTTPS/FTP XML** — public, no auth, official data. Publishes election night. |

---

**Site:** https://azsos.gov/elections  
**Results Feed:** `https://apps.azsos.gov/ftp/ElectionResults/{year}/State/{ElectionName}/Results.Summary.xml`  
**Candidate List:** `https://www.azcleanelections.gov/Custom/CandidateList`  
**Candidate Detail:** `https://www.azcleanelections.gov/Custom/CandidateDetail/?id={id}`  
**Operated by:** Arizona Secretary of State (results) / AZ Citizens Clean Elections Commission (candidate data)  
**Researched:** March 4, 2026  
**Updated:** June 2, 2026 — Stage 1 fully resolved via AZ Clean Elections; Google Civic dependency eliminated; complete race + candidate dataset confirmed live  
**Status:** Public, no authentication required (both sources)

---

## Stage 1 — Election + Race Creation (RESOLVED, no Google Civic needed)

### Election Date — Hard-code from AZSOS calendar

Google Civic API does not yet have the July 21 primary (normal for 7 weeks out). **Do not wait for it.** Seed the election record directly:

| Election | Date | Source |
|---|---|---|
| 2026 Primary Election | **2026-07-21** | AZSOS (HB2022, signed 2026-02-06) |
| 2026 General Election | **2026-11-03** | AZSOS |

The primary date was changed from "first Tuesday in August" to "second-to-last Tuesday in July" by legislation signed February 6, 2026.

---

### Race + Candidate Data — AZ Clean Elections `CandidateList` (live now)

**URL:** `https://www.azcleanelections.gov/Custom/CandidateList`  
**Method:** GET, no params, no auth, no Cloudflare gate  
**Response:** HTML fragment (server-rendered, no JS required)  
**Update cadence:** Reflects current filed candidates; updates as filings close

#### What it returns

317 candidates across 118 races in 7 categories:

| Category (`secBL{id}`) | Races | Candidates | Notes |
|---|---|---|---|
| FEDERAL - LEGISLATIVE (`1`) | 9 | 37 | All 9 U.S. House districts |
| STATE - EXECUTIVE (`2`) | 7 | 29 | Governor, SoS, AG, Mine Inspector, Treasurer, Supt. of Public Instruction, Corporation Commissioner |
| STATE - LEGISLATIVE (`3`) | 60 | 187 | All 30 Senate + 60 House districts (2 seats each) |
| COUNTY (`4`) | 8 | 10 | County supervisors/officers |
| COUNTY - JUDICIAL (`5`) | 2 | 2 | Local judicial races |
| COUNTY - LEGISLATIVE (`6`) | 19 | 22 | County board races |
| CITY - LEGISLATIVE (`7`) | 13 | 30 | City council races |

**Note:** No statewide U.S. Senate race in 2026 for Arizona. No statewide judicial races in this dataset.

#### HTML structure

```html
<!-- Branch heading -->
<h3 class="branch">STATE - EXECUTIVE</h3>
<section>
  <h3>Governor</h3>
  <ul class="people">
    <li>
      <img class="pic" src="/Custom/Picture/2343" />
      <img class="viewmore" onclick="myPopup.ViewCand(5577);" />
      <div>
        <b>Katie Hobbs</b>
        <span class="office">Governor</span>
        <span class="party">Democratic</span>
      </div>
    </li>
    ...
  </ul>
</section>
```

#### Key parsing rules

- **Candidate ID:** extract integer from `ViewCand({id})` onclick — this is your foreign key into `CandidateDetail`
- **Name:** content of `<b>` tag; may contain HTML entities (`&#225;`, `&quot;`) → unescape
- **Write-in flag:** name ends with `(Write-In)` — strip suffix and set `isWriteIn=true`
- **Office:** `<span class="office">` — same as race name from `<h3>` heading
- **Party:** `<span class="party">` — values include: `Democratic`, `Republican`, `Libertarian`, `Green`, `No Labels`, `Non-partisan`
- **Race grouping:** `<section id="secBL{1-7}">` → category; `<h3>` within → race name

#### Sample 2026 statewide races

| Race | Candidates | Parties |
|---|---|---|
| Governor | Andy Biggs, David Schweikert, Katie Hobbs, Ken Miceli, Scott Neely + 3 others | R×4, D×1, No Labels×2, Green×1 |
| Attorney General | Kris Mayes, Rodney Glassman, Warren Petersen | D×1, R×2 |
| Secretary of State | Adrian Fontes, Alexander Kolodin, Gina Swoboda, Duwayne Collier | D×1, R×2, Green×1 |
| Corporation Commissioner | 5 candidates | D×2, R×3 |
| U.S. House Dist. 1 | 8 candidates | D×4, R×3, Libertarian×1 |

---

### Candidate Detail — `CandidateDetail` endpoint

**URL:** `https://www.azcleanelections.gov/Custom/CandidateDetail/?id={candidateId}`  
**Method:** GET, single integer param  
**Response:** HTML `<article>` fragment  
**Gate:** None — open, server-side accessible

#### What it returns (per candidate)

- Full name + photo URL (`/Custom/Picture/{picId}`)
- Office + party + funding type (`Traditional Funding` vs `Clean Elections`)
- Campaign website URL
- Donation URL
- Social media links (Facebook, X/Twitter, YouTube, Instagram)
- Biography paragraph
- Campaign statement paragraph
- Debate video link (if available)

#### Sample response structure

```html
<article class="person">
  <figure><img src="/custom/Picture/2343" alt="Katie Hobbs"></figure>
  <h4>Katie Hobbs</h4>
  <p>
    Governor<br />
    Democratic<br />
    Traditional Funding
  </p>
  <p>Website: <a href="https://katiehobbs.org/">katiehobbs.org/</a></p>
  <p>Donations: <a href="http://katiehobbs.org/donate">...</a></p>
  <p class="social">
    <a href="https://www.facebook.com/hobbskatie">...</a>
    <a href="https://x.com/katiehobbs">...</a>
    <a href="https://youtube.com/@katiehobbsaz">...</a>
  </p>
  <p>{biography}</p>
  <p><b>Statement</b><br />{campaign statement}</p>
</article>
```

#### Parsing notes

- **Funding type:** `Traditional Funding` = privately funded; `Clean Elections` = publicly funded via CCEC program — useful metadata
- **Social:** `fa-facebook-f` → Facebook, `fa-x-twitter` → X/Twitter, `fa-youtube` → YouTube, `fa-instagram` → Instagram
- **Photo:** `/Custom/Picture/{picId}` — some candidates have no photo (`/Custom/Picture/0`)
- **Not all candidates have bios/statements** — handle missing `<p>` gracefully

---

## Recommended Stage 1 Adapter — CivicMirror

```
1. Seed election:
   INSERT election(name="2026 Arizona Primary", date=2026-07-21, state="AZ")

2. GET https://www.azcleanelections.gov/Custom/CandidateList
   → Parse HTML → extract races + candidates
   → For each <h3> race heading: upsert Race(name, category from secBL id, election_id)
   → For each <li> candidate: upsert Candidate(name, party, isWriteIn, candidateId, race_id)

3. For each candidate: GET /Custom/CandidateDetail/?id={candidateId}
   → Upsert candidate bio, website, social links, funding_type
   → Rate-limit: 317 candidates; 1 req/sec = ~5 min total; no bot wall observed

4. Repeat step 2 periodically (weekly until election) — late filings and withdrawals update the list
```

**No Google Civic API needed for Stage 1.**

---

## Stage 2 — Results Ingestion (election night, July 21)

### AZSOS HTTPS XML Feed

**URL:** `https://apps.azsos.gov/ftp/ElectionResults/2026/State/2026 Primary Election/Results.Summary.xml`  
(URL-encode space as `%20`)  
**Available:** 8:00 PM election night; returns HTTP 404 until then  
**Auth:** None  
**Rate limit:** Poll max once per 2 minutes during active reporting

#### XML Schema (verified from 2024 Primary + 2025 Special General production data)

```xml
<electionResult>
  <electionInformation>
    <resultsTimestamp>2026-07-21T20:15:00.000</resultsTimestamp>
    <electionName>2026 Primary Election</electionName>
    <electionDate>2026-07-21</electionDate>
    <fileId>12500</fileId>   <!-- increments each publish — use for change detection -->
  </electionInformation>

  <voterTurnout>
    <jurisdictions>
      <jurisdiction key="0" name="State"
        totalVoters="..." ballotsCast="..."
        precinctsParticipating="..." precinctsReported="..."
        precinctsReportingPercent="..."
        earlyBallotsRemaining="0" provisionalBallotsRemaining="0" />
      <!-- key 1–15 = individual counties -->
    </jurisdictions>
  </voterTurnout>

  <contests>
    <contest key="{id}"
      contestLongName="Governor (DEM)"   <!-- party suffix encoded in name -->
      districtKey="{id}" districtName="Statewide"
      numberToElect="1" termYears="4"
      isQuestion="false"
      precinctsReportingPercent="100.00">
      <choices>
        <choice key="{id}" choiceName="Hobbs, Katie"
          partyKey="3" party="DEM"
          totalVotes="..." isWriteIn="false">
          <jurisdictions>
            <jurisdiction key="0" name="State" votes="...">
              <voteTypes>
                <voteType voteTypeName="Polling Place" votes="..." />
                <voteType voteTypeName="Early Ballots" votes="..." />
                <voteType voteTypeName="Provisional Ballots" votes="..." />
              </voteTypes>
            </jurisdiction>
            <!-- per-county jurisdictions key 1–15 -->
          </jurisdictions>
        </choice>
      </choices>
    </contest>
  </contests>
</electionResult>
```

#### District name values (2024 Primary verified — 142 contests)

| `districtName` | Race type |
|---|---|
| `Federal Statewide` | U.S. Senator |
| `Congressional District 1`–`9` | U.S. Representative |
| `Statewide` | Governor, AG, SoS, Corporation Commissioner, etc. |
| `Legislative District 1`–`30` | State Senator, State Representative |

#### Key parsing notes

- **Party in contest name:** `contestLongName` encodes party (e.g. `"Governor (DEM)"`, `"Governor (REP)"`) — strip suffix to get base race name; normalize to your party model
- **No `isOfficial` certified flag** — the feed is unofficial ENR only; certified results published separately by AZSOS ~3 weeks post-election
- **`fileId` for change detection:** poll, compare `fileId`; skip parse if unchanged
- **100% signal:** `precinctsReportingPercent="100.00"` on the contest node

---

## Data Model Mapping

| Source | Field | CivicMirror model |
|---|---|---|
| Hard-coded / AZSOS calendar | election date, name | **election** |
| `CandidateList` `<h3>` race heading | race name | **race** |
| `CandidateList` `secBL{id}` | FEDERAL/STATE/COUNTY/CITY category | race grouping |
| `CandidateList` `<span class="party">` | Democratic/Republican/etc. | party |
| `CandidateList` `ViewCand({id})` | candidate external ID | candidate (FK to Detail) |
| `CandidateDetail` bio + statement | biography text | candidate profile |
| `CandidateDetail` website/social | links | candidate contact |
| `CandidateDetail` funding type | Traditional / Clean Elections | candidate metadata |
| XML `electionDate`, `electionName` | cross-check / confirm | election |
| XML `contestLongName` (stripped) | race name (results side) | race match |
| XML `districtName` | district grouping | race district |
| XML `choiceName`, `party`, `isWriteIn` | result choice | candidate / choice |
| XML `totalVotes` at `key="0"` (State) | statewide tally | result row |
| XML per-county `jurisdiction` | county breakdown | sub-jurisdiction result |
| XML ballot type `voteType` | Polling/Early/Provisional | ballot type breakdown |
| XML `fileId` | change detection | ingestion dedupe |

---

## Source Coverage Analysis

**Stage 1 is now fully resolved without Google Civic API dependency.** Two open, unauthenticated endpoints on `azcleanelections.gov` provide everything needed right now:

`Custom/CandidateList` returns all 317 candidates across 118 races for the July 21, 2026 primary — federal, state executive, all 90 legislative races, county, and city — with name, party, office, write-in flag, and a candidate ID. `Custom/CandidateDetail/?id={id}` returns bio, campaign statement, website, social links, and funding type for each candidate individually. Both endpoints are server-side accessible (no Cloudflare, no JS required). Neither is documented publicly — they were reverse-engineered from the `azcleanelections.gov` JavaScript.

**Stage 2** uses the AZSOS HTTPS XML feed, verified from 2024 and 2025 production data, publishing at 8:00 PM on election night at a predictable URL.

The `apps.arizona.vote/electioninfo` portal and `azsos.gov` itself remain Cloudflare-gated and are not viable for server-side automation. They are not needed.

**Supplemental sources** (Ballotpedia, Google Civic) remain useful for ballot measure full text, incumbency flags, and district boundary GeoJSON — but are no longer blockers for Stage 1.