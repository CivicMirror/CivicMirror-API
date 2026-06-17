# oh_boe_probe_nodriver.py
# nodriver port of the BOE county results probe — clears Cloudflare's
# automation-protocol gate that defeats Playwright/Camoufox/Patchright.
#
# Install:  pip install nodriver
# RUN HEADFUL. On a headless server, wrap with xvfb:
#     xvfb-run -a python oh_boe_probe_nodriver.py
# (The 2026 benchmark where nodriver passed every Cloudflare target ran headed;
#  headless is itself a detection signal.)

import asyncio, json, re
from urllib.parse import urlparse
import nodriver as uc
from nodriver import cdp

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

captured = []     # all response URLs seen
json_feeds = []   # candidate results JSON/XHR feeds


def on_response(evt, *_):
    # cdp.network.ResponseReceived; signature tolerant across nodriver versions
    r = getattr(evt, "response", None)
    if r is None:
        return
    url = r.url
    ct = (getattr(r, "mime_type", "") or "")
    captured.append(url)
    if ("json" in ct or url.endswith(".json")
            or re.search(r"(summary|results|enr|electionsettings|current_ver)", url, re.I)):
        json_feeds.append({"url": url, "status": getattr(r, "status", "?"), "ct": ct})


async def main():
    browser = await uc.start(headless=False, browser_args=["--lang=en-US"])
    tab = await browser.get("about:blank")

    # Enable network + register handler BEFORE navigating so we catch the
    # post-challenge results XHRs.
    await tab.send(cdp.network.enable())
    tab.add_handler(cdp.network.ResponseReceived, on_response)

    await tab.get(TARGET)
    await tab.sleep(10)  # let the CF JS challenge resolve, then widgets load
    try:
        await tab.wait_for(text="", timeout=15)  # settle; ignore if it times out
    except Exception:
        pass

    html = await tab.get_content()

    # 1) Vendor signature scan across HTML + every captured URL
    haystack = html + "\n" + "\n".join(captured)
    hits = {name: rx.findall(haystack)[:3]
            for name, rx in VENDOR_SIGNATURES.items() if rx.search(haystack)}

    # 2) Iframes (vendor ENR systems are almost always iframed)
    iframes = []
    for el in await tab.select_all("iframe"):
        src = el.attrs.get("src") if hasattr(el, "attrs") else None
        if src:
            iframes.append(src)

    # 3) Distinct hosts touched
    hosts = sorted({urlparse(u).netloc for u in captured if urlparse(u).netloc})

    print("\n=== VENDOR SIGNATURE HITS ===")
    print(json.dumps(hits, indent=2) if hits else "  (none — likely self-hosted HTML tables)")
    print("\n=== IFRAMES ===")
    for s in iframes:
        print("  ", s)
    print("\n=== CANDIDATE JSON / RESULTS FEEDS ===")
    for f in json_feeds:
        print("  ", f["status"], (f["ct"] or "")[:30], f["url"])
    print("\n=== HOSTS TOUCHED ===")
    for h in hosts:
        print("  ", h)

    # Detect a still-blocked outcome
    if re.search(r"(cf-challenge|Just a moment|cdn-cgi/challenge|Attention Required)", html, re.I):
        print("\n[!] Cloudflare interstitial still present — try a residential proxy "
              "(uc.start supports --proxy-server=) or a clean residential IP.")

    with open("oh_boe_probe_dump.html", "w") as fh:
        fh.write(html)
    with open("oh_boe_probe_network.json", "w") as fh:
        json.dump({"target": TARGET, "vendor_hits": hits, "iframes": iframes,
                   "json_feeds": json_feeds, "hosts": hosts,
                   "all_response_urls": captured}, fh, indent=2)

    browser.stop()


if __name__ == "__main__":
    uc.loop().run_until_complete(main())