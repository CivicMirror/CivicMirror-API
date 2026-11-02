import re

from cm2_ingestion.contracts import JurisdictionRecord, OfficeRecord

from .identity import stable_public_id

# Secretary h2 text that needs normalizing into a cleaner canonical office
# name. Every other office label already reads as a good office name as-is
# (e.g. "Governor", "District Attorney", "Register of Probate").
_OFFICE_NAME_MAP: dict[str, str] = {
    "Senator in Congress": "U.S. Senator",
    "Representative in Congress": "U.S. Representative",
    "Councillor": "Governor's Councillor",
    "Senator in General Court": "State Senator",
    "Representative in General Court": "State Representative",
}

_ROLE_KEYWORDS = (
    ("senator", "senator"),
    ("representative", "representative"),
    ("governor", "governor"),
    ("attorney general", "attorney_general"),
    ("secretary", "secretary"),
    ("treasurer", "treasurer"),
    ("auditor", "auditor"),
    ("councillor", "councillor"),
    ("district attorney", "district_attorney"),
    ("register", "register"),
    ("commissioner", "commissioner"),
    ("sheriff", "sheriff"),
)


def _office_key(office_label: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", office_label).strip()


def _role(canonical_name: str) -> str:
    normalized = canonical_name.casefold()
    for keyword, role in _ROLE_KEYWORDS:
        if keyword in normalized:
            return role
    return "elected_official"


def map_office(office_label: str, jurisdiction: JurisdictionRecord) -> OfficeRecord:
    office_key = _office_key(office_label)
    canonical_name = _OFFICE_NAME_MAP.get(office_key, office_key)
    return OfficeRecord(
        public_id=stable_public_id("office", jurisdiction.public_id, canonical_name),
        jurisdiction_public_id=jurisdiction.public_id,
        canonical_name=canonical_name,
        role=_role(canonical_name),
        positions=1,
        record_status="provisional",
        source_key=office_key,
    )
