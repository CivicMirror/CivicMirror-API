"""NC jurisdiction-first classification. Evidence confidence is never an identity key.

Municipality-specific calendar research is deliberately optional. Unknown November
municipal events use the approved inferred-general default; other unknown local
phases remain explicit holds rather than becoming fictitious specials.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

_EVIDENCE = Path(__file__).with_name("evidence")
_MUNICIPAL_NAMES = json.loads((_EVIDENCE / "municipality_names.json").read_text())
_SORTED_MUNICIPAL_NAMES = tuple(sorted(_MUNICIPAL_NAMES["names"], key=len, reverse=True))
MUNICIPAL_DATE_OVERRIDES = json.loads((_EVIDENCE / "municipal_dates.json").read_text())
RULE_VERSION = (
    "nc-classification-v1:"
    + hashlib.sha256(
        ((_EVIDENCE / "municipal_dates.json").read_bytes() + (_EVIDENCE / "municipality_names.json").read_bytes())
    ).hexdigest()[:12]
)
STATUTE = "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-1.html"
MUNICIPAL_STATUTE = "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-279.html"
FILING_SOURCE = "https://www.ncsbe.gov/results-data/candidate-lists"
_PRIMARIES = {
    2010: date(2010, 5, 4),
    2012: date(2012, 5, 8),
    2014: date(2014, 5, 6),
    2016: date(2016, 3, 15),
    2018: date(2018, 5, 8),
    2020: date(2020, 3, 3),
    2022: date(2022, 5, 17),
    2024: date(2024, 3, 5),
    2026: date(2026, 3, 3),
}
_SECONDS = {date(2010, 6, 22), date(2012, 7, 17), date(2014, 7, 15), date(2018, 6, 26), date(2024, 5, 14)}
_PARTY = re.compile(r"\s*(?:\((DEM|REP|LIB|GRN|GRE|CON|CST|WFP|UNA|IND)\)| - (DEM|REP|LIB|GRN|GRE|CON|CST))\s*$")
_OFFICE = r"(?:MAYOR|(?:CITY |TOWN |VILLAGE )?COUNCIL|COMMISSIONER|BOARD OF ALDERMEN|ALDERM[AE]N|TRUSTEE)"


def normalized_title(title: str) -> str:
    title = _PARTY.sub("", " ".join((title or "").upper().split()))
    return re.sub(
        r"^NC (?=(?:GOVERNOR|LIEUTENANT GOVERNOR|ATTORNEY GENERAL|SECRETARY OF STATE|"
        r"STATE TREASURER|STATE AUDITOR|COMMISSIONER OF|SUPERINTENDENT OF PUBLIC INSTRUCTION)\b)",
        "",
        title,
    )


def first_monday_tuesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(0 - first.weekday()) % 7 + 1)


def regular_phase(day: date) -> str | None:
    if day.year % 2:
        return None
    if day == first_monday_tuesday(day.year, 11):
        return "general"
    primary = _PRIMARIES.get(day.year)
    if primary is None and day.year > 2026:
        primary = first_monday_tuesday(day.year, 3)
    return "primary" if day == primary else None


def regular_dates(year: int) -> tuple[date, ...]:
    if year % 2:
        return ()
    primary = _PRIMARIES.get(year) or (first_monday_tuesday(year, 3) if year > 2026 else None)
    return tuple(d for d in (primary, first_monday_tuesday(year, 11)) if d)


def jurisdiction_for(title: str, county: str = "") -> tuple[str, str, str]:
    title = normalized_title(title)
    county = " ".join((county or "").upper().split())
    for pattern, kind, prefix in (
        (r"^US HOUSE OF REPRESENTATIVES DISTRICT (\w+)", "congressional_district", "congressional"),
        (r"^NC STATE SENATE DISTRICT (\w+)", "state_legislative_district", "state-senate"),
        (r"^NC HOUSE OF REPRESENTATIVES DISTRICT (\w+)", "state_legislative_district", "state-house"),
        (r"^NC (?:DISTRICT|SUPERIOR) COURT JUDGE DISTRICT (\w+)", "judicial_district", "judicial"),
        (r"^(?:NC )?DISTRICT ATTORNEY DISTRICT (\w+)", "judicial_district", "district-attorney"),
    ):
        match = re.match(pattern, title)
        if match:
            district = match[1].lstrip("0") or "0"
            return kind, f"{prefix}:{district}", f"North Carolina {prefix} district {district}"
    if re.match(
        r"^(?:US (?:SENATE|PRESIDENT)|PRESIDENT|GOVERNOR|LIEUTENANT GOVERNOR|ATTORNEY GENERAL|"
        r"SECRETARY OF STATE|STATE (?:TREASURER|AUDITOR)|COMMISSIONER OF |"
        r"SUPERINTENDENT OF PUBLIC INSTRUCTION|NC (?:SUPREME COURT|COURT OF APPEALS))",
        title,
    ):
        return "state", "state:NC", "North Carolina"
    body = re.sub(r"^(?:CITY|TOWN|VILLAGE) OF ", "", title)
    office = r"(?:(?:CITY|TOWN|VILLAGE) )?(?:MAYOR|COUNCIL\w*|COMMISSIONERS?|BOARD OF (?:ALDERMEN|COMMISSIONERS)|ALDERM[AE]N|TRUSTEES?)\b"
    for place in _SORTED_MUNICIPAL_NAMES:
        if body.startswith(place + " ") and re.match(office, body[len(place) + 1 :]):
            return "municipality", f"municipality:{place}", place.title()
    # Explicit school/special districts are not county electorates by default.
    if re.search(r"\b(?:PUBLIC SCHOOLS|CITY SCHOOLS|SCHOOL DISTRICT|SANITARY DISTRICT)\b", title):
        return "unknown", "", ""
    match = re.match(r"^(?:CITY|TOWN|VILLAGE) OF (.+?) (?=" + _OFFICE + r"\b)", title)
    if not match:
        match = re.match(r"^(.+?) (?=" + _OFFICE + r"\b)", title)
    if match and not re.search(r"\b(?:COUNTY|SCHOOL|SANITARY|DISTRICT|BOARD OF)\b", match[1]):
        place = match[1].strip()
        return "municipality", f"municipality:{place}", place.title()
    explicit_county = re.match(r"^(.+?) COUNTY (?:BOARD|COMMISSIONER|SHERIFF|REGISTER|CLERK|SCHOOL)", title)
    if explicit_county:
        county = explicit_county[1]
    if county and (
        explicit_county
        or re.match(
            r"^(?:COUNTYWIDE|SHERIFF|REGISTER OF DEEDS|CLERK OF|CORONER|(?:COUNTY )?BOARD OF|"
            r"COUNTY COMMISSIONER|SCHOOL BOARD|SOIL AND WATER)",
            title,
        )
    ):
        return "county", f"county:{county}", county.title() + " County"
    return "unknown", "", ""


@dataclass(frozen=True)
class NcClassification:
    jurisdiction_kind: str
    jurisdiction_key: str
    jurisdiction_name: str
    phase: str
    special_context: bool
    evidence_status: str
    reasons: tuple[str, ...]
    sources: tuple[str, ...]
    event_group: str
    election_type: str
    jurisdiction_level: str
    research_status: str = "not_required"
    rule_version: str = RULE_VERSION

    @property
    def resolved(self) -> bool:
        return self.evidence_status != "held"

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self)))


def classify_nc_contest(
    day: date,
    title: str,
    *,
    county: str = "",
    party_contest: str = "",
    is_unexpired: bool | str | None = None,
    identity_verified: bool | None = None,
    municipal_method: str | None = None,
) -> NcClassification:
    original = " ".join((title or "").upper().split())
    title = normalized_title(title)
    kind, jurisdiction, name = jurisdiction_for(title, county)
    partisan = bool(party_contest or _PARTY.search(original))
    reasons, sources = [], [STATUTE]
    invalid_flag = False
    if isinstance(is_unexpired, str):
        flag = is_unexpired.strip().upper()
        invalid_flag = flag not in {"", "TRUE", "FALSE"}
        is_unexpired = {"TRUE": True, "FALSE": False}.get(flag)
    special = bool(re.search(r"\bUNEXPIRED\b", title) or is_unexpired is True)
    if special:
        reasons.append("unexpired_title" if re.search(r"\bUNEXPIRED\b", title) else "unexpired_flag")
    phase = regular_phase(day)
    confirmed_special = False
    # Scoped exceptions from the reviewed inventory; no whole-date municipal rule.
    cd3 = title.startswith("US HOUSE OF REPRESENTATIVES DISTRICT 03") or jurisdiction == "congressional:3"
    cd9 = title.startswith("US HOUSE OF REPRESENTATIVES DISTRICT 09") or jurisdiction == "congressional:9"
    if (
        cd3
        and day in {date(2019, 4, 30), date(2019, 7, 9), date(2019, 9, 10)}
        or cd9
        and day in {date(2019, 5, 14), date(2019, 9, 10)}
    ):
        special = confirmed_special = True
        phase = "primary_runoff" if day == date(2019, 7, 9) else "general" if day == date(2019, 9, 10) else "primary"
        sources.append(
            f"https://www.fec.gov/updates/north-carolina-special-election-reporting-{3 if cd3 else 9}"
            f"{'rd' if cd3 else 'th'}-district-2019/"
        )
        reasons.append("official_special_schedule")
    elif day == date(2016, 6, 7) and kind in {"congressional_district", "state", "judicial_district"}:
        phase = "primary"
        reasons.append("2016_separate_primary")
        sources.append(
            "https://www.ncsbe.gov/blog/2016/02/26/"
            "numbered-memo-2016-03-information-regarding-march-15-and-june-7-primaries"
        )
    elif day in _SECONDS and (partisan or kind in {"state", "congressional_district", "state_legislative_district"}):
        phase = "primary_runoff"
        reasons.append("official_second_primary_date")
        sources.append(FILING_SOURCE)
    elif day == date(2020, 6, 23):
        if jurisdiction == "congressional:11":
            phase = "primary_runoff"
        elif title.startswith("COLUMBUS COUNTY BOARD OF COMMISSIONERS DISTRICT 02"):
            phase = "primary"
        if phase:
            reasons.append("2020_scoped_primary_notice")
            sources.append(
                "https://www.ncsbe.gov/blog/2020/06/01/numbered-memo-2020-12-covid-19-response-planning-person-voting"
            )
    if kind == "municipality":
        sources = [MUNICIPAL_STATUTE, *sources[1:]]
        # A state calendar says nothing about municipal nomination methods.
        phase = None
        if day == date(2023, 3, 7) and jurisdiction == "municipality:DOBSON":
            phase = "general"
            special = confirmed_special = True
            reasons.append("official_rerun")
            sources.append(
                "https://www.ncsbe.gov/news/press-releases/2022/12/19/"
                "state-board-orders-new-election-dobson-certifies-runoff-nash-and-edgecombe-counties"
            )
        elif day == date(2019, 9, 10) and jurisdiction == "municipality:CHARLOTTE":
            phase = "primary"
            reasons.append("official_charlotte_primary")
            sources.append(FILING_SOURCE)
        elif day.month == 11:
            phase = "general_runoff" if municipal_method == "election_runoff" else "general"
            reasons.append("municipal_method" if municipal_method else "municipal_november_default")
        elif municipal_method in {"primary_election", "partisan"} and day.month in {9, 10}:
            # Exact non-November dates must arrive in the follow-up registry.
            reasons.append("municipal_exact_date_required")
        overrides = [
            entry
            for entry in MUNICIPAL_DATE_OVERRIDES
            if entry.get("municipality", "").upper() == jurisdiction.removeprefix("municipality:")
            and entry.get("date") == day.isoformat()
        ]
        override_phases = {entry.get("phase") for entry in overrides}
        if overrides:
            if (
                len(override_phases) != 1
                or not override_phases <= {"primary", "primary_runoff", "general", "general_runoff"}
                or any(not entry.get("source_url") for entry in overrides)
            ):
                phase = None
                reasons.append("municipal_override_conflict")
            else:
                phase = next(iter(override_phases))
                reasons.append("municipal_date_override")
                sources.extend(entry["source_url"] for entry in overrides)
    status = "confirmed"
    research = "not_required"
    if special and not confirmed_special:
        status = "inferred"
    if (
        kind == "municipality"
        and not municipal_method
        and not confirmed_special
        and "official_charlotte_primary" not in reasons
        and "municipal_date_override" not in reasons
    ):
        status, research = "inferred", "pending"
    if day.year > 2026 and not reasons:
        status = "inferred"
    if kind == "unknown" or not phase or invalid_flag or identity_verified is False:
        status = "held"
        if kind == "unknown":
            reasons.append("jurisdiction_unresolved")
        if not phase:
            reasons.append("phase_unresolved")
        if invalid_flag:
            reasons.append("invalid_unexpired_flag")
        if identity_verified is False:
            reasons.append("electorate_unresolved")
    if not reasons:
        reasons.append("regular_calendar")
    local = kind in {"municipality", "county"}
    group = jurisdiction.lower() if local else ""
    if special:
        office = re.sub(r"\s*\(UNEXPIRED(?: TERM)?\)|\bUNEXPIRED(?: TERM)?\b", "", title).strip()
        office_hash = hashlib.sha256(office.encode()).hexdigest()[:16]
        group = f"{jurisdiction.lower()}:special:{office_hash}"
    etype = phase or "other"
    if phase == "general":
        etype = "special" if special else "municipal" if kind == "municipality" else "general"
    return NcClassification(
        kind,
        jurisdiction,
        name,
        phase or "unknown",
        special,
        status,
        tuple(reasons),
        tuple(sources),
        group,
        etype,
        "local" if local else "state",
        research,
    )
