"""
SC VREMS Candidate Scraper
vrems.scvotes.sc.gov/Candidate

Confirmed via HAR analysis (2026-05-24) across General, Local, and Special election types.

Auth: ASP.NET Core antiforgery cookie only — no login, no credentials.
      The cookie is issued automatically on the first GET request.

Election type coverage:
  General  → Statewide primaries and general elections (2018–present)
  Local    → All municipal/county/school/fire/water district elections,
             including local specials AND referendums (2019–present)
             2026 alone: 119 elections across the full calendar year
  Special  → State legislative specials only: US House, SC Senate, SC House
             (Local special elections are NOT here — they are under Local)

Candidate status values:
  Active elections:   Active, Withdrew Before Primary, Decertified before Primary,
                      Disqualified before Primary, Not Certified for Primary
  Completed elections: Elected, Defeated In Primary, Defeated in Election
  (Status doubles as lightweight race outcome for completed elections.)

Empty candidate tables:
  Local elections whose filing period hasn't opened yet return 0 rows
  with no error message. Check filingPeriodBeginDate before expecting data.
  Referendums always have 0 candidates (they are ballot questions, not races).
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

BASE = "https://vrems.scvotes.sc.gov"

ELECTION_TYPES = ["General", "Local", "Special"]


# ---------------------------------------------------------------------------
# Session setup
# ---------------------------------------------------------------------------

def get_session():
    """
    GET /Candidate/SelectElection
    Establishes the antiforgery session cookie. The cookie is all that is
    needed for GetYearsByElectionType, GetElections, and CandidateSearch.
    The __RequestVerificationToken in the HTML is only used if you want to
    replicate the browser's SelectElection POST redirect — which is not
    required for scraping.

    Returns: requests.Session with cookie already set
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "CivicMirror-SC-Scraper/1.0",
    })
    resp = session.get(f"{BASE}/Candidate/SelectElection", timeout=15)
    resp.raise_for_status()
    return session


# ---------------------------------------------------------------------------
# Discovery endpoints (clean JSON)
# ---------------------------------------------------------------------------

def get_years(session, election_type: str) -> list[int]:
    """
    GET /Candidate/GetYearsByElectionType?electionType={type}

    Returns list of years descending (most recent first).
    General:  [2026, 2024, 2022, 2020, 2018]
    Local:    [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019]
    Special:  [2026, 2025, 2024, 2023, 2022, 2020, 2019]
    """
    resp = session.get(
        f"{BASE}/Candidate/GetYearsByElectionType",
        params={"electionType": election_type},
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=15,
    )
    resp.raise_for_status()
    return [item["electionYear"] for item in resp.json()]


def get_elections(session, election_type: str, year: int) -> list[dict]:
    """
    GET /Candidate/GetElections?electionType={type}&year={year}

    Returns list of election records. Each dict has:
      electionId          str   — used for CandidateSearch POST
      electionName        str   — short name
      displayName         str   — "{M/D/YYYY} {electionName}"
      electionDate        str   — ISO 8601 datetime
      filingPeriodBeginDate str|None — None for referendums

    2026 counts confirmed: General=2, Local=119, Special=1
    """
    resp = session.get(
        f"{BASE}/Candidate/GetElections",
        params={"electionType": election_type, "year": year},
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=15,
    )
    resp.raise_for_status()
    elections = resp.json()
    for e in elections:
        e["electionType"] = election_type
    return elections


def get_all_elections(session, election_types=None, years=None) -> list[dict]:
    """
    Sweep all election types and (optionally filtered) years.
    Returns deduplicated flat list of election dicts.
    Use years=[2026] to limit scope.
    """
    if election_types is None:
        election_types = ELECTION_TYPES

    seen = set()
    results = []

    for etype in election_types:
        available_years = get_years(session, etype)
        target_years = [y for y in available_years if years is None or y in years]
        for year in target_years:
            for election in get_elections(session, etype, year):
                eid = election["electionId"]
                if eid not in seen:
                    seen.add(eid)
                    results.append(election)

    return results


# ---------------------------------------------------------------------------
# Candidate data
# ---------------------------------------------------------------------------

def is_filing_open(election: dict) -> bool:
    """
    Returns True if the filing period has started (or is a referendum with no
    filing period). Referendums always return True since they have no candidates
    regardless — the caller should handle the empty result.
    """
    begin = election.get("filingPeriodBeginDate")
    if begin is None:
        return True  # referendum — will return 0 rows naturally
    try:
        filing_dt = datetime.fromisoformat(begin).replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= filing_dt
    except Exception:
        return True  # assume open if unparseable


