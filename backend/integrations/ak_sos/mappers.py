"""
Parse elections.alaska.gov/election-candidates/ search-result HTML into
normalized candidate records.

Confirmed live 2026-11-03: the "Contest" field's selected value has no
effect on which contests appear in the result -- every search, regardless
of contest chosen, returns the full candidate roster for the selected
Election (55 <h4> headings total: 2 page-intro headings, then one
<h4>+<table class="...frm-grid..."> pair per contest). So the client only
needs to search once per election (see tasks.py); this module then walks
every heading in the returned HTML and keeps the ones recognized as
in-scope office titles via OFFICE_TITLE_FOR.

Office titles are normalized to match results/adapters/ak.py's conventions
exactly (both the raw ENR CSV contest names and that adapter's own
District renaming), so Stage 1's Races and Stage 2's results rows resolve
to the same office_title and match up automatically:
    "GOVERNOR / LIEUTENANT GOVERNOR" -> "Governor / Lieutenant Governor"
    "UNITED STATES SENATOR"          -> "U.S. Senator"
    "UNITED STATES REPRESENTATIVE"   -> "U.S. Representative"
    "STATE HOUSE DISTRICT 01"        -> "State House - District 1"   (zero-padding stripped)
    "STATE SENATE DISTRICT A"        -> "State Senate - District A"

Judicial contests (District/Superior/Supreme Court) are selectable in the
site's own Contest dropdown but never appear with actual rows on this page
in practice -- Alaska's judges face retention votes, not head-to-head
candidate races -- and OFFICE_TITLE_FOR returns None for them regardless,
consistent with results/adapters/ak.py excluding retention contests.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

# Confirmed live: searching with any of these (or any other in-scope value)
# returns the identical full roster -- see module docstring. Governor is
# used as the fixed default in tasks.py simply because it's first in the
# site's own Contest dropdown.
CONTESTS_IN_SCOPE: tuple[str, ...] = (
    "GOVERNOR / LIEUTENANT GOVERNOR",
    "STATE REPRESENTATIVE",
    "STATE SENATOR",
    "UNITED STATES REPRESENTATIVE",
    "UNITED STATES SENATOR",
)

_GOVERNOR_HEADING = "GOVERNOR / LIEUTENANT GOVERNOR"
_US_SENATOR_HEADING = "UNITED STATES SENATOR"
_US_REP_HEADING = "UNITED STATES REPRESENTATIVE"
_HOUSE_HEADING_RE = re.compile(r'^STATE HOUSE DISTRICT (\d+)$')
_SENATE_HEADING_RE = re.compile(r'^STATE SENATE DISTRICT ([A-Z])$')

_PARTY_STATUS_RE = re.compile(r'^\((.*?)\)(?:\s*\((.*?)\))?$')


def office_title_for(heading: str) -> str | None:
    """Normalize a results page <h4> heading to this adapter's office_title
    convention, or None if the heading is out of scope (judicial, or one of
    the two non-contest intro headings every page carries)."""
    heading = " ".join(heading.strip().split())
    if heading == _GOVERNOR_HEADING:
        return "Governor / Lieutenant Governor"
    if heading == _US_SENATOR_HEADING:
        return "U.S. Senator"
    if heading == _US_REP_HEADING:
        return "U.S. Representative"
    match = _HOUSE_HEADING_RE.match(heading)
    if match:
        return f"State House - District {int(match.group(1))}"
    match = _SENATE_HEADING_RE.match(heading)
    if match:
        return f"State Senate - District {match.group(1)}"
    return None


def _primary_party(party_full: str, office_title: str) -> str:
    """
    For a Governor/Lt. Governor ticket, this page's party text can be two
    parties joined by " / " (e.g. "Registered Republican / Registered
    Democrat" on a split-ticket pair) -- confirmed live on the 2026 filing
    list. aggregation.ingest.ingest_candidate derives Candidate.normalized_party
    from whatever party string it's given, uppercased with no further
    shortening when the text isn't a recognized code, and that column is
    only 40 chars (elections.models.Candidate.normalized_party) -- long
    enough for a single party's name but not two joined together, which
    raised django.db.utils.DataError in production the first time this ran
    against a real split ticket. Reducing to just the gubernatorial
    candidate's own party keeps it meaningful and under the limit; the full
    two-party text survives in source_metadata (see map_candidate).
    """
    if office_title == "Governor / Lieutenant Governor" and " / " in party_full:
        return party_full.split(" / ", 1)[0].strip()
    return party_full


def normalize_candidate_name(raw_name: str, office_title: str) -> str:
    """
    Normalize this page's ballot name to the same string the results
    adapter's candidate_name will carry, so results.tasks can attach
    incoming OfficialResult rows to the Candidate this creates by exact
    name match.

    Every office except Governor: "Last, First Middle Suffix" -> "First
    Middle Suffix Last" (same reversal convention as
    integrations.az_sos.mappers.normalize_candidate_name and
    results/adapters/ak.py's own _reverse_name).

    Governor / Lieutenant Governor is the one exception. This page gives
    the full ticket as "Bronson, Dave / Church, Josh", but Alaska's ENR
    results feed (results/adapters/ak.py) only ever reports a ticket as
    bare surnames joined with "/" and no spaces: "Bronson/Church". Applying
    the normal single-comma reversal to the whole ticket string would
    garble it, and keeping the full-name form would never match the
    results row at all -- so this reduces the ticket to the same
    surnames-only form the results feed uses.
    """
    if office_title == "Governor / Lieutenant Governor":
        surnames = [person.split(",", 1)[0].strip() for person in raw_name.split("/")]
        return "/".join(surnames)
    name = raw_name.strip()
    if "," in name:
        last, _, first = name.partition(",")
        name = f"{first.strip()} {last.strip()}".strip()
    return name


def _party_and_status(small_text: str) -> tuple[str, str]:
    """"(Registered Republican) (Certified)" -> ("Registered Republican", "Certified").
    A withdrawn candidate's cell carries only the party, no status paren."""
    match = _PARTY_STATUS_RE.match(small_text.strip())
    if not match:
        return small_text.strip(), ""
    return match.group(1).strip(), (match.group(2) or "").strip()


def candidate_status_for(status_raw: str, withdrawn: bool) -> str:
    """
    Map the page's status text to Candidate.CandidateStatus. Withdrawn (a
    separate badge on the name, not part of the status text) always wins.
    "Denied" covers plain denials and the observed data quirk where a second
    note is appended with no separator ("DeniedNo POFD on file") -- a
    prefix match, not equality, so any such note still maps correctly.
    Unknown/future status text defaults to "running" (least-destructive
    default, same convention as every other state's Stage 1 adapter).
    """
    if withdrawn:
        return "withdrawn"
    if status_raw.strip().lower().startswith("denied"):
        return "disqualified"
    return "running"


def _cell_text(cell) -> str:
    return cell.get_text(" ", strip=True)


def parse_candidates_html(html: str) -> list[dict]:
    """
    Parse one election-candidates search result page into a flat list of
    candidate dicts: {office_title, name, party, status_raw, candidate_status,
    incumbent, withdrawn, address, phone, email}.

    One dict per ballot line -- a Governor/Lt. Governor ticket's "name" is
    the page's own combined "First Last / First Last" string, matching how
    results/adapters/ak.py passes that ticket through unchanged.
    """
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict] = []

    for heading in soup.find_all("h4"):
        office_title = office_title_for(heading.get_text(strip=True))
        if office_title is None:
            continue
        table = heading.find_next_sibling("table")
        if table is None:
            continue

        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            name_cell, address_cell, contact_cell = cells[0], cells[1], cells[2]

            withdrawn_span = name_cell.find("span")
            withdrawn = bool(withdrawn_span and withdrawn_span.get_text(strip=True) == "Withdrawn")

            strong = name_cell.find("strong")
            ballot_name = strong.get_text(strip=True) if strong else ""
            if not ballot_name:
                continue
            name = normalize_candidate_name(ballot_name, office_title)

            small = name_cell.find("small")
            party_full, status_raw = _party_and_status(small.get_text(strip=True)) if small else ("", "")
            party = _primary_party(party_full, office_title)

            incumbent_tag = name_cell.find("em")
            incumbent = bool(incumbent_tag and incumbent_tag.get_text(strip=True) == "Incumbent")

            email_link = contact_cell.find("a")
            email = email_link.get_text(strip=True) if email_link else ""
            phone = _cell_text(contact_cell).replace(email, "").replace("Email:", "").strip()

            records.append({
                "office_title": office_title,
                "name": name,
                "ballot_name": ballot_name,
                "party": party,
                "party_full": party_full,
                "status_raw": status_raw,
                "candidate_status": candidate_status_for(status_raw, withdrawn),
                "incumbent": incumbent,
                "withdrawn": withdrawn,
                "address": _cell_text(address_cell),
                "phone": phone,
                "email": email,
            })

    return records


def map_race_identity(office_title: str) -> tuple[dict, dict]:
    """Return (identity, fields) for aggregation.ingest.ingest_race.

    geography_scope reuses elections.geography.infer_geography_scope --
    the same classifier results/tasks.py's bootstrap path uses for races
    created straight from the results feed -- so a Stage 1 race and a
    bootstrap-fallback race for the same office always agree.
    """
    from elections.geography import infer_geography_scope
    from elections.models import Race

    variant = f"ak:{office_title}"
    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "Alaska",
        "geography_scope": infer_geography_scope(office_title),
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "source": Race.Source.AK_SOS,
        "source_metadata": {
            "provider": "ak_sos",
            "office": office_title,
            "contest_variant": variant,
        },
    }
    return identity, fields


def map_candidate(record: dict) -> dict:
    """Return Candidate model fields for aggregation.ingest.ingest_candidate."""
    return {
        "candidate_status": record["candidate_status"],
        "incumbent": record["incumbent"],
        "contact_phone": record["phone"],
        "contact_office": record["address"],
        "source_metadata": {
            "provider": "ak_sos",
            "ak_status": record["status_raw"],
            "ak_ballot_name": record["ballot_name"],
            "ak_party_full": record["party_full"],
            "email": record["email"],
        },
    }
