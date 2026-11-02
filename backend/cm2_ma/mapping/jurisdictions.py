import re

from cm2_ingestion.contracts import JurisdictionRecord

from .identity import stable_public_id

_STATE = JurisdictionRecord(
    public_id=stable_public_id("jurisdiction", "state", "Massachusetts"),
    name="Massachusetts",
    classification="state",
    state="MA",
    record_status="verified",
    source_key="MA",
)

# Secretary h2 office label -> JurisdictionRecord.classification for its
# district-level (h3) jurisdictions. Offices not listed here never appear
# with a district_label (all statewide).
_OFFICE_CLASSIFICATION: dict[str, str] = {
    "Representative in Congress": "congressional_district",
    "Councillor": "councillor_district",
    "Senator in General Court": "state_senate_district",
    "Representative in General Court": "state_house_district",
    "District Attorney": "district_attorney_district",
    "Register of Probate": "county",
    "County Treasurer": "county",
    "County Commissioner": "county",
    "Sheriff": "county",
}


def _office_key(office_label: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", office_label).strip()


def map_jurisdiction(office_label: str, district_label: str | None) -> tuple[JurisdictionRecord, ...]:
    if district_label is None:
        return (_STATE,)

    classification = _OFFICE_CLASSIFICATION.get(_office_key(office_label), "other")
    district = JurisdictionRecord(
        public_id=stable_public_id("jurisdiction", classification, district_label),
        name=district_label,
        classification=classification,
        state="MA",
        parent_public_id=_STATE.public_id,
        record_status="provisional",
        source_key=f"MA:{classification}:{district_label}",
    )
    return (_STATE, district)
