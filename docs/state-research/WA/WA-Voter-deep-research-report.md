# VoteWA HAR Assessment for a Washington Results Adapter

## Executive summary

I parsed the attached HAR locally and the clearest conclusion is this: **the capture is from the `voter.votewa.gov` voter-portal login flow, not from Washington’s public election-results application.** In practical terms, that means the HAR does **not** expose a public, reusable election-results API or a public static results feed for races, candidates, counties, districts, precincts, or tabulation totals.

What it *does* expose is a small set of anonymous static JSON endpoints used to configure the VoteWA portal UI, plus client-side references to two personalized voter-data endpoints that appear to serve logged-in voter and ballot information. Those endpoints are organized around a voter identifier and are not appropriate targets for a public results adapter.

The more important architectural finding comes from the official Washington sources outside the HAR: the Secretary of State already separates the voter/candidate portal from the public results surface. The SOS election archive links `Results` to public results domains, `Data` to SOS-hosted election-data pages, and `Candidates Who Filed` to VoteWA. The legacy public results site exposes an `Export Results` page with statewide, county, and county-precinct CSV/XML exports, and SOS data pages also publish downloadable files such as reconciliation spreadsheets. That makes it reasonable to infer that a Washington adapter should target the public results and SOS download surfaces first, not the login portal captured in this HAR. citeturn2view0turn5view2turn6view0turn13view0turn14view0

The bottom line is therefore twofold. **From this HAR:** no reusable public results API was found. **For the broader Washington stack:** yes, there are still strong public adapter surfaces, but they live on the official results and data pages rather than inside this captured `portal2023/login.aspx` flow. citeturn2view0turn6view0

## What the HAR actually captured

After filtering out unrelated browser noise and third-party assets, the HAR shows a straightforward VoteWA portal boot sequence:

- a `302` redirect from `https://voter.votewa.gov/` to `https://voter.votewa.gov/portal2023/login.aspx`
- static CSS and JavaScript for the portal
- four anonymous `fetch` requests for static JSON configuration files
- one third-party `POST` to Google reCAPTCHA
- **no requests at all** to either public Washington results domain
- **no** WebSocket traffic
- **no** GraphQL requests
- **no** ZIP, XLSX, CSV, or XML downloads

That matters because the HAR lets us rule out the wrong surface. It is a login/session-oriented voter portal trace, not an election-results trace.

| HAR signal | Observation | Interpretation |
|---|---:|---|
| Total network entries | 50 | Small capture, easy to classify |
| Requests to `voter.votewa.gov` | 22 | The only VoteWA surface actually captured |
| Requests to `results.vote.wa.gov` or `results.votewa.gov` | 0 | No public results app activity in the HAR |
| VoteWA `fetch` JSON calls | 4 | Static config/i18n only |
| VoteWA XHR calls returning app data | 0 | No visible JSON results API |
| Third-party XHR calls | 1 | Google reCAPTCHA only |
| WebSocket calls | 0 | No push/live results channel observed |
| GraphQL calls | 0 | No GraphQL surface observed |
| ZIP/XLSX/CSV/XML downloads | 0 | No downloadable results artifacts in the HAR |

The HTML and JavaScript also show that the portal is built in a classic server-postback style rather than a modern results API style. The login page contains ASP.NET-style hidden fields such as `__VIEWSTATE`, `__EVENTVALIDATION`, `hdnVoterID`, `hdnElectionID`, `hdnBallotID`, `hdnServerAction`, and `hdnVIPCookie`, and the client JavaScript submits a form by setting `hdnServerAction` and calling `document.getElementById('vipForm').submit()`. That is not how public bulk election-results feeds are usually exposed.

Authentication-wise, the HAR is equally telling. No request to `voter.votewa.gov` carried cookies, bearer tokens, API keys, or session headers, and no captured VoteWA response set a cookie. The only token-like exchange was a Google reCAPTCHA reload request, which is an anti-bot mechanism and not a reusable application authorization channel.

