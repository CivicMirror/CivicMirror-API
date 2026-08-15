import re

from cm2_ingestion.contracts import JurisdictionRecord, OfficeRecord

from .identity import stable_public_id


def _title_name(value: str) -> str:
    return " ".join(value.title().split())


def _strip_unexpired(contest_name: str) -> str:
    normalized = " ".join((contest_name or "").strip().upper().split())
    return re.sub(r"\s*\(UNEXPIRED\)$", "", normalized).strip()


def _office_name(contest: str, jurisdiction: JurisdictionRecord) -> str:
    if contest == "US SENATE":
        return "U.S. Senator"
    if contest.startswith("US HOUSE OF REPRESENTATIVES DISTRICT "):
        return "U.S. Representative"
    if contest.startswith("NC STATE SENATE DISTRICT "):
        return "North Carolina State Senator"
    if contest.startswith("NC HOUSE OF REPRESENTATIVES DISTRICT "):
        return "North Carolina State Representative"

    district_judge = re.match(r"^NC DISTRICT COURT JUDGE DISTRICT [0-9A-Z]+( SEAT [0-9A-Z]+)?$", contest)
    if district_judge:
        return f"District Court Judge{district_judge.group(1) or ''}".title().replace("Court Judge", "Court Judge")
    superior_judge = re.match(r"^NC SUPERIOR COURT JUDGE DISTRICT [0-9A-Z]+( SEAT [0-9A-Z]+)?$", contest)
    if superior_judge:
        return f"Superior Court Judge{superior_judge.group(1) or ''}".title().replace("Court Judge", "Court Judge")
    if contest.startswith("DISTRICT ATTORNEY DISTRICT "):
        return "District Attorney"

    if contest.startswith("NC SUPREME COURT "):
        return _title_name(contest.removeprefix("NC "))
    if contest.startswith("NC COURT OF APPEALS "):
        return _title_name(contest.removeprefix("NC "))

    if jurisdiction.classification == "county":
        county_prefix = jurisdiction.name.upper()
        remainder = contest.removeprefix(county_prefix).strip()
        if remainder == "BOARD OF COMMISSIONERS":
            return "County Commissioner"
        return _title_name(remainder or contest)

    if jurisdiction.classification == "school_district":
        _, _, suffix = contest.partition("BOARD OF EDUCATION")
        return f"Board of Education Member {_title_name(suffix)}".strip()

    if jurisdiction.classification == "municipality":
        prefix = jurisdiction.name.upper()
        remainder = contest.removeprefix(prefix).strip()
        return _title_name(remainder or contest)

    if "SOIL AND WATER CONSERVATION DISTRICT" in contest:
        return "Soil and Water Conservation District Supervisor"
    if "SANITARY" in contest:
        if "BOARD MEMBER" in contest:
            return "Sanitary District Board Member"
        if "SUPERVISOR" in contest:
            return "Sanitary District Supervisor"

    return _title_name(contest)


def _role(office_name: str) -> str:
    normalized = office_name.casefold()
    for token, role in (
        ("senator", "senator"),
        ("representative", "representative"),
        ("justice", "justice"),
        ("judge", "judge"),
        ("mayor", "mayor"),
        ("commissioner", "commissioner"),
        ("sheriff", "sheriff"),
        ("clerk", "clerk"),
        ("board", "board_member"),
        ("supervisor", "supervisor"),
    ):
        if token in normalized:
            return role
    return "elected_official"


def map_office(
    contest_name: str,
    jurisdiction: JurisdictionRecord,
    *,
    term_years: int,
    vote_for: int,
) -> OfficeRecord:
    del vote_for
    contest = _strip_unexpired(contest_name)
    canonical_name = _office_name(contest, jurisdiction)
    return OfficeRecord(
        public_id=stable_public_id("office", jurisdiction.public_id, canonical_name),
        jurisdiction_public_id=jurisdiction.public_id,
        canonical_name=canonical_name,
        role=_role(canonical_name),
        default_term_months=term_years * 12,
        positions=1,
        record_status="provisional",
        source_key=contest,
    )
