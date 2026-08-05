from __future__ import annotations

import datetime


def test_get_active_cycle_returns_2026_cycle_before_general():
    from integrations.ut_elections.calendar import get_active_cycle
    cycle = get_active_cycle(datetime.date(2026, 8, 5))
    assert cycle is not None
    assert cycle.year == 2026
    assert cycle.primary_date == datetime.date(2026, 6, 23)
    assert cycle.general_date == datetime.date(2026, 11, 3)
    assert cycle.candidate_filing_url == (
        "https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx"
    )


def test_get_active_cycle_returns_none_when_no_cycle_configured():
    from integrations.ut_elections.calendar import get_active_cycle
    assert get_active_cycle(datetime.date(2099, 1, 1)) is None
