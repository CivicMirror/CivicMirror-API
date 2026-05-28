import pytest

from aggregation.models import SourcePrecedence


@pytest.mark.django_db
def test_source_precedence_uniqueness():
    SourcePrecedence.objects.create(state="CA", field_group="results", source="ca_sos", rank=0)
    with pytest.raises(Exception):
        SourcePrecedence.objects.create(state="CA", field_group="results", source="ca_sos", rank=5)


@pytest.mark.django_db
def test_source_precedence_str():
    sp = SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    assert "civic_api" in str(sp)
