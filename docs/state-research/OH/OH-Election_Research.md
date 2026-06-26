# Ohio Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | DATA Act + live dashboard (own system) — no adapter built |

---

**Site:** https://www.ohiosos.gov/elections/election-results-and-data/
**Data Dashboard:** https://www.ohiosos.gov/elections/voters/ohio-election-results-data/
**DATA Act Portal:** https://data.ohiosos.gov/voter
**Live Results:** https://liveresults.ohiosos.gov
**Operated by:** Ohio Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Ohio has one of the most advanced election data transparency systems in the nation, anchored by the first-in-the-nation **Data Analysis Transparency Archive (DATA) Act** passed in 2023. The Office of Data Analytics and Archives provides detailed data tools for absentee/early voting trends, historical results, voter registration, and daily voter roll snapshots.

---

## Data Access

### Election Results Data Dashboard
- Custom-built interactive dashboard
- County-level data from 88 county boards since 2016 Primary
- Updated after official certification
- Best on desktop

### Live Election Night Results
- **URL:** https://liveresults.ohiosos.gov
- Real-time unofficial results on election night

### Official Election Results (XLSX Downloads)
- Summary-level and precinct-level results as XLSX files
- Organized by race and party
- Includes voter registration and turnout data
- Available for each election cycle

### DATA Act — Daily Voter Registration Snapshots
- **URL:** https://data.ohiosos.gov/voter
- Daily snapshots of voter registration database from all 88 counties
- Search by date and county
- Raw, unmodified data as transmitted by county boards
- 60,000+ county files, several terabytes total
- Bulk download available for large searches
- Contact: data@ohiosos.gov

### Election Results Data Dashboard (Additional)
- Absentee/early voting tracking tools
- Historical election results analysis

---

## API Access

No traditional REST API, but the DATA Act portal provides:
1. Searchable file access for daily voter registration snapshots
2. Bulk download capability
3. XLSX downloads for all official election results

---

## Notes

- 88 county boards of elections (fully decentralized system)
- DATA Act (2023) is landmark transparency legislation
- Daily voter registration snapshots created at 4 PM, transmitted by 11:59 PM
- Ohio is one of 8 states with fully decentralized election administration
- Precinct-level data available as XLSX
- 8+ million voter records in system
---

## Source Coverage Analysis

Ohio's SOS provides a dedicated DATA Act transparency portal, precinct-level XLSX downloads, a live election night dashboard (`liveresults.ohiosos.gov`), and access to voter registration data — making it one of the more complete state sources in this batch for live results and historical election data. However, ballot measures are not clearly documented as a structured data category (they may be embedded in the XLSX under "Issues"), pre-2016 precinct data is inconsistent, and candidate biographical/contact data, platform statements, official/incumbent records, and GeoJSON district boundaries are absent. Supplement with **Google Civic Information API** (candidates, districts, official incumbency), **Ballotpedia** (ballot measures, candidate bios, and incumbency confirmation), **OpenStates** (Ohio state legislative data), and **OpenFEC** (federal candidates and campaign finance).

---

# HAR Analysis Update — June 16, 2026

Analysis of three captured HAR files (`www_ohiosos_gov.har` — 74 entries, `data_ohiosos_gov.har` — 1 entry, `www_ohiosos_gov-electioncalendar.har` — empty/0 entries) plus live endpoint probing. This section **supersedes** several assumptions in the original notes above.

## Key Corrections to Original Notes

| Original assumption | Corrected finding |
|---|---|
| Live results at `liveresults.ohiosos.gov` | **Stale.** `liveresults.ohiosos.gov` now `301`-redirects → `https://www.ohiosos.gov/data`. Live results are a **Power BI Gov embed** (see below). |
| "Fully decentralized, 88 county boards" | **Misleading.** ~62 of 88 counties run on **one unified `boe.ohio.gov` platform**; only 26 (mostly metros) are independent. See county split below. |
| Results system is the SOS site | SOS site is a **Next.js + Contentful CMS** content site (`images.ctfassets.net`). It carries no structured election/race/results data — only links out to Power BI, the DATA Act portal, and county sites. |
| "Public, no authentication required" | True, but **every results tier is behind Cloudflare bot-challenge** (reCAPTCHA + `cdn-cgi/challenge-platform`). curl/httpx get `403`; automation needs a real browser. |

## Infrastructure Map (confirmed from HAR)

- **CMS:** Next.js front-end, Contentful headless CMS (`q3i90m1u8zsl` space on `ctfassets.net`).
- **DATA Act portal backend:** Azure App Service — leaked hostname `wa-sos-maint-dev.azurewebsites.net`. Fronted by Cloudflare (returns `403` challenge to scripted clients).
- **Bot protection:** Cloudflare challenge platform + Google reCAPTCHA v3 (`6LcQiXUsAAAAAJeOeCf-KWF0ir_9zA75h2MEQLSz`) sitewide.
- **QA tooling embedded:** BugHerd widget (public apikey present in markup — informational only).

## Results Tiers

### Tier 1 — Live / Election Night: Power BI Gov (publish-to-web)
Embedded report decoded from the homepage `app.powerbigov.us/view?r=…` token:

```
report key (k): f24e8a09-f178-41ba-8d63-a2cc469f1fb3
tenant   (t):   6a62fcd2-2ec8-44eb-aac5-8892a8d5a826
cloud:          US Gov (powerbigov.us / *.analysis.usgovcloudapi.net)
```

