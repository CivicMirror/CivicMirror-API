from cm2_ma.mapping.jurisdictions import map_jurisdiction
from cm2_ma.mapping.offices import map_office


def test_statewide_office_maps_to_the_state_singleton_jurisdiction():
    jurisdictions = map_jurisdiction("Governor", None)

    assert len(jurisdictions) == 1
    assert jurisdictions[0].classification == "state"
    assert jurisdictions[0].name == "Massachusetts"


def test_district_office_maps_to_state_plus_a_child_jurisdiction():
    jurisdictions = map_jurisdiction("Representative in General Court", "9th Essex District")

    assert len(jurisdictions) == 2
    state, district = jurisdictions
    assert state.classification == "state"
    assert district.classification == "state_house_district"
    assert district.name == "9th Essex District"
    assert district.parent_public_id == state.public_id


def test_county_row_office_is_classified_as_county():
    jurisdictions = map_jurisdiction("Register of Probate", "Barnstable County")

    district = jurisdictions[-1]
    assert district.classification == "county"
    assert district.name == "Barnstable County"


def test_jurisdiction_identity_is_stable_across_calls():
    first = map_jurisdiction("District Attorney", "Suffolk District")
    second = map_jurisdiction("District Attorney", "Suffolk District")

    assert first[-1].public_id == second[-1].public_id


def test_office_name_is_normalized_for_congress_and_general_court():
    jurisdiction = map_jurisdiction("Senator in General Court", "First Essex District")[-1]
    office = map_office("Senator in General Court", jurisdiction)

    assert office.canonical_name == "State Senator"


def test_office_name_passes_through_when_already_clean():
    jurisdiction = map_jurisdiction("Register of Probate", "Essex County")[-1]
    office = map_office("Register of Probate", jurisdiction)

    assert office.canonical_name == "Register of Probate"


def test_office_strips_vacancy_qualifier_from_sheriff():
    jurisdiction = map_jurisdiction("Sheriff (to fill a vacancy)", "Franklin County")[-1]
    office = map_office("Sheriff (to fill a vacancy)", jurisdiction)

    assert office.canonical_name == "Sheriff"
