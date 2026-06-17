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