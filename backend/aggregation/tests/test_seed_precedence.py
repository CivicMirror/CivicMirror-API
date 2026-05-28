import pytest

from aggregation.migrations import _seed_data  # helper module created in Step 3
from aggregation.models import SourcePrecedence


@pytest.mark.django_db
def test_seed_rows_define_civic_default_and_ca_overrides():
    _seed_data.seed(SourcePrecedence)
    assert SourcePrecedence.objects.get(state="*", field_group="*", source="civic_api").rank == 0
    assert (
        SourcePrecedence.objects.get(state="CA", field_group="results", source="ca_sos").rank
        < SourcePrecedence.objects.get(state="CA", field_group="results", source="civic_api").rank
    )
    assert SourcePrecedence.objects.get(state="CA", field_group="contacts", source="civic_api").rank == 0
