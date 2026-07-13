from integrations.mn_sos.mappers import is_in_scope_file, is_write_in


def test_is_in_scope_file_matches_confirmed_federal_state_labels():
    for label in (
        "U.S. President Statewide",
        "U.S. Senator Statewide",
        "U.S. Representative by District",
        "State Senator by District",
        "State Representative by District",
        "Supreme Court and Courts of Appeals Races",
    ):
        assert is_in_scope_file(label) is True


def test_is_in_scope_file_excludes_local_and_precinct_labels():
    for label in (
        "County Races",
        "County Races and Questions",
        "Municipal Questions",
        "Municipal and Hospital District Races and Questions",
        "Municipal, Hospital, and School District Races by Precinct",
        "Hospital District Races",
        "School Board Races",
        "School Referendum and Bond Questions",
        "Constitutional Amendment Statewide",
        "U.S. President by Precinct",
        "Precinct Reporting Statistics",
    ):
        assert is_in_scope_file(label) is False


def test_is_in_scope_file_matches_future_governor_label_by_pattern():
    assert is_in_scope_file("Governor and Lieutenant Governor Statewide") is True
    assert is_in_scope_file("governor by county") is False  # county-scoped, not statewide/district


def test_is_write_in_matches_9901_only():
    assert is_write_in("9901") is True
    assert is_write_in("0202") is False
    assert is_write_in("") is False