- Publish-to-web → **technically queryable** via `https://wabi-us-gov-virginia-api.analysis.usgovcloudapi.net/public/reports/querydata`.
- **Catch:** the `X-PowerBI-ResourceKey` is NOT the `k` value above (direct attempt returned `UnableToFindKeyInDBorCacheException`). The real ResourceKey must be scraped from the embed's bootstrap config (`powerbi.com`-style `appConfig` / `resolvedClusterUri`) at runtime, and the visual query schema is undocumented.
- **Verdict:** brittle, region-specific, undocumented schema. NOT a stable adapter target. Use only if live election-night data is a hard requirement.

### Tier 2 — Official / Certified: XLSX via DATA Act portal
- Entry point: `https://data.ohiosos.gov/portal/past-election-results`
- Summary-level + precinct-level XLSX, organized by race/party; includes registration & turnout.
- Cloudflare-walled → **browser-driven download required** (Playwright, not httpx).
- Sibling portals on same host: `/portal/election-dashboards`, `/portal/historical-comparisons`, `/portal/voter-registration`, `/portal/campaign-finance`, `/portal/business-services`.
- **Verdict:** best structured-results target for certified data, but needs browser automation + XLSX parsing (reuse the pdfplumber-style per-file approach but for openpyxl).

### Tier 3 — County-level
The `directories/local-election-results` RSC payload enumerates all 88 counties. They split into two adapter classes (full list in appendix):

| Hosting class | Count | URL pattern |
|---|---|---|
| **Unified `boe.ohio.gov`** | **62** | `www.boe.ohio.gov/{county}/election-info/election-night-results/` (+ path variants `/election-results/`, `/elections`; + 5 subdomain variants `{county}.boe.ohio.gov`) |
| **Independent metro domains** | **26** | bespoke per-county (Cuyahoga, Franklin, Hamilton, Stark, Lucas, Lorain, Butler, Warren, Mahoning, Delaware, …) |

**Implication:** one adapter (with ~3 path-pattern fallbacks) covers 62 counties; only 26 need bespoke handling. Far better than the 88-scraper assumption.

**Open question (next pass):** all `boe.ohio.gov` pages also `403` under Cloudflare, so the *rendered* content is unconfirmed — it may embed an ENR vendor (Clarity / ES&S / Enhanced Voting / Civera) iframe, or self-host tables. This determines whether the 62-county adapter is one JSON pull or 62 HTML scrapes. **Use the Playwright probe below to identify the vendor.**

## Updated Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API (SOS exposes no metadata API) |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results: Live | ⚠️ Brittle | Power BI Gov publish-to-web; runtime ResourceKey scrape required |
| Stage 2 — Results: Certified | ❌ No adapter | XLSX behind Cloudflare; needs Playwright + openpyxl |
| Stage 2 — Results: County | ❌ No adapter | 62 unified `boe.ohio.gov` + 26 independent; vendor TBD (run probe) |

## Playwright Probe Stub — Identify County ENR Vendor

Goal: get past Cloudflare on one unified BOE page, capture all network traffic + iframes, and surface vendor signatures / candidate JSON endpoints. Network capture is how you find the real results feed.

