import pytest

_VA_ROWS = [
    ("VA", "results",  "va_elect",  0),
    ("VA", "results",  "civic_api", 1),
    ("VA", "date",     "va_elect",  0),
    ("VA", "date",     "civic_api", 1),
    ("VA", "contacts", "civic_api", 0),
    ("VA", "contacts", "va_elect",  1),
    ("VA", "identity", "civic_api", 0),
    ("VA", "identity", "va_elect",  1),
]


@pytest.mark.django_db
def test_va_precedence_rows_seeded():
    from aggregation.models import SourcePrecedence

    for state, field_group, source, rank in _VA_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )
    # idempotency
    for state, field_group, source, rank in _VA_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )

    va_rows = list(
        SourcePrecedence.objects.filter(state="VA").values_list(
            "field_group", "source", "rank"
        )
    )
    assert len(va_rows) == 8, f"Expected 8 VA rows, got {len(va_rows)}"

    expected = [
        ("results",  "va_elect",  0),
        ("results",  "civic_api", 1),
        ("date",     "va_elect",  0),
        ("date",     "civic_api", 1),
        ("contacts", "civic_api", 0),
        ("contacts", "va_elect",  1),
        ("identity", "civic_api", 0),
        ("identity", "va_elect",  1),
    ]
    for field_group, source, rank in expected:
        assert (field_group, source, rank) in va_rows, (
            f"Missing VA precedence row: {field_group}/{source}/rank={rank}"
        )
