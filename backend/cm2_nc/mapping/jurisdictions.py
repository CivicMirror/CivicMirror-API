import re

from cm2_ingestion.contracts import JurisdictionRecord

from .identity import stable_public_id

_STATEWIDE_PREFIXES = (
    "US SENATE",
    "GOVERNOR",
    "LIEUTENANT GOVERNOR",
    "ATTORNEY GENERAL",
    "SECRETARY OF STATE",
    "STATE TREASURER",
    "STATE AUDITOR",
    "COMMISSIONER OF AGRICULTURE",
    "COMMISSIONER OF INSURANCE",
    "COMMISSIONER OF LABOR",
    "SUPERINTENDENT OF PUBLIC INSTRUCTION",
    "NC SUPREME COURT",
    "NC COURT OF APPEALS",
)
_STATE = JurisdictionRecord(
    public_id=stable_public_id("jurisdiction", "state", "North Carolina"),
    name="North Carolina",
    classification="state",
    state="NC",
    record_status="verified",
    source_key="NC",
)


def _title_name(value: str) -> str:
    words = value.title().split()
    return " ".join(word.casefold() if index and word.casefold() in {"and", "of"} else word for index, word in enumerate(words))


def _child(*, name: str, classification: str, source_key: str) -> tuple[JurisdictionRecord, ...]:
    record = JurisdictionRecord(
        public_id=stable_public_id("jurisdiction", classification, name),
        name=name,
        classification=classification,
        state="NC",
        parent_public_id=_STATE.public_id,
        record_status="provisional",
        source_key=source_key,
    )
    return (_STATE, record)


def _school_district_name(contest_name: str) -> str | None:
    marker = " BOARD OF EDUCATION"
    if marker not in contest_name:
        return None
    prefix = contest_name.split(marker, 1)[0]
    prefix = re.sub(r"\s+(?:CITY|COUNTY)?\s*SCHOOLS$", "", prefix).strip()
    return f"{_title_name(prefix)} School District"


def _municipality_name(contest_name: str) -> str | None:
    prefix_match = re.match(
        r"^((?:CITY|TOWN|VILLAGE) OF .+?)(?: CITY COUNCIL| TOWN COUNCIL| VILLAGE COUNCIL| MAYOR| "
        r"COMMISSIONER| BOARD OF ALDERMEN| ALDERMEN| ALDERMAN| COUNCIL)",
        contest_name,
    )
    if prefix_match:
        return _title_name(prefix_match.group(1))
    suffix_match = re.match(r"^(.+? VILLAGE) (?:COUNCIL|COUNCILMAN|MAYOR)", contest_name)
    if suffix_match:
        return _title_name(suffix_match.group(1))
    return None


def map_jurisdiction(contest_name: str, county_name: str) -> tuple[JurisdictionRecord, ...]:
    contest = " ".join((contest_name or "").strip().upper().split())
    county = " ".join((county_name or "").strip().upper().split())

    congressional = re.match(r"^US HOUSE OF REPRESENTATIVES DISTRICT ([0-9A-Z]+)", contest)
    if congressional:
        district = congressional.group(1)
        return _child(
            name=f"North Carolina Congressional District {district}",
            classification="congressional_district",
            source_key=f"US HOUSE DISTRICT {district}",
        )

    legislative = re.match(r"^NC (STATE SENATE|HOUSE OF REPRESENTATIVES) DISTRICT ([0-9A-Z]+)", contest)
    if legislative:
        chamber, district = legislative.groups()
        chamber_name = "State Senate" if chamber == "STATE SENATE" else "House of Representatives"
        return _child(
            name=f"North Carolina {chamber_name} District {district}",
            classification="state_legislative_district",
            source_key=f"NC {chamber} DISTRICT {district}",
        )

    judicial = re.match(
        r"^(?:NC (?:DISTRICT|SUPERIOR) COURT JUDGE|DISTRICT ATTORNEY) DISTRICT ([0-9A-Z]+)",
        contest,
    )
    if judicial:
        district = judicial.group(1)
        return _child(
            name=f"North Carolina Judicial District {district}",
            classification="judicial_district",
            source_key=f"NC JUDICIAL DISTRICT {district}",
        )

    if contest.startswith(_STATEWIDE_PREFIXES):
        return (_STATE,)

    school_name = _school_district_name(contest)
    if school_name:
        return _child(
            name=school_name,
            classification="school_district",
            source_key=f"NC SCHOOL DISTRICT:{school_name.upper()}",
        )

    municipality_name = _municipality_name(contest)
    if municipality_name:
        return _child(
            name=municipality_name,
            classification="municipality",
            source_key=f"NC MUNICIPALITY:{municipality_name.upper()}",
        )

    soil_water = re.match(r"^(.+? SOIL AND WATER CONSERVATION DISTRICT)", contest)
    if soil_water:
        name = _title_name(soil_water.group(1))
        return _child(name=name, classification="other", source_key=f"NC DISTRICT:{name.upper()}")

    sanitary = re.match(r"^(.+? SANITARY(?: LAND)? DISTRICT)", contest)
    if sanitary:
        name = _title_name(sanitary.group(1))
        return _child(name=name, classification="other", source_key=f"NC DISTRICT:{name.upper()}")

    county_match = re.match(r"^(.+?) COUNTY\b", contest)
    if county_match:
        name = f"{_title_name(county_match.group(1))} County"
        return _child(name=name, classification="county", source_key=f"{county_match.group(1)} COUNTY")

    if county:
        return _child(
            name=f"{_title_name(county)} County",
            classification="county",
            source_key=f"{county} COUNTY",
        )

    return _child(name=_title_name(contest), classification="other", source_key=contest)
