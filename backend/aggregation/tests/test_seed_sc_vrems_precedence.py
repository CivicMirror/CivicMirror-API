import pytest


@pytest.mark.django_db
def test_sc_vrems_precedence_rows_seeded():
    from aggregation.migrations._seed_data import seed
    from aggregation.models import SourcePrecedence

    seed(SourcePrecedence)
    seed(SourcePrecedence)  # idempotency: twice must not duplicate

    sc_rows = list(
        SourcePrecedence.objects.filter(state="SC").values_list(
            "field_group", "source", "rank"
        )
    )
    assert len(sc_rows) == 8, f"Expected 8 SC rows, got {len(sc_rows)}"

    expected = [
        ("results",  "sc_vrems",  0),
        ("results",  "civic_api", 1),
        ("date",     "sc_vrems",  0),
        ("date",     "civic_api", 1),
        ("contacts", "civic_api", 0),
        ("contacts", "sc_vrems",  1),
        ("identity", "civic_api", 0),
        ("identity", "sc_vrems",  1),
    ]
    for field_group, source, rank in expected:
        assert (field_group, source, rank) in sc_rows, (
            f"Missing SC precedence row: {field_group}/{source}/rank={rank}"
        )
