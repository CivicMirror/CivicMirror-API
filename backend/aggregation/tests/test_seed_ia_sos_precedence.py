import pytest

from aggregation.models import SourcePrecedence

_IA_ROWS = [
    ("IA", "results",  "ia_sos",    0),
    ("IA", "results",  "civic_api", 1),
    ("IA", "date",     "ia_sos",    0),
    ("IA", "date",     "civic_api", 1),
    ("IA", "contacts", "civic_api", 0),
    ("IA", "contacts", "ia_sos",    1),
    ("IA", "identity", "civic_api", 0),
    ("IA", "identity", "ia_sos",    1),
]


def _seed_ia(model):
    for state, field_group, source, rank in _IA_ROWS:
        model.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


@pytest.mark.django_db
def test_ia_sos_precedence_rows_seeded():
    _seed_ia(SourcePrecedence)
    _seed_ia(SourcePrecedence)  # idempotency

    ia_rows = list(
        SourcePrecedence.objects.filter(state="IA").values_list(
            "field_group", "source", "rank"
        )
    )
    assert len(ia_rows) == 8, f"Expected 8 IA rows, got {len(ia_rows)}"

    expected = [
        ("results",  "ia_sos",    0),
        ("results",  "civic_api", 1),
        ("date",     "ia_sos",    0),
        ("date",     "civic_api", 1),
        ("contacts", "civic_api", 0),
        ("contacts", "ia_sos",    1),
        ("identity", "civic_api", 0),
        ("identity", "ia_sos",    1),
    ]
    for field_group, source, rank in expected:
        assert (field_group, source, rank) in ia_rows, (
            f"Missing IA precedence row: {field_group}/{source}/rank={rank}"
        )
