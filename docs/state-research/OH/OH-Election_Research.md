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

## Recommendation

**Ohio is not a viable statewide adapter target** at this time. The 62-county unified platform serves PDFs with no structured API. The SOS certified results (XLSX) are Cloudflare-walled and require browser automation + spreadsheet parsing.

**What is buildable now:**
- **Cuyahoga County** via the existing Enhanced Voting adapter (`enhanced_voting.py`) — add `cuyahogacounty` jurisdiction. This would cover Ohio's most populous county (Cuyahoga = Cleveland, ~1.2M residents) but only 1 of 88 counties.

**Defer until viable:**
- Statewide SOS XLSX adapter (needs Playwright infrastructure decision)
- boe.ohio.gov PDF adapter (needs PDF parsing + layout reverse-engineering)
- Other independent metro counties (each needs individual research)