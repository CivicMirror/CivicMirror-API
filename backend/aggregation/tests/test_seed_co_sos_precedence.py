import pytest


@pytest.mark.django_db
def test_co_sos_precedence_rows_seeded():
    from aggregation.migrations._seed_data import seed
    from aggregation.models import SourcePrecedence

    seed(SourcePrecedence)
    seed(SourcePrecedence)  # idempotency

    co_rows = list(
        SourcePrecedence.objects.filter(state="CO").values_list(
            "field_group", "source", "rank"
        )
    )
    assert len(co_rows) == 8, f"Expected 8 CO rows, got {len(co_rows)}"

    expected = [
        ("results",  "co_sos",   0),
        ("results",  "civic_api", 1),
        ("date",     "co_sos",   0),
        ("date",     "civic_api", 1),
        ("contacts", "civic_api", 0),
        ("contacts", "co_sos",   1),
        ("identity", "civic_api", 0),
        ("identity", "co_sos",   1),
    ]
    for field_group, source, rank in expected:
        assert (field_group, source, rank) in co_rows, (
            f"Missing CO precedence row: {field_group}/{source}/rank={rank}"
        )
