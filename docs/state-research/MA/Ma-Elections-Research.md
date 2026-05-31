# Massachusetts PD43+ Election Results — Research Notes

**Site:** https://electionstats.state.ma.us  
**Operated by:** Massachusetts Secretary of the Commonwealth  
**Platform vendor:** ElectionStats / PD43+ (same vendor operates sites for ~10 U.S. states)  
**Researched:** March 4, 2026  
**Status:** Public, no authentication required

---

## Overview

Unlike the Texas GoElect portal (which is an Angular SPA backed by a REST API), the Massachusetts site is a traditional **server-rendered HTML application**. There is no hidden JSON/REST API — all data is delivered as rendered HTML tables or downloadable CSV files. The platform is branded "PD43+" (Public Document 43+), a reference to the official Massachusetts election results publication.

The site covers:
- **Elections** (candidates, vote counts) from 1970 through present
- **Ballot questions** from 1972 through present  
- **Candidate profiles** with cross-election history

Data granularity goes down to individual precincts. All 351 Massachusetts municipalities are represented.

---

## Architecture

The site uses a **path-segment filter pattern** rather than query strings. All filter parameters are embedded as colon-separated key:value pairs in the URL path itself. For example:

```
/elections/search/year_from:2024/year_to:2024/stage:General
/elections/view/165304/filter_by_county:Middlesex
/elections/download/165304/precincts_include:0/
```

This is consistent across elections, ballot questions, and candidates. There are no `?param=value` query strings on any known endpoint.

---

## Endpoint Reference

### Elections

#### Search / Browse
```
GET /elections/search
GET /elections/search/year_from:YYYY/year_to:YYYY
GET /elections/search/year_from:YYYY/year_to:YYYY/stage:General
```

**Available `stage:` values:**
- `General` — all general elections
- `Primary` — all primaries (all parties combined)
- `Democratic+Primaries` — Democratic primaries only
- `Republican+Primaries` — Republican primaries only
- `Green-Rainbow+Primaries`, `Libertarian+Primaries`, etc.

The search page returns an HTML table of all matching elections with summary vote counts inline. The full list of available election years spans 1970–2026, with some years absent (no elections held or data not digitized).

---

#### Election Detail
```
GET /elections/view/{election_id}/
GET /elections/view/{election_id}/filter_by_county:{CountyName}
```

Returns an HTML table with county-level vote totals per candidate. When a county filter is applied, rows expand to show city/town breakdown within that county, with "More »" expand links for precinct-level detail (those are JavaScript-driven and require the download endpoint to get the full data).

**County names (14 total):**
Barnstable, Berkshire, Bristol, Dukes, Essex, Franklin, Hampden, Hampshire, Middlesex, Nantucket, Norfolk, Plymouth, Suffolk, Worcester

**Example — 2024 U.S. Senate General Election:**
```
GET /elections/view/165304/
```
Returns statewide county breakdown: Warren 2,041,668 (59.8%) vs. Deaton 1,365,440 (40.0%).

---

#### Download (CSV)
```
GET /elections/download/{election_id}/precincts_include:0/
GET /elections/download/{election_id}/precincts_include:1/
```

| Parameter | Data Returned |
|-----------|---------------|
| `precincts_include:0` | Municipality-level results (one row per city/town) |
| `precincts_include:1` | Precinct-level results (one row per ward/precinct) |

**Response:** Returns `Content-Type: text/csv;charset=UTF-8` directly — no base64, no wrapping envelope. The file downloads immediately.

**CSV column structure:**
```
Locality, Ward, Pct, [Candidate 1 Name], [Candidate 2 Name], ..., All Others, Blanks, Total Votes Cast
```

Ward and Pct columns are blank for municipality-level downloads. For precinct downloads they contain the ward number and precinct number respectively.

**Example rows (2024 Senate, municipality-level):**
```csv
Locality,Ward,Pct,Elizabeth Ann Warren,John Deaton,All Others,Blanks,Total Votes Cast
Acton,,,8643,2878,77,251,11849
Adams,,,1837,1437,22,178,3474
...
TOTALS,,,2041668,1365440,6221,99601,3512930
```

