from cm2_ma.mapping.office_crosswalk import resolve_district_code
from cm2_ma.source_records import OcpfDistrict

# Real rows, captured live from district_code_list.txt during design.
_DISTRICTS = {
    1114: OcpfDistrict(district_code=1114, office_type="Statewide", district_description="Auditor"),
    231: OcpfDistrict(district_code=231, office_type="House", district_description="9th Essex"),
    363: OcpfDistrict(district_code=363, office_type="House", district_description="18th Worcester"),
    1107: OcpfDistrict(district_code=1107, office_type="Governor's Council", district_description="7th District"),
    602: OcpfDistrict(district_code=602, office_type="District Attorney", district_description="Berkshire District - Berkshire County"),
    614: OcpfDistrict(district_code=614, office_type="District Attorney", district_description="Middle District"),
    705: OcpfDistrict(district_code=705, office_type="Treasurer", district_description="Essex County"),
    # Senate: OCPF's PRE-2021 name for what the Secretary now calls
    # "Third Bristol and Plymouth District" (Massachusetts Senate District D36 --
    # verified against the Legislature's own Senate Map Key).
    104: OcpfDistrict(district_code=104, office_type="Senate", district_description="1st Plymouth & Bristol"),
    # OCPF's PRE-2021 name for D01, now "Berkshire, Hampden, Franklin and Hampshire".
    154: OcpfDistrict(district_code=154, office_type="Senate", district_description="Berkshire, Hampshire, Franklin & Hampden"),
}


def test_statewide_office_matches_by_identity_name():
    code = resolve_district_code(office_label="Auditor", district_label=None, districts=_DISTRICTS)
    assert code == 1114


def test_house_district_strips_suffix_and_abbreviates_ordinal():
    code = resolve_district_code(
        office_label="Representative in General Court", district_label="Ninth Essex District", districts=_DISTRICTS
    )
    assert code == 231


def test_governors_council_keeps_district_suffix():
    code = resolve_district_code(office_label="Councillor", district_label="Seventh District", districts=_DISTRICTS)
    assert code == 1107


def test_district_attorney_matches_as_prefix_before_county_suffix():
    code = resolve_district_code(
        office_label="District Attorney", district_label="Berkshire District", districts=_DISTRICTS
    )
    assert code == 602


def test_district_attorney_middle_district_has_no_county_suffix():
    code = resolve_district_code(office_label="District Attorney", district_label="Middle District", districts=_DISTRICTS)
    assert code == 614


def test_county_treasurer_maps_to_ocpf_treasurer_office_type():
    code = resolve_district_code(office_label="County Treasurer", district_label="Essex County", districts=_DISTRICTS)
    assert code == 705


def test_senate_district_translates_current_name_to_pre_2021_ocpf_name():
    code = resolve_district_code(
        office_label="Senator in General Court",
        district_label="Third Bristol & Plymouth District",
        districts=_DISTRICTS,
    )
    assert code == 104


def test_senate_district_translates_multi_county_current_name():
    code = resolve_district_code(
        office_label="Senator in General Court",
        district_label="Berkshire, Hampden, Franklin & Hampshire District",
        districts=_DISTRICTS,
    )
    assert code == 154


def test_federal_office_never_resolves():
    code = resolve_district_code(
        office_label="Representative in Congress", district_label="First District", districts=_DISTRICTS
    )
    assert code is None


def test_unresolvable_house_district_returns_none_not_error():
    # The one confirmed real gap: Secretary lists a 19th Worcester House
    # district; OCPF's table (verified live) only goes to 18th.
    code = resolve_district_code(
        office_label="Representative in General Court",
        district_label="Nineteenth Worcester District",
        districts=_DISTRICTS,
    )
    assert code is None


def test_sheriff_strips_vacancy_qualifier_from_office_label():
    districts = dict(_DISTRICTS)
    districts[900] = OcpfDistrict(district_code=900, office_type="Sheriff", district_description="Franklin County")
    code = resolve_district_code(
        office_label="Sheriff (to fill a vacancy)", district_label="Franklin County", districts=districts
    )
    assert code == 900
