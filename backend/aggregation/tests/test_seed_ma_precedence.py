import pytest

from aggregation.migrations._seed_data import seed
from aggregation.models import SourcePrecedence

_MA_ROWS = [
    ("MA", "results",  "ma_sos",    0),
    ("MA", "results",  "civic_api", 1),
    ("MA", "date",     "ma_sos",    0),
    ("MA", "date",     "civic_api", 1),
    ("MA", "contacts", "civic_api", 0),
    ("MA", "contacts", "ma_sos",    1),
    ("MA", "identity", "civic_api", 0),
    ("MA", "identity", "ma_sos",    1),
]


@pytest.mark.django_db
def test_ma_precedence_rows_seeded():
    seed(SourcePrecedence)  # baseline (* + CA)
    for state, field_group, source, rank in _MA_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )

    # MA SOS owns results + date; Civic owns identity + contacts.
    assert (
        SourcePrecedence.objects.get(state="MA", field_group="results", source="ma_sos").rank
        < SourcePrecedence.objects.get(state="MA", field_group="results", source="civic_api").rank
    )
    assert (
        SourcePrecedence.objects.get(state="MA", field_group="date", source="ma_sos").rank
        < SourcePrecedence.objects.get(state="MA", field_group="date", source="civic_api").rank
    )
    assert (
        SourcePrecedence.objects.get(state="MA", field_group="identity", source="civic_api").rank
        < SourcePrecedence.objects.get(state="MA", field_group="identity", source="ma_sos").rank
    )
    assert (
        SourcePrecedence.objects.get(state="MA", field_group="contacts", source="civic_api").rank
        < SourcePrecedence.objects.get(state="MA", field_group="contacts", source="ma_sos").rank
    )