Note: Numbers with commas are quoted (e.g., `"2,041,668"`). The TOTALS row always appears at the bottom.

---

#### Election ID Structure

Election IDs are sequential integers assigned at time of data import. Observed ranges:

| Era | Approximate ID Range | Example |
|-----|---------------------|---------|
| 2006–2010 | ~80000s–100000s | — |
| 2008 | ~105767 | 2008 Democratic Presidential Primary |
| 2016 | ~126695–131805 | 2016 elections |
| 2020 | ~140911 | 2020 State Senate special |
| 2022 | ~154333–154393 | 2022 General elections |
| 2024 | ~160657–165516 | 2024 elections |
| 2026 (special) | ~171919–171920 | 2026 1st Middlesex special |

IDs are not densely sequential — gaps exist between individual elections within the same cycle. The best way to enumerate all elections is via the search page.

---

### Ballot Questions

#### Search
```
GET /ballot_questions/search
GET /ballot_questions/search/year_from:YYYY/year_to:YYYY
```

Optional additional path filters (can be combined):
- `/type:{TypeName}` — e.g., `Initiative+Petition`, `Constitutional+Amendment`, `Public+Policy+(Non-Binding)`, `Local+Question`, `County+Question`, `Referendum+(Repeal)`
- `/locality:{CityOrTown}` — filter to one municipality
- `/county:{CountyName}` — filter by county

Available years: 1972, 1974, 1976, 1978, 1980, 1982, 1984, 1986, 1988, 1990, 1992, 1994, 1996, 1998, 2000, 2002, 2004, 2006, 2008, 2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024.

The search result page renders each question with a summary and the statewide Yes/No result inline.

---

#### Ballot Question Detail
```
GET /ballot_questions/view/{question_id}/
```

Shows full question text, Yes/No vote counts, and a breakdown by locality. IDs are sequential integers (observed range: ~5961 for older questions through ~11661 for 2024).

---

#### Download (CSV)
```
GET /ballot_questions/download/{question_id}/precincts_include:0/
GET /ballot_questions/download/{question_id}/precincts_include:1/
```

Same `precincts_include` flag as elections. Returns CSV directly.

**CSV column structure:**
```
Locality, , , Yes, No, Blanks, Total Votes Cast
```

The two blank columns after Locality appear to be Ward/Pct placeholders (matching the elections format). For precinct-level downloads, these are populated.

**Example rows (ballot question 5961, Berkshire/Hampshire district):**
```csv
Locality,,,Yes,No,Blanks,"Total Votes Cast"
Ashfield,,,814,70,88,972
Dalton,,,"2,499",359,517,"3,375"
...
TOTALS,,,"14,417","1,936","2,812","19,165"
```

---

### Candidates

#### Search
```
GET /candidates/search
```

Returns a search interface. Candidate search appears to work primarily through election search — individual candidate pages are accessed via direct slug URL.

---

#### Candidate Profile
```
GET /candidates/view/{Slug}
```

Where `{Slug}` is the candidate's full name hyphenated: `First-Middle-Last`. Special characters are handled as follows:
- Spaces → hyphens
- Apostrophes → removed (e.g., `L'Italien` → `LItalien`)
- Periods → removed (e.g., `Jr.` → `Jr`)
- Commas → removed

**Example:**
```
GET /candidates/view/Elizabeth-Ann-Warren
GET /candidates/view/Lori-Loureiro-Trahan
GET /candidates/view/Barbara-A-LItalien
```

**Profile page shows:**
- Win/loss record (general elections, primaries, total)
- List of opponents in each race with links to those candidates
- Full historical election results table (same format as the search page)
- Links to individual election detail pages

---

## Data Coverage

### Elections
The site covers elections from **1970 through present** with the following caveats:
- Not all election years are present (some older special elections may be missing)
- Election-level granularity appears consistent back to 1970
- Precinct-level data availability for older elections is unconfirmed and may vary

### Ballot Questions
Coverage begins at **1972**. Question types include:
- Constitutional Amendments
- Initiative Petitions  
- Referenda (Repeal)
- Public Policy Questions (Non-Binding) — advisory questions placed on ballots by legislative districts, very common in recent cycles
- Local Questions — city/town-specific questions (tax overrides, bonds, etc.)
- County Questions

