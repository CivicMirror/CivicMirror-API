import pytest

from aggregation.models import SourcePrecedence
from aggregation.precedence import field_group_for, resolve_rank


def test_field_group_for_maps_known_fields():
    assert field_group_for("election_date") == "date"
    assert field_group_for("office_title") == "identity"
    assert field_group_for("image_url") == "contacts"
    assert field_group_for("party") == "party"
    assert field_group_for("ocd_division_id") == "district"
    assert field_group_for("results_url") == "results"


def test_field_group_for_unknown_field_defaults_to_identity():
    assert field_group_for("some_new_field") == "identity"


@pytest.mark.django_db
def test_resolve_rank_prefers_most_specific_row():
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="results", source="ca_sos", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="results", source="civic_api", rank=1)
    # CA/results: ca_sos outranks civic
    assert resolve_rank("CA", "results", "ca_sos") < resolve_rank("CA", "results", "civic_api")


@pytest.mark.django_db
def test_resolve_rank_falls_back_through_wildcards():
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    # No CA-specific row: civic resolves via the global default
    assert resolve_rank("CA", "contacts", "civic_api") == 0


@pytest.mark.django_db
def test_resolve_rank_unranked_source_is_lowest():
    rank = resolve_rank("CA", "results", "nonexistent_source")
    assert rank == float("inf")