| Authentication signal | Observed in HAR | Assessment |
|---|---|---|
| Cookies on VoteWA requests | No | No session established in the capture |
| `Set-Cookie` from VoteWA | No | Login had not progressed to an authenticated state |
| Bearer token / API key headers | No | No tokenized API surface visible |
| ASP.NET hidden state | Yes | Form-postback flow, not an obvious public API |
| Google reCAPTCHA POST | Yes | Ephemeral anti-bot exchange; not useful for adapter work |

One subtle but useful clue is the `hdnVIPCookie` bootstrap value embedded in the login page. In the captured page it resolves to an anonymous production-state object: locale `en`, voter flag `false`, environment `p`, and JSON mode `false`. That strongly reinforces that the capture never reached a logged-in or data-bearing state.

## Endpoint inventory

No pagination was observed anywhere in the HAR. The only dynamic parameters visible were locale, voter id, and IDs embedded in URLs returned by a static config file.

### HAR network inventory

| Endpoint pattern | Observed | Method | Data returned | IDs and params seen | Public or auth | Reusability for a results adapter | Recommended access | Confidence |
|---|---|---|---|---|---|---|---|---|
| `https://voter.votewa.gov/portal2023/login.aspx` | Yes | `GET` | HTML login page and hidden state fields | none on initial load | Public entrypoint | None for results; useful only to understand portal architecture | Browser or plain `GET` for inspection | High |
| `https://voter.votewa.gov/portal2023/json/links.json` | Yes | `GET` | Static URL registry | embedded `e=882`, `c=99` in `genericvotersguide` URL; no request params | Public | Low; useful as config and discovery of adjacent pages, not results | Direct `GET` | High |
| `https://voter.votewa.gov/portal2023/json/lang/locales.json` | Yes | `GET` | Static locale list | none | Public | None for results | Direct `GET` | High |
| `https://voter.votewa.gov/portal2023/json/lang/{locale}.json` | Yes | `GET` | UI translation bundle | path parameter `{locale}`; observed `en` | Public | None for results | Direct `GET` | High |
| `https://voter.votewa.gov/portal2023/json/sidebars.json` | Yes | `GET` | Static page/sidebar config | none | Public | Very low; useful for understanding portal scope only | Direct `GET` | High |
| `https://voter.votewa.gov/portal2023/json/counties.json` | No, but referenced in JS | `GET` | County metadata, inferred from client code | none | Likely public if exposed | Low to moderate; county office enrichment only | Direct `GET` if confirmed public | Medium |
| `https://voter.votewa.gov/portal2023/json/voters/{voter}.json` | No, but referenced in JS | `GET` | Personalized voter JSON file | path parameter `{voter}` | Should be treated as private/personalized | **Do not use** for public results | Avoid; out of scope | Medium-High |
| `https://voter.votewa.gov/portal2023/jsonhandler.ashx?v={voter}` | No, but referenced in JS | `GET` | Server-generated personalized voter JSON | query `v={voter}` | Should be treated as private/personalized | **Do not use** for public results | Avoid; out of scope | Medium-High |
| `https://www.google.com/recaptcha/api2/reload?k=<redacted>` | Yes | `POST` | reCAPTCHA challenge response | query `k=<site-key>` | Third-party anti-bot | None | Ignore for adapter | High |

The four anonymous JSON files that *were* captured all look like deployment artifacts rather than live data services. They returned `application/json`, shared the same `Last-Modified` timestamp, and had no evidence of live election query parameters, pagination, or contest identifiers.

A representative observed request and response from the HAR looked like this:

```http
GET /portal2023/json/links.json HTTP/2
Host: voter.votewa.gov
Accept: application/json
```

