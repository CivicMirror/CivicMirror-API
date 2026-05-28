import pytest

from aggregation.migrations import _seed_data
from aggregation.models import SourcePrecedence


@pytest.mark.django_db
def test_ma_precedence_rows_seeded():
    _seed_data.seed(SourcePrecedence)
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
