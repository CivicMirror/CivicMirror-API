from datetime import date

import pytest


@pytest.mark.parametrize(
    "day,title,county,party,unexpired,phase,kind,special,status",
    [
        (
            date(2026, 3, 3),
            "NC STATE SENATE DISTRICT 01",
            "",
            "REP",
            False,
            "primary",
            "state_legislative_district",
            False,
            "confirmed",
        ),
        (date(2026, 11, 3), "GOVERNOR", "", "", False, "general", "state", False, "confirmed"),
        (
            date(2026, 11, 3),
            "NC SUPREME COURT ASSOCIATE JUSTICE (UNEXPIRED)",
            "",
            "",
            None,
            "general",
            "state",
            True,
            "inferred",
        ),
        (
            date(2026, 3, 3),
            "US HOUSE OF REPRESENTATIVES DISTRICT 03",
            "",
            "REP",
            True,
            "primary",
            "congressional_district",
            True,
            "inferred",
        ),
        (
            date(2019, 7, 9),
            "US HOUSE OF REPRESENTATIVES DISTRICT 03 (REP)",
            "",
            "",
            True,
            "primary_runoff",
            "congressional_district",
            True,
            "confirmed",
        ),
        (
            date(2019, 9, 10),
            "US HOUSE OF REPRESENTATIVES DISTRICT 09",
            "",
            "",
            False,
            "general",
            "congressional_district",
            True,
            "confirmed",
        ),
        (
            date(2020, 6, 23),
            "COLUMBUS COUNTY BOARD OF COMMISSIONERS DISTRICT 02 (REP)",
            "COLUMBUS",
            "",
            False,
            "primary",
            "county",
            False,
            "confirmed",
        ),
        (
            date(2020, 6, 23),
            "US HOUSE OF REPRESENTATIVES DISTRICT 11 (REP)",
            "",
            "",
            False,
            "primary_runoff",
            "congressional_district",
            False,
            "confirmed",
        ),
        (
            date(2025, 11, 4),
            "CITY OF CHARLOTTE MAYOR",
            "MECKLENBURG",
            "",
            False,
            "general",
            "municipality",
            False,
            "inferred",
        ),
        (date(2025, 10, 7), "CITY OF ASHEVILLE MAYOR", "BUNCOMBE", "", False, "unknown", "municipality", False, "held"),
        (date(2026, 11, 3), "SHERIFF", "WAKE", "", False, "general", "county", False, "confirmed"),
        (date(2025, 11, 4), "MURPHY MAYOR", "CHEROKEE", "", False, "general", "municipality", False, "inferred"),
        (
            date(2023, 3, 7),
            "TOWN OF DOBSON COMMISSIONER",
            "SURRY",
            "",
            False,
            "general",
            "municipality",
            True,
            "confirmed",
        ),
    ],
)
def test_classification_preserves_jurisdiction_phase_and_evidence(
    day,
    title,
    county,
    party,
    unexpired,
    phase,
    kind,
    special,
    status,
):
    from integrations.nc_sbe.classification import classify_nc_contest

    result = classify_nc_contest(day, title, county=county, party_contest=party, is_unexpired=unexpired)
    assert (result.phase, result.jurisdiction_kind, result.special_context, result.evidence_status) == (
        phase,
        kind,
        special,
        status,
    )


def test_calendar_does_not_treat_first_tuesday_or_any_march_date_as_primary():
    from integrations.nc_sbe.classification import regular_phase

    assert regular_phase(date(2022, 11, 1)) is None
    assert regular_phase(date(2022, 11, 8)) == "general"
    assert regular_phase(date(2026, 3, 17)) is None
    assert regular_phase(date(2022, 3, 8)) is None  # 2022 primary was postponed.


