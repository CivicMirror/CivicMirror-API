import datetime

from integrations.mn_sos import election_dates


def test_state_primary_is_second_tuesday_of_august():
    # 2024: Aug 13; 2026: Aug 11 (matches the live 20240813 / 20260811 paths).
    assert election_dates.state_primary_date(2024) == datetime.date(2024, 8, 13)
    assert election_dates.state_primary_date(2026) == datetime.date(2026, 8, 11)


def test_state_general_is_tuesday_after_first_monday_of_november():
    # 2024: Nov 5; 2026: Nov 3.
    assert election_dates.state_general_date(2024) == datetime.date(2024, 11, 5)
    assert election_dates.state_general_date(2026) == datetime.date(2026, 11, 3)


def test_statutory_statewide_elections_yields_even_year_primary_and_general():
    ref = datetime.date(2026, 7, 17)
    got = election_dates.statutory_statewide_elections(ref, years_back=0, years_ahead=0)
    assert got == [
        (datetime.date(2026, 8, 11), "primary", "2026 Minnesota Primary"),
        (datetime.date(2026, 11, 3), "general", "2026 Minnesota General Election"),
    ]


def test_statutory_statewide_elections_skips_odd_years():
    ref = datetime.date(2025, 7, 17)
    got = election_dates.statutory_statewide_elections(ref, years_back=0, years_ahead=0)
    assert got == []  # 2025 is odd — no statewide federal/state election