def get_candidates(session, election_id: str | int) -> list[dict]:
    """
    POST /Candidate/CandidateSearch/

    Fetches all candidates for a given electionId. Returns empty list if:
      - Filing period has not opened yet
      - Election is a referendum (no candidates)

    Returns list of dicts with keys:
      candidate_id, candidate_detail_id, office, associated_counties,
      name_on_ballot, running_mate, party, filing_location, status
    """
    resp = session.post(
        f"{BASE}/Candidate/CandidateSearch/",
        data={
            "ElectionId": str(election_id),
            "ExportFileName": f"Candidates_{election_id}",
            "SelectedOffice": "-1",
            "SelectedCandidateStatus": "All",
            "CandidateFirstName": "",
            "CandidateLastName": "",
            "SelectedPoliticalParty": "All",
            "SelectedFilingLocation": "All",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=30,
    )
    resp.raise_for_status()
    return _parse_candidate_table(resp.text)


def _parse_candidate_table(html: str) -> list[dict]:
    """
    Parse <table id="gridCandidateSearch"> from HTML fragment.

    Columns (confirmed order):
      0: Office
      1: Associated Counties
      2: Name on Ballot  (contains <a href="CandidateDetail/?candidateId=...&electionId=...">)
      3: Running Mate
      4: Party
      5: Location of Filing
      6: Candidate Status
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "gridCandidateSearch"})
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    candidates = []
    for row in tbody.find_all("tr"):
        candidate_id = row.get("data-key")
        cells = row.find_all("td")
        if len(cells) < 7:
            continue

        name_link = cells[2].find("a")
        name = name_link.get_text(strip=True) if name_link else cells[2].get_text(strip=True)

        # candidateId in the CandidateDetail href
        detail_cid = None
        detail_eid = None
        if name_link and name_link.get("href"):
            m = re.search(r"candidateId=(\d+)", name_link["href"])
            if m:
                detail_cid = m.group(1)
            m2 = re.search(r"electionId=(\d+)", name_link["href"])
            if m2:
                detail_eid = m2.group(1)

        candidates.append({
            "candidate_id": candidate_id,
            "candidate_detail_id": detail_cid or candidate_id,
            # Note: detail_election_id links to the General election record
            # even when searching within a Primary — intentional system behavior
            "candidate_detail_election_id": detail_eid,
            "office": cells[0].get_text(strip=True),
            "associated_counties": cells[1].get_text(strip=True),
            "name_on_ballot": name,
            "running_mate": cells[3].get_text(strip=True),
            "party": cells[4].get_text(strip=True),
            "filing_location": cells[5].get_text(strip=True),
            "status": cells[6].get_text(strip=True),
        })

    return candidates


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

def scrape_all(election_types=None, years=None, skip_empty_filing=True) -> list[dict]:
    """
    Full sweep: all types, all years (or filtered), all candidates.

    skip_empty_filing: if True, skip elections where filing hasn't started yet
    (avoids unnecessary requests that will return 0 rows).

    Returns flat list of candidate dicts, each augmented with election metadata.
    """
    session = get_session()
    elections = get_all_elections(session, election_types=election_types, years=years)

    all_candidates = []
    for election in elections:
        eid = election["electionId"]

        if skip_empty_filing and not is_filing_open(election):
            print(f"  SKIP  [{eid}] {election['displayName']} — filing not open until {election['filingPeriodBeginDate']}")
            continue

        candidates = get_candidates(session, eid)
        print(f"  {'OK' if candidates else 'EMPTY':5} [{eid}] {election['displayName']} — {len(candidates)} candidates")

        for c in candidates:
            c.update({
                "election_id": eid,
                "election_name": election["electionName"],
                "election_date": election["electionDate"],
                "election_type": election["electionType"],
                "filing_period_begin": election.get("filingPeriodBeginDate"),
            })
        all_candidates.extend(candidates)

    return all_candidates


def scrape_upcoming(cutoff_date=None) -> list[dict]:
    """
    Scrape only elections on or after cutoff_date (ISO string, e.g. '2026-05-24').
    Defaults to today. Sweeps all three election types for the current year.
    """
    from datetime import date
    if cutoff_date is None:
        cutoff_date = date.today().isoformat()

    session = get_session()
    current_year = date.today().year
    elections = get_all_elections(session, years=[current_year])

    upcoming = [e for e in elections if e["electionDate"][:10] >= cutoff_date]
    print(f"Found {len(upcoming)} elections on or after {cutoff_date}")

    all_candidates = []
    for election in upcoming:
        eid = election["electionId"]
        if not is_filing_open(election):
            print(f"  SKIP  [{eid}] {election['displayName']} — filing opens {election['filingPeriodBeginDate'][:10]}")
            continue
        candidates = get_candidates(session, eid)
        print(f"  {'OK' if candidates else 'EMPTY':5} [{eid}] {election['displayName']} — {len(candidates)} candidates")
        for c in candidates:
            c.update({
                "election_id": eid,
                "election_name": election["electionName"],
                "election_date": election["electionDate"],
                "election_type": election["electionType"],
            })
        all_candidates.extend(candidates)

    return all_candidates


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("=== SC VREMS Scraper — Upcoming Elections ===\n")
    candidates = scrape_upcoming()

    print(f"\nTotal candidates fetched: {len(candidates)}")

    by_election = {}
    for c in candidates:
        key = f"[{c['election_id']}] {c['election_name']} ({c['election_date'][:10]})"
        by_election.setdefault(key, []).append(c)

    print("\nSummary by election:")
    for label, cands in sorted(by_election.items()):
        offices = len(set(c["office"] for c in cands))
        print(f"  {label}: {len(cands)} candidates, {offices} offices")

    out_path = "sc_vrems_candidates.json"
    with open(out_path, "w") as f:
        json.dump(candidates, f, indent=2)
    print(f"\nSaved to {out_path}")