```json
{
  "contact_us": "https://www.sos.wa.gov/elections/contact-info",
  "elections_home": "https://www.sos.wa.gov/elections",
  "generic_voters_guide": "https://voter.votewa.gov/genericvoterguide.aspx?e=882&c=99",
  "voters_guide": "https://voter.votewa.gov/WhereToVoteDetail.aspx?ID=&part=&ptlPKID=&ptlhPKID=&tab=VotersGuide&returnurl=%2Fportal2023%2Flogin.aspx",
  "county_offices": "https://www.sos.wa.gov/elections/voters/voter-registration/county-elections-offices",
  "generic_voting_locations": "https://www.google.com/maps/d/u/0/edit?mid=..."
}
```

That response is useful because it confirms two things. First, the endpoint is public and anonymous. Second, it contains **links to adjacent public or semi-public pages**, but **not** race or results payloads.

The two most important unobserved-but-referenced endpoints are more significant for exclusion than for inclusion. The portal JavaScript contains a `getVoterData()` function that first tries a file path and then falls back to a handler endpoint:

```http
GET /portal2023/json/voters/{voter}.json HTTP/2
Host: voter.votewa.gov
Accept: application/json
```

```http
GET /portal2023/jsonhandler.ashx?v={voter} HTTP/2
Host: voter.votewa.gov
Accept: application/json
```

The client code references at least these fields on the resulting `voterData` object:

```json
{
  "ElectionID": 0,
  "ElectionName": "string",
  "ElectionType": "string",
  "ElectionDate": "string",
  "ElectionDateText": "string",
  "ElectionRegistrationDeadline": "string",
  "BallotSentDate": "string",
  "BallotReceivedDate": "string",
  "PrecinctID": 0,
  "CanPreverify": false,
  "NoticeCount": 0,
  "Status": "scalar"
}
```

That inferred schema is about **personalized ballot/voter state**, not public race reporting. It is exactly the sort of endpoint a results adapter should avoid.

### Public result surfaces confirmed from official Washington pages

Although the attached HAR never touched the public results infrastructure, the official SOS election archive clearly separates it from the voter portal. The archive page links `Results` to public results domains, `Data` to SOS election-data pages, and `Candidates Who Filed` to `voter.votewa.gov`. It also shows a domain split: 2026 special-election results link to the newer `results.votewa.gov` path, while 2025 and 2024 results still link to the legacy `results.vote.wa.gov` path. The public 2024 results page says results update as counties report and remain unofficial until certification, and its `Export Results` page lists CSV/XML exports for statewide, county, and “All County Precincts” data. SOS election-data pages separately publish downloadable files like reconciliation spreadsheets. citeturn2view0turn5view2turn6view0turn13view0turn14view0

| Official surface | Example pattern | Data type | IDs seen | Public or auth | Adapter value | Recommended access | Confidence |
|---|---|---|---|---|---|---|---|
| SOS election archive | `https://www.sos.wa.gov/.../election-results-and-voters-pamphlets` | Election index and discovery surface | dates like `20260428`, `20241105` | Public | Excellent seed list for elections and source URLs | Direct crawl | High |
| Legacy public results site | `https://results.vote.wa.gov/results/<YYYYMMDD>/` | Public HTML results pages | `20241105` | Public | Good for navigation and election metadata | Direct `GET`; parse HTML | High |
| Legacy export catalog | `https://results.vote.wa.gov/results/<YYYYMMDD>/export.html` | Public CSV/XML export directory | `20241105` | Public | **Best public surface found** for contest/county/precinct downloads | Direct file download | High |
| Newer public results route | `https://results.votewa.gov/results/public/washington/elections/<YYYYMMDD>` | Public results route/app shell | `20260428`, `20260210` | Public route | Promising, but internals unknown from this HAR | Capture a new HAR there first | Medium |
| Public candidate list | `https://voter.votewa.gov/CandidateList.aspx?e=<election_id>` | Public candidate-discovery HTML | `e=899` observed on current page | Public | Useful for candidate enrichment, not results | Direct `GET` or HTML parsing | High |

## What the official Washington sources show

