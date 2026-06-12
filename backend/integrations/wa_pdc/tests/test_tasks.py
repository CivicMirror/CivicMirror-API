"""
Unit tests for the Washington PDC candidate contact synchronization task.
"""
from __future__ import annotations

import contextlib
import datetime
from unittest.mock import MagicMock, patch

import pytest

from integrations.wa_pdc.tasks import _matches_name, sync_wa_pdc_candidates


def test_matches_name():
    # 1. Direct match
    assert _matches_name("Aaron Croft", "Aaron Croft") is True
    assert _matches_name("aaron croft", "Aaron Croft") is True

    # 2. Parentheses/nickname extraction
    assert _matches_name("Aaron Croft", "Aaron Matthew Croft (Aaron M. Croft)") is True
    assert _matches_name("Jenny Graham", "VIRGINIA (Jenny) C. GRAHAM (Jenny Graham)") is True
    assert _matches_name("Jonathan Bingle", "JONATHAN BINGLE (Jonathan Bingle)") is True

    # 3. Middle names and initials matching
    assert _matches_name("Aaron Croft", "Aaron Matthew Croft") is True
    assert _matches_name("Aaron Croft", "Aaron M. Croft") is True

    # 4. Mismatch cases
    assert _matches_name("John Doe", "Jane Doe") is False
    assert _matches_name("Bob Smith", "Bob Jones") is False


def test_sync_wa_pdc_candidates_success():
    # Create mock Django objects
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.election_date = datetime.date(2026, 11, 3)

    mock_race = MagicMock()
    mock_race.election = mock_election
    mock_race.office_title = "STATE REPRESENTATIVE"
    mock_race.jurisdiction = "LEG DISTRICT 06 - HOUSE"

    mock_candidate = MagicMock()
    mock_candidate.name = "Aaron Croft"
    mock_candidate.source_metadata = {}
    mock_candidate.contact_phone = ""

    # Mock Candidate relation on race
    mock_race.candidates.all.return_value = [mock_candidate]

    # Mock SODA API payload response
    mock_soda_response = [
        {
            "filer_name": "Aaron Matthew Croft (Aaron M. Croft)",
            "candidate_committee_phone": "5098636526",
            "candidate_email": "croftfam@mac.com",
            "committee_email": "campaign@croft4WA.com",
            "legislative_district": "06",
            "office": "STATE REPRESENTATIVE",
            "treasurer_name": "Chris Drohan",
            "treasurer_phone": "5094346407",
            "committee_id": "40967",
            "candidacy_id": "3391016",
            "filer_id": "CROFA--936",
            "url": {"url": "https://my.pdc.wa.gov/registration/public/-/#/public/registration/68916"},
        }
    ]

    with patch("integrations.wa_pdc.tasks.SyncLog.objects.create") as mock_log_create, \
         patch("integrations.wa_pdc.tasks.Race.objects.filter") as mock_race_filter, \
         patch("integrations.wa_pdc.tasks.transaction.atomic") as mock_atomic, \
         patch("integrations.wa_pdc.tasks.requests.get") as mock_get:

        # Mock SyncLog
        mock_log = MagicMock()
        mock_log_create.return_value = mock_log

        # Mock transaction.atomic context manager
        mock_atomic.return_value = contextlib.nullcontext()

        # Mock Race.objects.filter().prefetch_related()
        mock_query = MagicMock()
        mock_race_filter.return_value = mock_query
        mock_query.prefetch_related.return_value = [mock_race]

        # Mock requests
        mock_response = MagicMock()
        mock_response.json.return_value = mock_soda_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Execute celery task synchronously via apply()
        result = sync_wa_pdc_candidates.apply(args=[1])

    # Assert candidate was enriched
    assert mock_candidate.contact_phone == "5098636526"
    assert mock_candidate.source_metadata["pdc_personal_email"] == "croftfam@mac.com"
    assert mock_candidate.source_metadata["pdc_campaign_email"] == "campaign@croft4WA.com"
    assert mock_candidate.source_metadata["pdc_treasurer_name"] == "Chris Drohan"
    assert mock_candidate.source_metadata["pdc_candidacy_id"] == "3391016"
    assert mock_candidate.source_metadata["pdc_filer_id"] == "CROFA--936"
    assert mock_candidate.source_metadata["pdc_registration_url"] == "https://my.pdc.wa.gov/registration/public/-/#/public/registration/68916"

    # Assert save was called
    assert mock_candidate.save.call_count == 1

    # Check Celery task output
    assert result.result["enriched"] == 1
    assert result.result["skipped"] == 0