```python
# oh_boe_probe.py
# Identify what renders inside a unified boe.ohio.gov county results page:
#   - embedded ENR vendor (Clarity/ES&S/Enhanced Voting/Civera/Dominion), or
#   - self-hosted HTML tables, plus any XHR/fetch JSON results feed.
#
# Install: pip install playwright && playwright install chromium
# (Optional but recommended for the Cloudflare wall: pip install playwright-stealth)

import asyncio, json, re
from urllib.parse import urlparse
from playwright.async_api import async_playwright

# Swap in any county; adams is the canonical unified-pattern page.
TARGET = "https://www.boe.ohio.gov/adams/election-info/election-night-results/"

VENDOR_SIGNATURES = {
    "Clarity (Scytl)":   re.compile(r"clarityelections|enr\.clarityelections|scytl", re.I),
    "ES&S":              re.compile(r"essvote|enr\.essvote|electionresults\.ess", re.I),
    "Enhanced Voting":   re.compile(r"enhancedvoting|enhanced-voting", re.I),
    "Civera":            re.compile(r"civera", re.I),
    "Dominion":          re.compile(r"dominionvoting|dvsorders", re.I),
    "Knowink/TotalVote": re.compile(r"knowink|totalvote", re.I),
    "Power BI":          re.compile(r"powerbi|powerbigov|analysis\.(usgov)?cloud", re.I),
}

async def main():
    captured = []          # all network requests
    json_feeds = []        # candidate results JSON/XHR
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Safari/605.1.15"),
            locale="en-US",
        )
        # If installed: from playwright_stealth import stealth_async; await stealth_async(page)
        page = await ctx.new_page()

        def on_request(req):
            captured.append((req.method, req.resource_type, req.url))

        async def on_response(resp):
            url = resp.url
            ct = (resp.headers or {}).get("content-type", "")
            if "json" in ct or url.endswith(".json") or re.search(r"(summary|results|enr|electionsettings)", url, re.I):
                json_feeds.append({"url": url, "status": resp.status, "ct": ct})

        page.on("request", on_request)
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        await page.goto(TARGET, wait_until="domcontentloaded", timeout=60000)
        # Give Cloudflare's JS challenge time to resolve, then let widgets load.
        await page.wait_for_timeout(8000)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        html = await page.content()

        # 1) Vendor signature scan across page HTML + all captured URLs
        haystack = html + "\n" + "\n".join(u for _, _, u in captured)
        hits = {name: rx.findall(haystack)[:3] for name, rx in VENDOR_SIGNATURES.items() if rx.search(haystack)}

        # 2) Iframes (vendor ENR systems are almost always iframed)
        iframes = [await f.get_attribute("src") for f in await page.query_selector_all("iframe")]
        iframes = [s for s in iframes if s]

        # 3) Distinct third-party hosts touched
        hosts = sorted({urlparse(u).netloc for _, _, u in captured if urlparse(u).netloc})

        print("\n=== VENDOR SIGNATURE HITS ===")
        print(json.dumps(hits, indent=2) if hits else "  (none — likely self-hosted HTML tables)")
        print("\n=== IFRAMES ===")
        for s in iframes: print("  ", s)
        print("\n=== CANDIDATE JSON / RESULTS FEEDS ===")
        for f in json_feeds: print("  ", f["status"], f["ct"][:30], f["url"])
        print("\n=== THIRD-PARTY HOSTS TOUCHED ===")
        for h in hosts: print("  ", h)

        with open("oh_boe_probe_dump.html", "w") as fh:
            fh.write(html)
        with open("oh_boe_probe_network.json", "w") as fh:
            json.dump({"requests": captured, "json_feeds": json_feeds,
                       "iframes": iframes, "hosts": hosts, "vendor_hits": hits}, fh, indent=2)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**How to read the output:**
- **Vendor hit + iframe** → adapter targets the vendor's documented ENR JSON (e.g. Clarity's `/current_ver.txt` → `summary.json` pattern). Best case: one schema covers all 62 unified counties.
- **No vendor, JSON feed present** → self-hosted API; capture the feed URL/shape from `oh_boe_probe_network.json`.
- **No vendor, no JSON, tables in HTML** → 62-county HTML scrape; parse `oh_boe_probe_dump.html` to build the row selector.
- **Page still shows a Cloudflare interstitial** → add `playwright-stealth`, or run headful (`headless=False`), or route through a residential proxy.

Re-run against 2–3 independent metros (Cuyahoga, Franklin, Hamilton) separately — those will each need their own adapter regardless.

## County Hosting Appendix

### Unified `boe.ohio.gov` platform — 62 counties
Standard path `…/{county}/election-info/election-night-results/` unless noted.

adams, ashland, ashtabula, athens, auglaize, belmont, brown, carroll, champaign, clark, clinton, darke, defiance, erie, fairfield `(…/election-results/)`, fayette, fulton, gallia, geauga `(…/election-results/)`, greene, hardin, harrison, highland, hocking, holmes, jackson, jefferson, knox, lawrence, licking, logan, madison, marion, medina, meigs, miami, monroe, morgan, muskingum, noble, paulding, perry `(…/election-results/)`, pickaway, pike, preble, putnam, richland `(…/election-results/)`, ross, scioto, seneca, shelby, summit `(/summit/elections)`, tuscarawas, vanwert, vinton, washington, wyandot

Subdomain variants on same platform: allen `(www.allen.boe.ohio.gov/election-reports)`, columbiana `(www.columbiana.boe.ohio.gov/elections/election-results/)`, coshocton `(www.coshocton.boe.ohio.gov/election-results/)`, huron `(www.huron.boe.ohio.gov/election-results/)`, montgomery `(www.montgomery.boe.ohio.gov/election-results/)`

### Independent county domains — 26 counties
- butler — `elections.bcohio.gov/dataandresources/results.php`
- clermont — `boe.clermontcountyohio.gov/election_results/`
- crawford — `crawfordcountyohioboe.gov/election-results/`
- cuyahoga — `boe.cuyahogacounty.gov/elections`
- delaware — `vote.delawarecountyohio.gov/data/pastresults/`
- franklin — `vote.franklincountyohio.gov/election-info`
- guernsey — `boe.guernseycounty.gov/documents/`
- hamilton — `votehamiltoncountyohio.gov/results/`
- hancock — `hancockcountyohioelections.gov/`
- henry — `henrycountyohio.gov/241/Election-Results`
- lake — `www.lakecountyohio.gov/boe/election-results/`
- lorain — `www.voteloraincountyohio.gov/elections-results-search`
- lucas — `www.lucascountyohiovotes.gov/historic_election_results/index.php`
- mahoning — `vote.mahoningcountyoh.gov/`
- mercer — `elections.mercercountyohio.gov/electionResults.shtml`
- morrow — `boe.morrowcountyohio.gov/new_page/index.php`
- ottawa — `boe.ottawa.oh.gov/current-results/`
- portage — `www.portagecounty-oh.gov/board-elections/pages/election-results`
- sandusky — `sanduskycountyoh.gov/index.php?page=board-of-elections`
- stark — `www.starkcountyohio.gov/government/offices/board_of_elections/election_results.php`
- trumbull — `boe.co.trumbull.oh.gov/boe_results.html`
- union — `www.unioncountyohio.gov/departments/boe/boe-election-results`
- warren — `vote.warrencountyohio.gov/`
- wayne — `www.waynecountyoh.gov/election-results-past-election-results/`
- williams — `www.williamscountyoh.gov/152/Election-Results`
- wood — `www.co.wood.oh.us/boe/ElectionArchives.html`

*(62 + 26 = 88 ✓)*

---

# Probe Results — June 16–17, 2026

## boe.ohio.gov Unified Platform — Vendor Identified: **Self-hosted PDFs (no vendor)**

### Methodology
- Playwright headless: **blocked by Cloudflare** (Ohio SOS custom challenge platform). `403` for all automation-UA requests.
- nodriver (headful, Chrome): **passes Cloudflare** challenge. However, the probe targeted `election-night-results/` which returns `404` outside active elections. Corrected target: `election-results/`.
- **HAR capture** (Adams County, `/adams/election-info/election-results/`): successful, 142 requests, 18 MB. This is the definitive vendor analysis.

### Adams County HAR Findings

| Finding | Detail |
|---|---|
| ENR vendor | **None** — zero hits for Clarity, ES&S, Enhanced Voting, Civera, Dominion, KNOWiNK, Power BI |
| Third-party hosts | `boe.ohio.gov`, Google Fonts, `cloudflareinsights.com`, Adobe (PDF reader) only |
| Results format | **PDF files** served directly from `boe.ohio.gov` |
| PDF URL pattern | `/{county}/c/elecres/{YYYYMMDD}results.pdf` |
| Precinct PDF | `/{county}/c/elecres/{YYYYMMDD}precinct.pdf` |
| Historical depth | Adams page lists PDFs back to Nov 2021 |
| Iframes | Only `/adams/c/webpart/Notices.html` (county notice board) |
| JSON/API calls | **Zero** — no XHR, no fetch, no JSON feeds |

**Example URLs from Adams election-results page:**
```
https://www.boe.ohio.gov/adams/c/elecres/20260505results.pdf   ← May 2026 primary
https://www.boe.ohio.gov/adams/c/elecres/20260505precinct.pdf
https://www.boe.ohio.gov/adams/c/elecres/20251104results.pdf
https://www.boe.ohio.gov/adams/c/elecres/20251104precinct.pdf
https://www.boe.ohio.gov/adams/c/elecres/20241105results.pdf
https://www.boe.ohio.gov/adams/c/elecres/20240319results.pdf
```

### Conclusion for 62-County Unified Platform

The `boe.ohio.gov` unified WordPress platform serves **self-hosted PDF files** for all 62 counties. There is no structured data feed, JSON API, or embedded third-party ENR vendor. Adapting these counties would require:
1. Scraping the `/{county}/election-info/election-results/` page to enumerate PDF URLs
2. Downloading each PDF
3. Parsing with `pdfplumber` or `PyMuPDF`
4. Reverse-engineering the PDF table structure (likely varies per election type)

**This is not a viable near-term adapter target.** PDF parsing is fragile, layout-dependent, and county-specific. Defer until there's a specific use case.

## SOS Directory — `/directories/local-election-results`

The SOS data portal (`ohiosos.gov/data`) hosts an interactive county map pointing to all 88 county BOE sites. The RSC page payload (318 KB) enumerates:
- 62 counties → `www.boe.ohio.gov/{county}/election-info/election-night-results/`
- 16 independent county domains (see appendix; Cuyahoga, Franklin, Hamilton, Wood, Lake, Union, Portage, Stark, Lorain, Lucas, Crawford, Hancock, Mercer, Sandusky, Wayne + SOS data portal itself)

This page is a useful county discovery mechanism but contains no results data itself.

## Cuyahoga County — **Enhanced Voting (confirmed)**

Independently confirmed from earlier session: `boe.cuyahogacounty.gov/elections` uses the **Enhanced Voting** platform at `app.enhancedvoting.com`.

- API: `https://app.enhancedvoting.com/api/elections/cuyahogacounty/{publicElectionId}/data`
- `ballotItems` are at the **top level** of the response (not nested under `d.election`)
- 297 ballot items confirmed for Nov 2025 general
- The existing `enhanced_voting.py` adapter reads `data.get("ballotItems", [])` — matches this schema
- Adding `cuyahogacounty` as a jurisdiction slug would extend EV coverage to Cuyahoga