The official SOS materials make the separation of concerns unusually clear. The VoteWA portal announcement describes VoteWA as a voter-facing portal with updated navigation and accessibility, and says it supports county election work such as managing voter registration data and issuing, tracking, and processing ballots. That aligns with what the HAR shows: a login portal concerned with voter lookup, reminders, ballot state, and county-office interactions rather than public race reporting. citeturn4view0

By contrast, the SOS election archive treats public results as a separate surface. For 2026 it points special-election `Results` to the newer public results route, while 2025 and 2024 results still point to the legacy public results domain. The same archive page points `Candidates Who Filed` at `voter.votewa.gov`, which is consistent with VoteWA hosting candidate and voter pages while election results live elsewhere. citeturn2view0turn3view1

The legacy 2024 public results pages are especially helpful for adapter planning. The 2024 public results page says results are updated as counties report tabulations and remain unofficial until certification. The linked export page then lists downloadable CSV/XML outputs for statewide contests, statewide measures, federal offices, state executive offices, legislative offices, judicial offices, all counties, and “All County Precincts (participating counties).” That is exactly the kind of public, reusable surface a results adapter can start with. citeturn5view2turn6view0

The SOS election-data pages provide another reliable path. On the 2026 April Special Election page, SOS exposes an “Other Files” section with a reconciliation XLSX, and the clicked file resolves to a direct downloadable spreadsheet URL. Even if the newer results route turns out to be JS-heavy or vendor-specific, these SOS-hosted data files provide a stable official fallback for imports and validation. citeturn13view0turn14view0

The data flow implied by the HAR and the official public pages looks like this:

```mermaid
flowchart LR
    A[Browser opens voter.votewa.gov] --> B[/portal2023/login.aspx]
    B --> C[/portal2023/json/links.json]
    B --> D[/portal2023/json/lang/locales.json]
    B --> E[/portal2023/json/lang/en.json]
    B --> F[/portal2023/json/sidebars.json]
    B --> G[Form postback login flow]
    G --> H[/portal2023/jsonhandler.ashx?v={voter} inferred]
    G --> I[/portal2023/json/voters/{voter}.json inferred]
    C --> J[Public generic voter guide URL]
    C --> K[County office and other helper URLs]

    L[SOS election archive] --> M[Legacy public results site]
    L --> N[Newer public results route]
    L --> O[SOS election data pages]
    M --> P[Export Results CSV/XML]
    O --> Q[Reconciliation XLSX and related files]
```

That flowchart highlights the central finding: the captured portal and the public results stack are adjacent systems, not the same system.

## Adapter recommendations

My assessment is:

**Public reusable election-results API in the attached HAR:** **No evidence found.**  
**Public reusable static results data in the attached HAR:** **No evidence found.**  
**Public reusable official results/download surfaces outside the HAR:** **Yes, strongly confirmed.** citeturn2view0turn6view0turn13view0

For implementation purposes, the most defensible architecture is a two-track approach.

The first track should be a **public-download adapter** built around the legacy public results export pages and SOS-hosted election-data files. The official archive page already enumerates elections, the legacy results site exposes an export catalog with statewide, county, and precinct-oriented files, and SOS data pages publish reconciliation spreadsheets. That is enough to support a reliable initial Washington adapter without depending on undocumented portal internals. citeturn2view0turn6view0turn13view0turn14view0

The second track should be a **discovery pass for the newer 2026 results route**. Because the attached HAR never touched that domain, there is not enough evidence yet to say whether it exposes public reusable JSON calls, static JSON bundles, or only a browser-rendered shell over additional endpoints. The correct next step is not to reverse-engineer the voter portal further; it is to capture a separate HAR from the public 2026 results route itself and inspect its XHR/fetch traffic. The newer route pattern is official and public, but its internal mechanics remain unverified here. citeturn2view0

Just as important, the two personalized portal endpoints discovered in JavaScript should stay **out of scope**. They appear to serve voter-specific election and ballot state and are keyed by voter id. Even if they were technically reachable, they would be the wrong surface for a public results adapter and a poor fit for sustainable ingestion.

