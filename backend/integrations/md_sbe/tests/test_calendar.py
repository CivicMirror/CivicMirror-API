from __future__ import annotations

import datetime


def test_get_active_cycle_returns_2026_cycle_before_primary():
    from integrations.md_sbe.calendar import get_active_cycle
    cycle = get_active_cycle(datetime.date(2026, 3, 1))
    assert cycle is not None
    assert cycle.year == 2026
    assert cycle.primary_date == datetime.date(2026, 6, 23)
    assert cycle.general_date == datetime.date(2026, 11, 3)
    assert cycle.cycle_letter == "G"


def test_get_active_cycle_returns_none_when_no_cycle_configured():
    from integrations.md_sbe.calendar import get_active_cycle
    assert get_active_cycle(datetime.date(2099, 1, 1)) is None


def test_cycle_prefix_is_cycle_letter_plus_phase_letter():
    """MD's prefix is [cycle][phase]: the 2026 gubernatorial cycle is GP for the
    primary and GG for the general. One prefix used for both phases sends the
    general-election fetch to a dead URL."""
    from integrations.md_sbe.calendar import get_active_cycle
    cycle = get_active_cycle(datetime.date(2026, 3, 1))

    assert cycle.primary_cycle_prefix == "GP"
    assert cycle.general_cycle_prefix == "GG"
    assert cycle.prefix_for_phase("primary") == "GP"
    assert cycle.prefix_for_phase("general") == "GG"


def test_presidential_cycle_letter_yields_pp_and_pg():
    from integrations.md_sbe.calendar import MdElectionCycle
    cycle = MdElectionCycle(
        year=2024,
        primary_date=datetime.date(2024, 5, 14),
        general_date=datetime.date(2024, 11, 5),
        cycle_letter="P",
    )
    assert cycle.prefix_for_phase("primary") == "PP"
    assert cycle.prefix_for_phase("general") == "PG"


def test_phase_for_date_flips_after_the_primary():
    from integrations.md_sbe.calendar import get_active_cycle
    cycle = get_active_cycle(datetime.date(2026, 3, 1))

    assert cycle.phase_for_date(datetime.date(2026, 6, 23)) == "primary"
    assert cycle.phase_for_date(datetime.date(2026, 6, 24)) == "general"
