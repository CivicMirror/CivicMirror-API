from datetime import date

import pytest

from api.serializers import ElectionSerializer
from elections.models import Election


@pytest.mark.django_db
def test_election_serializer_includes_sources_and_provenance():
    e = Election.objects.create(
        name="2026 California Primary Election", election_date=date(2026, 6, 2),
        election_type="primary", jurisdiction_level="state", state="CA",
        source_id="11255", canonical_key="CA:primary:2026-06-02:state",
        contributing_sources=["civic_api", "ca_sos"],
        field_provenance={"name": "civic_api", "election_date": "ca_sos"},
    )
    data = ElectionSerializer(e).data
    assert data["sources"] == ["civic_api", "ca_sos"]
    assert data["field_provenance"]["election_date"] == "ca_sos"
