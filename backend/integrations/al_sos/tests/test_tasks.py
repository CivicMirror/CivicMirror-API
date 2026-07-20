"""Integration tests for al_sos Celery tasks. All network access is mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


def _year_page_html() -> str:
    return (_FIXTURES / "al_year_page_2026.html").read_text()


@pytest.mark.django_db
def test_sync_al_elections_creates_elections():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})

    assert Election.objects.filter(state="AL", election_type="primary").exists()
    assert Election.objects.filter(state="AL", election_type="general").exists()
    assert Election.objects.filter(state="AL", election_type="primary_runoff").exists()


@pytest.mark.django_db
def test_sync_al_elections_stores_document_links_in_metadata():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})

    primary = Election.objects.get(state="AL", election_type="primary")
    links = primary.source_metadata["al_document_links"]
    assert any("Sample Ballots" == link["label"] for link in links)


@pytest.mark.django_db
def test_sync_al_elections_is_idempotent():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})
        sync_al_elections.apply(kwargs={"year": 2026})

    assert Election.objects.filter(state="AL").count() == 4