## Updated Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results: Live | ⚠️ Brittle | Power BI Gov publish-to-web; runtime ResourceKey scrape required |
| Stage 2 — Results: Certified (SOS) | ❌ No adapter | XLSX at `data.ohiosos.gov`; Cloudflare-walled; needs Playwright + openpyxl |
| Stage 2 — Results: 62-county boe.ohio.gov | ❌ Not viable | Self-hosted PDFs; no structured data; requires PDF parsing |
| Stage 2 — Results: Cuyahoga (Enhanced Voting) | ✅ Buildable | Extend existing EV adapter with `cuyahogacounty` jurisdiction |
| Stage 2 — Results: 25 other independents | ❌ No adapter | Mixed formats; each county needs bespoke approach |

## Recommendation (as of June 17, 2026)

**Ohio is not a viable statewide adapter target** at this time. The 62-county unified platform serves PDFs with no structured API. The SOS certified results (XLSX) are Cloudflare-walled and require browser automation + spreadsheet parsing.

**What is buildable now:**
- **Cuyahoga County** via the existing Enhanced Voting adapter (`enhanced_voting.py`) — add `cuyahogacounty` jurisdiction. This would cover Ohio's most populous county (Cuyahoga = Cleveland, ~1.2M residents) but only 1 of 88 counties.

**Defer until viable:**
- Statewide SOS XLSX adapter (needs Playwright infrastructure decision)
- boe.ohio.gov PDF adapter (needs PDF parsing + layout reverse-engineering)
- Other independent metro counties (each needs individual research)

---

# Probe Results — June 26, 2026

## `liveresults.boe.ohio.gov` — Ohio State Clarity ENR Platform (Major Finding)

Independent county homepages were scanned via curl (browser UA) to identify ENR vendor links. Three independent counties confirmed using a shared state-managed Clarity ENR platform at `liveresults.boe.ohio.gov`:

| County | Slug | Confirmed election IDs |
|---|---|---|
| Stark | `starkohenr` | 13 (May 2026 primary) |
| Butler | `butlerohenr` | 14–23 (multiple elections); older on `livevoterturnout.com` |
| Warren | `warrenohenr` | 17 (current as of June 2026) |

**URL pattern:** `https://liveresults.boe.ohio.gov/ENR/{county}ohenr/{electionId}/en/`

This is the standard Clarity Elections ENR URL structure — same as WV (`/ENR/`), same `current_ver.txt` → `{version}/json/en/summary.json` data flow. The existing `clarity.py` adapter handles this already.

**Platform history** (visible from Butler's full results archive):
- Oldest elections: `www.livevoterturnout.com/{County}/LiveResults/en/Index_{id}.html`
- Transitional: `liveresults.boe.ohio.gov/{county}oh/LiveResults/en/Index_{id}.html`
- Current: `liveresults.boe.ohio.gov/ENR/{county}ohenr/{id}/en/Index_{id}.html`

### Cloudflare Protection
`liveresults.boe.ohio.gov` returns `403 cf-mitigated: challenge` to all curl/httpx requests regardless of browser UA. Same behavior as `enr-scvotes.org` (SC). **Fix: add to `CLARITY_PROXY_HOSTS` in `clarity.py` + `ALLOWED_HOSTS` on CF Worker** — same mechanism already in production for SC.

### Scope Unknown for Unified Counties
The 62 unified `boe.ohio.gov` counties return 403 Cloudflare challenges on all requests (headless and curl), so whether they also have ENR slugs on `liveresults.boe.ohio.gov` is unconfirmed. Their certified results pages serve PDFs only. Election night results paths (`/election-night-results/`) return 404 outside active elections. **Hypothesis: the unified counties likely also have Clarity ENR slugs on this platform** (it's state-managed and the pattern is uniform), but this requires a headed browser during an active election to confirm.

## Franklin County — GUID-based File Downloads (No API)

`vote.franklincountyohio.gov` site loads cleanly (no Cloudflare). Results are published as XLSX and PDF files via `/getmedia/{guid}/` URLs. GUIDs are random per upload — there is no predictable URL pattern. The election info page must be scraped to find current file links. No JSON API.

**Verdict: not viable without browser scrape + XLSX parsing.**

## Hamilton County, Lucas County, Portage County — Cloudflare-blocked

These independent county sites return Cloudflare JS challenge responses to headless Playwright and curl. Format unconfirmed. Defer.

## Clermont County — PDFs + CSV

`boe.clermontcountyohio.gov` serves PDF and a CSV file per election. CSV naming pattern: `{id}ElectionResultsCSV{year}{type}.CSV` (e.g. `13ElectionResultsCSV2025SPE.CSV`). No Clarity ENR links observed. Not a priority target.

## Cuyahoga County — Enhanced Voting (URL updated)

Homepage now links to `enhancedvoting.com/results/public/Cuyahoga-County-OH` (redirects to `www.enhancedvoting.com/results/public/Cuyahoga-County-OH`). Returns 404 when no active election. The underlying API at `app.enhancedvoting.com/api/elections/cuyahogacounty/` is expected to still work during elections — the 404 is from no active publicElectionId.

## Updated Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results: Live | ⚠️ Brittle | Power BI Gov publish-to-web; runtime ResourceKey scrape required |
| Stage 2 — Results: Certified (SOS) | ❌ No adapter | XLSX at `data.ohiosos.gov`; Cloudflare-walled |
| Stage 2 — Results: 62-county boe.ohio.gov | ❌ Not viable (certified) | PDFs only; election night format unconfirmed |
| Stage 2 — Clarity ENR counties (Stark, Butler, Warren + possibly more) | ✅ Buildable | Proxy `liveresults.boe.ohio.gov` + Clarity adapter; per-election `results_url` in admin |
| Stage 2 — Cuyahoga (Enhanced Voting) | ✅ Buildable | Add `cuyahogacounty` slug to EV adapter |
| Stage 2 — Franklin, Hamilton, and other large metros | ❌ Not viable / unknown | GUID files or Cloudflare-blocked |

## Updated Recommendation

**Ohio is now viable for partial county coverage** via two existing adapters:

### 1. Clarity ENR (multiple independent counties)
- Add `liveresults.boe.ohio.gov` to `CLARITY_PROXY_HOSTS` in `backend/results/adapters/clarity.py`
- Add `liveresults.boe.ohio.gov` to CF Worker `ALLOWED_HOSTS` secret
- For each election: set `results_url` in Django admin per county (e.g. `https://liveresults.boe.ohio.gov/ENR/starkohenr/13/en/`)
- **Currently confirmed**: Stark (~375K pop), Butler (~420K), Warren (~250K) = ~1M total
- **Potentially many more**: If the 62 unified counties also have ENR slugs, coverage could approach statewide

### 2. Enhanced Voting (Cuyahoga)
- Add `cuyahogacounty` to `JURISDICTION_SLUGS` in `enhanced_voting.py`
- Cuyahoga = ~1.2M residents (Cleveland metro)

### Open Question Before Building
Before committing to an Ohio adapter, it's worth confirming whether the unified `boe.ohio.gov` counties also have Clarity ENR slugs. The way to confirm: during an active election (any Ohio municipal election), try `https://liveresults.boe.ohio.gov/ENR/adamsohenr/{id}/en/current_ver.txt` via the proxy. If it returns a version string, unified county coverage is confirmed.

### Not buildable yet
- Franklin, Hamilton, Lucas, Portage: blocked or GUID-based files
- Statewide SOS XLSX: Cloudflare-walled, needs Playwright

---

# Federal Races Research — June 26, 2026

## Scope

Ohio has 15 US House seats and 2 US Senate seats (Class I and Class III, alternating cycles). Presidential elections occur every 4 years. All are **statewide or multi-county** races — no Ohio congressional district falls entirely within a single county.

## SOS Statewide Results — No Accessible Live API

Full sweep of all SOS-controlled sources for statewide federal race results:

| Source | URL | Status | Notes |
|---|---|---|---|
| Data Portal (XLSX) | `data.ohiosos.gov/portal/past-election-results` | ❌ Cloudflare-walled | Playwright headless blocked; nodriver (headed) required |
| Power BI Gov embed | `app.powerbigov.us/view?r=eyJrIjoiZjI0...` | ⚠️ Brittle | Runtime ResourceKey required; schema undocumented |
| SOS main site | `www.ohiosos.gov/elections/election-results-and-data/` | ❌ Cloudflare-walled | Redirects to `/data`; no direct XLSX links in RSC payloads |
| Statewide Clarity ENR | `liveresults.boe.ohio.gov/ENR/{statewide slug}/` | ❌ Not found | Probed common slug patterns (`ohiosos`, `ohioenr`, `ohenr`, etc.); all return 403 CF challenge; existence unconfirmed |

**Confirmed via SOS HAR (RSC payloads):** No statewide ENR URL is linked anywhere in the SOS system. The only statewide results path is the DATA Act XLSX portal and Power BI embed.

## County Clarity ENR — Federal Race Coverage Gap

County-level Clarity ENR feeds (Stark, Butler, Warren + others) contain federal races on each county's ballot, but report **county-level partial totals only**. Since no Ohio congressional district is wholly contained within a single county, county ENR data cannot produce complete district or statewide totals without aggregating multiple counties.

**Butler County election ID mapping** (confirmed from homepage):

| ID | Election | Federal races present |
|---|---|---|
| 14 | Nov 8, 2022 general | US Senate (Vance/Ryan), US House OH-8, US House fragments |
| 16 | Mar 19, 2024 primary | Presidential preference |
| 19 | Nov 5, 2024 general | President, US Senate (Moreno/Brown), US House OH-8 |

Each ID contains only Butler County's portion of statewide/district totals.

## Other Federal Data Sources Evaluated

| Source | Type | Vote totals? | Notes |
|---|---|---|---|
| FEC API (`api.open.fec.gov`) | Campaign finance | ❌ No | Has candidate metadata, fundraising; no certified vote counts |
| MIT Election Data & Science Lab | Historical CSV | ✅ Historical only | County-level results on Harvard Dataverse; not a live API |
| OpenElections | Historical CSV | ✅ Historical only | GitHub-hosted per-state CSVs; not suitable for live/recent elections |
| Associated Press Elections | Live results | ✅ Yes | Commercial license required; used by AP member newsrooms |
| Decision Desk HQ | Live results | ✅ Yes | Commercial API; subscription required |

No free public API provides live statewide Ohio federal race results outside the SOS system.

## Additional Independent County Sweep

Additional independent counties checked for `liveresults.boe.ohio.gov` usage (all via curl, browser UA):

| County | Result |
|---|---|
| Trumbull | PDF-only (`/pdfs/Election Results...pdf`); no ENR vendor |
| Montgomery (boe subdomain) | SOS maintenance page at time of check (June 26 maintenance window) |
| Columbiana, Huron, Coshocton (boe subdomains) | No ENR links visible; likely PDF like unified platform |
| Delaware | WordPress pagination; no ENR links on homepage |
| Lorain, Lake, Hancock | Loaded but no ENR vendor signatures visible |

No additional Clarity ENR counties confirmed beyond Stark, Butler, Warren. Montgomery (Dayton, ~535K) is on the unified boe.ohio.gov subdomain and likely serves PDFs.

## Statewide Federal Results — Viable Paths Ranked

1. **All-county Clarity ENR aggregation** — If all 88 counties use `liveresults.boe.ohio.gov`, collecting slugs for all counties and summing results would reconstruct statewide totals. Requires:
   - Confirming all 88 counties have Clarity ENR slugs (test during next active election)
   - Entering 88 `results_url` values per election in Django admin (~4 elections/year = ~352 entries/year)
   - Verdict: **operationally feasible but high maintenance**; consider automation to reduce admin burden

2. **SOS XLSX portal** — Best source if Cloudflare can be bypassed. Statewide certified data, all races. Requires Playwright + XLSX parsing infrastructure. Verdict: **viable after Playwright infrastructure decision**.

3. **Power BI Gov runtime scrape** — Technically possible but undocumented schema and runtime ResourceKey requirement make it fragile. Verdict: **not recommended** as a production data source.

## Conclusion: Federal Coverage Classification

Under the coverage framework in `docs/design/COVERAGE-CLARIFICATION.md`:

- **Federal results ingested (statewide)**: ❌ Not available without either (a) all-county aggregation or (b) SOS XLSX bypass
- **Federal elections discovered**: ✅ Civic API
- **Federal races created**: ⚠️ Untested (Civic API)

**Ohio remains Federal Only until a statewide results source is resolved.** The county Clarity ENR adapters are valuable for county-level election night reporting (an Enhanced Coverage capability) but do not satisfy the Core Coverage requirement for statewide federal results.

---

## June 26, 2026 — Google Civic API Probe

### `representatives` endpoint: deprecated

`GET /civicinfo/v2/representatives?address=...` returns `404 Method not found`. Google deprecated this endpoint. The existing CivicMirror adapter does not call it, so no immediate breakage.

### `voterinfo` endpoint: requires active election

`GET /civicinfo/v2/voterinfo?address=...&electionId=...` only returns contests during the active election window (approximately 60–90 days before election day). No Ohio elections are currently in the API:
- May 2026 primary has already passed.
- November 2026 general will not appear until approximately August–September 2026.

Scan of election ID ranges 8820–8860 and 9440–9530 found no Ohio elections.

### Ohio address coverage

Ohio has **1 address** defined in `backend/integrations/civic/addresses.py`:
```python
"OH": [
    {"label": "OH-capital", "address": "1 Capitol Sq, Columbus, OH 43215"},
]
```
This single Columbus address covers only the OH-3 congressional district (Franklin County). 14 of 15 congressional districts have no race coverage.

**Fix applied (June 26, 2026):** OH entry expanded to 15 addresses covering all congressional districts:

| Label | Address | District |
|---|---|---|
| OH-1 | 801 Plum St, Cincinnati, OH 45202 | Cincinnati / Hamilton County |
| OH-2 | 270 E Main St, Batavia, OH 45103 | Clermont / southeast suburbs |
| OH-3 | 1 Capitol Sq, Columbus, OH 43215 | Columbus / Franklin County |
| OH-4 | 50 Town Square, Lima, OH 45801 | Lima / north-central Ohio |
| OH-5 | 221 Clinton St, Defiance, OH 43512 | Defiance / northwest Ohio |
| OH-6 | 501 3rd St, Steubenville, OH 43952 | Steubenville / eastern Ohio valley |
| OH-7 | 107 W Liberty St, Wooster, OH 44691 | Wooster / northeast-central |
| OH-8 | 345 High St, Hamilton, OH 45011 | Hamilton / Butler County |
| OH-9 | 1 Government Center, Toledo, OH 43604 | Toledo / Lake Erie shoreline |
| OH-10 | 101 W 3rd St, Dayton, OH 45402 | Dayton / Montgomery County |
| OH-11 | 601 Lakeside Ave E, Cleveland, OH 44114 | Cleveland east / Cuyahoga |
| OH-12 | 1 W Main St, Newark, OH 43055 | Newark / Licking County |
| OH-13 | 209 S High St, Akron, OH 44308 | Akron / Summit County |
| OH-14 | 47 N Park Pl, Painesville, OH 44077 | Painesville / Lake County |
| OH-15 | 1 South Court St, Athens, OH 45701 | Athens / southeast Ohio |

All 14 new addresses validated against Civic API ("Election unknown" — addresses recognized, no active election).

### Virginia proxy for active-election behavior

During a Virginia Republican primary (active election), the Civic API returned only **1 contest** (US Senate) across 3 addresses in different districts. This confirms that Civic API coverage is sparse even during active election windows — likely reflecting incomplete VIP (Voting Information Project) data submissions by state.

### Stage 1 implications for Ohio

| Race type | Civic API (after fix) | State-verified source |
|---|---|---|
| US House (all 15 districts) | ✅ 15 addresses configured | ❌ SOS blocked |
| Governor + statewide offices | ⚠️ Depends on VIP data quality | ❌ SOS blocked |
| US Senate | N/A — no OH Senate race in 2026 | N/A |
| State legislative | ⚠️ Partial (1 district per address) | ❌ SOS blocked |

**Race creation window**: Only during the ~60–90 day active window before election day. Ohio Nov 2026 races will not be createable until August–September 2026.

---

## June 26, 2026 — Cloudflare Bot Management Investigation

### Problem

All Ohio data sources are protected by **Cloudflare Managed Challenge** — the most aggressive CF Bot Management tier. This is not a simple IP reputation block; it requires JavaScript execution for challenge resolution.

Sites confirmed blocked:
- `liveresults.boe.ohio.gov` — Ohio Clarity ENR (county results JSON)
- `data.ohiosos.gov` — Ohio SOS DATA Act portal (XLSX certified results)
- `www.ohiosos.gov` — Main SOS website
- `boe.ohio.gov` — Unified county BOE platform

### CF Worker proxy: insufficient

The `civicmirror-proxy` CF Worker bypasses **Akamai/CloudFront IP reputation blocks** (which affect Iowa and South Carolina). It does NOT bypass Cloudflare Bot Management:
- `liveresults.boe.ohio.gov` added to `ALLOWED_HOSTS` on June 26, 2026
- `data.ohiosos.gov` added to `ALLOWED_HOSTS` on June 26, 2026
- Both return `HTTP 403` with full CF challenge HTML body even via the proxy

Even Cloudflare edge IPs (Worker infrastructure) are challenged by these sites' CF Bot Management configuration.

### Playwright headless: insufficient

Playwright headless Chrome is also blocked — CF Managed Challenge fingerprints headless browser signals and challenges them. Waited 10+ seconds; challenge did not resolve on either site.

### RSC bypass on www.ohiosos.gov (partial)

`www.ohiosos.gov` runs Next.js. RSC requests with `Rsc: 1` header bypass the CF challenge and return `HTTP 200 text/x-component`. However:
- The RSC response (122K chars) is the global layout/navigation shell only
- Page-specific content (election results links, XLSX downloads) is fetched client-side from Contentful CMS
- Contentful access token is server-side only (not in client-side JS bundle)
- This bypass is useful for navigation data, not election results

### What would unblock Ohio

1. **nodriver + xvfb** — `nodriver` (undetected Chrome) running headed with an X display server. The existing `Updated_BOE_Probe.py` in this directory uses this approach. Not currently available on the server (neither xvfb nor nodriver installed).
2. **Residential proxy** — Route requests through residential IPs. CF Bot Management trusts residential IPs significantly more than datacenter IPs.
3. **Ohio SOS CF configuration change** — If Ohio SOS removes or relaxes their Managed Challenge configuration.

### Revised status

| Adapter | Previous status | Revised status |
|---|---|---|
| Clarity ENR (`liveresults.boe.ohio.gov`) | Buildable | **Blocked — CF Managed Challenge** |
| SOS XLSX (`data.ohiosos.gov`) | Research needed | **Blocked — CF Managed Challenge** |
| Enhanced Voting Cuyahoga | Buildable | **Accessible** (returns 404 when no active election — expected) |

**Ohio Stage 2 adapters cannot be built until the CF Bot Management constraint is resolved.**

---

## June 26, 2026 — CFDISCLOSURE System Discovery

### Source

**`www6.ohiosos.gov`** — Oracle APEX app hosting Ohio's Campaign Finance Disclosure (CFDISCLOSURE) system. Discovered via HAR capture of the File Transfer Page (`CFDISCLOSURE:73`).

### Active Candidate List (ACT_CAN_LIST.CSV)

**URL:** `https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:120`
**Content-Disposition:** `attachment; filename="ACT_CAN_LIST.CSV"`
**Size:** ~122KB, 764 rows
**Updated:** Daily (timestamp confirmed as 10:30 AM on day of access)

**Schema (22 columns):**
`COM_NAME, MASTER_KEY, COM_ADDRESS, COM_CITY, COM_STATE, COM_ZIP, TREA_FIRST_NAME, TREA_LAST_NAME, TREA_MIDDLE_NAME, TREA_SUFFIX, TREA_ADDRESS, TREA_CITY, TREA_STATE, TREA_ZIP, DEP_FIRST_NAME, DEP_LAST_NAME, CANDIDATE_FIRST_NAME, CANDIDATE_LAST_NAME, OFFICE, DISTRICT, OFFICE (party), SPONSOR`

Note: two columns named `OFFICE` — col 18 = office type, col 20 = party affiliation.

**Office breakdown (764 rows, June 26, 2026):**

| Office | Count |
|---|---|
| HOUSE (OH State House) | 470 |
| SENATE (OH State Senate) | 105 |
| COURT OF APPEALS JUDGE | 87 |
| GOVERNOR | 19 |
| STATE TEACHERS RETIREMENT | 15 |
| STATE BOARD OF EDUCATION | 14 |
| SUPREME COURT JUSTICE | 14 |
| TREASURER | 7 |
| ATTORNEY GENERAL | 3 |
| SECRETARY OF STATE | 3 |
| AUDITOR | 3 |
| Other | 20 |

Party breakdown: Democrat (335), Republican (315), Independent (28), Libertarian (25), Non-Partisan (20).

**Coverage assessment for Stage 1:**
- ✅ Ohio State House — all 99 districts, multiple candidates per district
- ✅ Ohio State Senate — all active candidates
- ✅ Governor, AG, SOS, Treasurer, Auditor (statewide executive)
- ✅ Supreme Court, Court of Appeals (judicial)
- ❌ **Federal races NOT included** — US House and US Senate are excluded (federal candidates file with FEC, not state campaign finance)

### Other available files (same File Transfer Page)

| GETID | File | Size |
|---|---|---|
| 120 | Active Candidate List (`ACT_CAN_LIST.CSV`) | 122 KB |
| 123 | Candidate Cover Pages | 4,668 KB |
| 6768 | Candidate Contributions—2026 | 90,289 KB |
| 6769 | Candidate Expenditures—2026 | 3,649 KB |

Historic contributions/expenditures go back to 1990 (annual files).

### Access requirements

Download requires two cookies set in sequence:
1. `cf_clearance` — CF Bot Management clearance (requires real browser or nodriver)
2. `ORA_WWV_APP_119` — Oracle APEX session (established by navigating to `CFDISCLOSURE:73`)

The download URL itself has no session ID parameter — APEX session is carried via cookie only.

**Access pattern once CF is bypassed:**
```
1. GET https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:::NO::P73_TYPE:CAN:
   → Establishes ORA_WWV_APP_119 session cookie
2. GET https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:120
   → Returns ACT_CAN_LIST.CSV (with session cookie)
```

### Comparison with Civic API for Stage 1

| Source | State legislative | Statewide | Federal | Available |
|---|---|---|---|---|
| CFDISCLOSURE ACT_CAN_LIST.CSV | ✅ All (5 months early) | ✅ All | ❌ None | CF-blocked |
| Civic API (15 addresses) | ⚠️ Partial | ⚠️ Partial | ✅ US House (15 districts) | ~Aug–Sep 2026 |

CFDISCLOSURE is the superior source for state-level races — available months before the election, structured CSV, no VIP data quality issues. Federal races still require Civic API.

### Revised Ohio Stage 1 strategy (when CF is resolved)

1. **CFDISCLOSURE** → seed all OH state legislative + statewide candidates (available now)
2. **Civic API with 15-address config** → seed US House candidates (active ~Aug–Sep 2026)
3. No US Senate race for Ohio in 2026