### Candidate Data
Candidate profiles are available for any candidate who appeared on a ballot in the database. Some very old elections may only have aggregate data without individual candidate slug pages.

---

## Search Filter Syntax Summary

All filters are path segments in `key:value` format, URL-encoded for spaces (space → `+`):

| Filter | Example | Applies To |
|--------|---------|------------|
| `year_from:YYYY` | `year_from:2020` | Elections, Ballot Questions |
| `year_to:YYYY` | `year_to:2024` | Elections, Ballot Questions |
| `stage:Value` | `stage:General` | Elections |
| `filter_by_county:Name` | `filter_by_county:Middlesex` | Election detail view |
| `precincts_include:0` | `precincts_include:0` | Download (municipality) |
| `precincts_include:1` | `precincts_include:1` | Download (precinct) |
| `type:Value` | `type:Local+Question` | Ballot Questions |
| `locality:Name` | `locality:Boston` | Ballot Questions |
| `county:Name` | `county:Suffolk+County` | Ballot Questions |

---

## Comparison: MA vs. TX

| Feature | Massachusetts (PD43+) | Texas (GoElect EVR) |
|---------|----------------------|---------------------|
| Architecture | Server-rendered HTML + CSV downloads | Angular SPA + REST API |
| Data format | Direct CSV download | Base64-encoded JSON/CSV |
| Authentication | None | None |
| Data access | HTML scrape or CSV download | Clean REST API calls |
| Historical depth | 1970–present | ~2025–present (EVR system) |
| Geographic granularity | Precinct | County only (individual voter list for statewide) |
| Individual voter data | Not available | Yes (statewide voter list by date) |
| Programmatic access | CSS/regex scraping for search; direct CSV for details | Structured API, no scraping needed |
| Ballot questions | Yes (1972–present) | No |
| Candidate profiles | Yes | No |

---

## Scraping Approach

Since there is no REST API, programmatic access requires two techniques:

**For enumerating elections (discovery):** Fetch the search page and parse the HTML table. Each row contains the election name, year, office, stage, and a link to the detail page with its ID embedded in the URL path. A regex like `/elections/view/(\d+)/` against the page HTML will extract all IDs.

**For downloading results (bulk data):** Once you have an election ID, construct the CSV download URL directly — no need to parse HTML at all:

```python
import requests

def download_election_csv(election_id, precinct_level=False):
    """Download election results as CSV."""
    precincts = 1 if precinct_level else 0
    url = f"https://electionstats.state.ma.us/elections/download/{election_id}/precincts_include:{precincts}/"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text  # already plain CSV

def download_ballot_question_csv(question_id, precinct_level=False):
    """Download ballot question results as CSV."""
    precincts = 1 if precinct_level else 0
    url = f"https://electionstats.state.ma.us/ballot_questions/download/{question_id}/precincts_include:{precincts}/"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text

def get_election_detail_html(election_id, county=None):
    """Get the HTML detail page, optionally filtered by county."""
    if county:
        url = f"https://electionstats.state.ma.us/elections/view/{election_id}/filter_by_county:{county}"
    else:
        url = f"https://electionstats.state.ma.us/elections/view/{election_id}/"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text
```

**Rate limiting:** No rate limiting was observed during testing. The site appears to be simple file serving with no bot protection. Standard polite crawling (0.5–1 second between requests) is recommended.

**Parsing notes:**
- Vote count columns use quoted commas for thousands separators (e.g., `"2,041,668"`) — use Python's `csv` module, not simple split
- The TOTALS row at the bottom of each CSV is a summary row, not a locality
- Precinct CSV has Ward and Pct columns populated; municipality CSV has them blank

---

## File Sizes

| Data Type | Approx. Size |
|-----------|-------------|
| Election search results page (HTML) | ~100–500 KB depending on year range |
| Election detail page (HTML, statewide) | ~50–100 KB |
| Municipality-level CSV | ~15–80 KB depending on office scope |
| Precinct-level CSV | ~150–800 KB for statewide offices |
| Ballot question detail CSV | ~5–30 KB |