def test_special_primary_keeps_nomination_type_and_has_separate_event_identity():
    from integrations.nc_sbe.classification import classify_nc_contest

    regular = classify_nc_contest(date(2026, 3, 3), "US HOUSE OF REPRESENTATIVES DISTRICT 03")
    special = classify_nc_contest(date(2026, 3, 3), "US HOUSE OF REPRESENTATIVES DISTRICT 03", is_unexpired=True)
    other = classify_nc_contest(date(2026, 3, 3), "US HOUSE OF REPRESENTATIVES DISTRICT 09", is_unexpired=True)
    assert special.election_type == "primary"
    assert regular.event_group == ""
    assert special.event_group != regular.event_group
    assert special.event_group != other.event_group


def test_municipal_november_method_override_and_confidence_do_not_mint_duplicate_identity():
    from integrations.nc_sbe.classification import classify_nc_contest

    inferred = classify_nc_contest(date(2025, 11, 4), "CITY OF ROCKY MOUNT MAYOR")
    confirmed = classify_nc_contest(date(2025, 11, 4), "CITY OF ROCKY MOUNT MAYOR", municipal_method="plurality")
    runoff = classify_nc_contest(date(2025, 11, 4), "CITY OF ROCKY MOUNT MAYOR", municipal_method="election_runoff")
    assert inferred.phase == confirmed.phase == "general"
    assert inferred.evidence_status == "inferred"
    assert confirmed.evidence_status == "confirmed"
    assert inferred.event_group == confirmed.event_group
    assert runoff.phase == "general_runoff"
    assert runoff.election_type == "general_runoff"


def test_unknown_identity_and_invalid_flags_are_held_without_inventing_a_county():
    from integrations.nc_sbe.classification import classify_nc_contest

    assert classify_nc_contest(date(2026, 11, 3), "SHERIFF").evidence_status == "held"
    assert classify_nc_contest(date(2026, 11, 3), "GOVERNOR", is_unexpired="not-a-boolean").evidence_status == "held"
    assert classify_nc_contest(date(2026, 11, 3), "CITY OF X MAYOR", identity_verified=False).evidence_status == "held"


def test_future_municipal_date_registry_overrides_only_the_named_place_and_year(monkeypatch):
    from integrations.nc_sbe import classification

    monkeypatch.setattr(
        classification,
        "MUNICIPAL_DATE_OVERRIDES",
        [
            {
                "municipality": "ROCKY MOUNT",
                "date": "2025-11-04",
                "phase": "general_runoff",
                "source_url": "https://example.org/notice",
            }
        ],
        raising=False,
    )
    known = classification.classify_nc_contest(date(2025, 11, 4), "CITY OF ROCKY MOUNT MAYOR")
    other = classification.classify_nc_contest(date(2025, 11, 4), "TOWN OF CARY MAYOR")
    historic = classification.classify_nc_contest(date(2023, 11, 7), "CITY OF ROCKY MOUNT MAYOR")
    assert (known.phase, known.evidence_status) == ("general_runoff", "confirmed")
    assert other.phase == historic.phase == "general"
    assert other.evidence_status == historic.evidence_status == "inferred"


@pytest.mark.parametrize(
    "titles,key",
    [
        (["TOWN OF ASKEWVILLE MAYOR", "TOWN OF ASKEWVILLE TOWN COMMISSIONER"], "municipality:ASKEWVILLE"),
        (["CITY OF BESSEMER CITY MAYOR", "CITY OF BESSEMER CITY COUNCIL MEMBER WARD 1"], "municipality:BESSEMER CITY"),
        (["CITY OF ELIZABETH CITY MAYOR", "CITY OF ELIZABETH CITY COUNCIL WARD 1"], "municipality:ELIZABETH CITY"),
        (["CITY OF CHARLOTTE MAYOR", "CITY OF CHARLOTTE CITY COUNCIL DISTRICT 01"], "municipality:CHARLOTTE"),
    ],
)
def test_municipal_office_qualifiers_do_not_split_one_ballot_into_fictitious_places(titles, key):
    from integrations.nc_sbe.classification import classify_nc_contest

    classified = [classify_nc_contest(date(2025, 11, 4), title) for title in titles]
    assert {c.jurisdiction_key for c in classified} == {key}
    assert len({c.event_group for c in classified}) == 1
