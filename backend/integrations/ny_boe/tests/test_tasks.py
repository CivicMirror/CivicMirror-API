from datetime import date
from unittest.mock import patch

import pytest

from elections.models import Election


def test_merge_metadata_preserves_existing_keys():
    from integrations.ny_boe.tasks import merge_source_metadata

    assert merge_source_metadata({"curated": "keep"}, {"ny_boe": {"version": "1"}}) == {
        "curated": "keep",
        "ny_boe": {"version": "1"},
    }


@pytest.mark.django_db
def test_sync_ny_elections_preserves_flateau_names():
    from aggregation.models import SourcePrecedence
    from integrations.ny_boe.tasks import sync_ny_elections

    SourcePrecedence.objects.create(state="NY", field_group="identity", source="ny_boe", rank=0)
    SourcePrecedence.objects.create(state="NY", field_group="date", source="ny_boe", rank=0)
    SourcePrecedence.objects.create(state="NY", field_group="status", source="ny_boe", rank=0)
    election = Election.objects.create(
        name="2026 New York Primary",
        election_date=date(2026, 6, 23),
        election_type=Election.ElectionType.PRIMARY,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NY",
        canonical_key="NY:primary:2026-06-23:state",
        source_metadata={"flateau_election_names": ["Albany Primary"], "curated": "keep"},
    )

    document = {
        "document_type": "primary_candidate_certification",
        "title": "Certification for the June 23, 2026 Primary Election",
        "election_date": date(2026, 6, 23),
        "election_type": Election.ElectionType.PRIMARY,
        "landing_url": "https://elections.ny.gov/",
        "pdf_url": "https://elections.ny.gov/cert.pdf",
    }

    with patch("integrations.ny_boe.tasks.NyBoeClient") as client_cls, \
         patch("integrations.ny_boe.tasks.sync_ny_races") as sync_races:
        client_cls.return_value.get_current_certification_documents.return_value = [document]
        sync_ny_elections()

    election.refresh_from_db()
    assert election.source_metadata["flateau_election_names"] == ["Albany Primary"]
    assert election.source_metadata["curated"] == "keep"
    assert election.source_metadata["ny_boe"]["pdf_url"] == "https://elections.ny.gov/cert.pdf"
    sync_races.delay.assert_called_once()
