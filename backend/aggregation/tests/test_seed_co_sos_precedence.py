import pytest

from aggregation.models import SourcePrecedence

_CO_ROWS = [
    ("CO", "results",  "co_sos",    0),
    ("CO", "results",  "civic_api", 1),
    ("CO", "date",     "co_sos",    0),
    ("CO", "date",     "civic_api", 1),
    ("CO", "contacts", "civic_api", 0),
    ("CO", "contacts", "co_sos",    1),
    ("CO", "identity", "civic_api", 0),
    ("CO", "identity", "co_sos",    1),
]


def _seed_co(model):
    for state, field_group, source, rank in _CO_ROWS:
        model.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


@pytest.mark.django_db
def test_co_sos_precedence_rows_seeded():
    _seed_co(SourcePrecedence)
    _seed_co(SourcePrecedence)  # idempotency

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