If I had to rank the candidate access methods right now, it would be:

1. **Direct file download** from official results export pages and SOS data files.  
2. **Direct HTML parsing** of official public results and candidate pages where needed.  
3. **Headless browser or fresh HAR capture** only for the newer 2026 public results route, and only until its public XHR/static asset model is understood.

## Sample probes and code

The first step should be to verify the **public** surfaces, not to probe the personalized voter endpoints. The following examples are therefore limited to anonymous endpoints or official public pages.

These `curl` probes fetch public static endpoints that were truly present in the HAR:

```bash
curl -L 'https://voter.votewa.gov/portal2023/json/links.json'
curl -L 'https://voter.votewa.gov/portal2023/json/lang/locales.json'
curl -L 'https://voter.votewa.gov/portal2023/json/lang/en.json'
curl -L 'https://voter.votewa.gov/portal2023/json/sidebars.json'
```

These fetch official public pages that are more relevant to a results adapter:

```bash
curl -L 'https://results.vote.wa.gov/results/20241105/'
curl -L 'https://results.vote.wa.gov/results/20241105/export.html'
curl -L 'https://voter.votewa.gov/CandidateList.aspx?e=899'
```

And this downloads an SOS-hosted spreadsheet file exposed from the official 2026 April Special Election data page:

```bash
curl -L 'https://www.sos.wa.gov/sites/default/files/2026-05/2026%20April%20Special%20Reconciliation.xlsx' \
  -o wa_20260428_reconciliation.xlsx
```

That spreadsheet URL is not guessed; it is exposed by the official SOS 2026 April Special Election page when the reconciliation file link is followed. citeturn13view0turn14view0

A small Python probe for public pages and exports can look like this:

```python
import requests
import urllib.parse
from bs4 import BeautifulSoup

def fetch_text(url: str) -> str:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text

def enumerate_export_links(election_date: str = "20241105") -> list[str]:
    url = f"https://results.vote.wa.gov/results/{election_date}/export.html"
    html = fetch_text(url)
    soup = BeautifulSoup(html, "html.parser")

    links = set()
    for a in soup.select("a[href]"):
        href = urllib.parse.urljoin(url, a["href"])
        links.add(href)

    return sorted(links)

def fetch_vote_wa_static_config() -> dict:
    config_urls = {
        "links": "https://voter.votewa.gov/portal2023/json/links.json",
        "locales": "https://voter.votewa.gov/portal2023/json/lang/locales.json",
        "english_bundle": "https://voter.votewa.gov/portal2023/json/lang/en.json",
        "sidebars": "https://voter.votewa.gov/portal2023/json/sidebars.json",
    }

    out = {}
    for name, url in config_urls.items():
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        out[name] = resp.json()
    return out

if __name__ == "__main__":
    # Public, observed-in-HAR config endpoints
    static_cfg = fetch_vote_wa_static_config()
    print("Config keys:", static_cfg["links"].keys())

    # Public results export page
    export_links = enumerate_export_links("20241105")
    for link in export_links:
        if any(tag in link.lower() for tag in (".csv", ".xml", "export", "results")):
            print(link)
```

If you want a more targeted next capture plan, the highest-value next steps are these:

- Capture a HAR from the **public 2026 results route** while clicking statewide, county, race, and precinct views.
- Capture a second HAR from the **legacy 2024 or 2025 export/results site** while clicking export links and county pages.
- Try unauthenticated `curl` or `requests` calls against the public results/export pages and SOS-hosted spreadsheet URLs before building any browser automation.
- Use the public candidate list separately for candidate enrichment, because it is on VoteWA but distinct from results. citeturn3view1turn6view0

The rigorous conclusion, then, is not “VoteWA has no reusable data.” It is narrower and more actionable: **this specific HAR does not expose a public reusable results API, but the official Washington public results and SOS data surfaces very likely provide enough public structure to build a baseline Washington results adapter without relying on the captured login portal.** citeturn2view0turn5view2turn6view0turn13view0