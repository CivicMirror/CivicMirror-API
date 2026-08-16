from datetime import date

import pytest
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_ingestion.contracts import (
    CandidateFilingRecord,
    ContestRecord,
    ElectionRecord,
    JurisdictionRecord,
    OfficeRecord,
    PersonSourceEvidence,
    PreElectionBatch,
)


@pytest.fixture
def source_artifact(db):
    return SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.CANDIDATES,
        url="https://example.test/nc/candidates.csv",
        retrieved_at=timezone.now(),
        content_sha256="d" * 64,
        parser_version="nc-candidates-v1",
        election_date=date(2026, 11, 3),
    )


@pytest.fixture
def batch_factory():
    def build(**overrides):
        values = {
            "state": "NC",
            "jurisdictions": (
                JurisdictionRecord(
                    public_id="ocd-division/country:us/state:nc",
                    name="North Carolina",
                    classification="state",
                    state="NC",
                    record_status="verified",
                    source_key="nc",
                ),
            ),
            "offices": (
                OfficeRecord(
                    public_id="nc/us-senator",
                    jurisdiction_public_id="ocd-division/country:us/state:nc",
                    canonical_name="United States Senator",
                    role="legislator",
                    default_term_months=72,
                    positions=1,
                    record_status="verified",
                    source_key="US SENATE",
                ),
            ),
            "elections": (
                ElectionRecord(
                    public_id="nc/2026-11-03/general",
                    name="2026 General Election",
                    election_date=date(2026, 11, 3),
                    election_type="general",
                    lifecycle_status="upcoming",
                    source_key="2026-11-03-general",
                ),
            ),
            "contests": (
                ContestRecord(
                    public_id="nc/2026-11-03/general/us-senator",
                    election_public_id="nc/2026-11-03/general",
                    office_public_id="nc/us-senator",
                    vote_for=1,
                    is_partisan=True,
                    source_key="US SENATE",
                ),
            ),
            "candidates": (
                CandidateFilingRecord(
                    filing_key="us-senator/dedreana-freeman",
                    contest_public_id="nc/2026-11-03/general/us-senator",
                    ballot_name="DeDreana Freeman",
                    canonical_name="DeDreana Freeman",
                    given_name="DeDreana",
                    family_name="Freeman",
                    party_candidate="DEM",
                    source_records=(
                        PersonSourceEvidence(
                            source_row_key="candidate-row-county-1",
                            reported_name="DeDreana Freeman",
                            ballot_name="DeDreana Freeman",
                            protected_address="123 Private Lane",
                            protected_phone="919-555-0100",
                            protected_email="private@example.test",
                        ),
                        PersonSourceEvidence(
                            source_row_key="candidate-row-county-2",
                            reported_name="DeDreana Freeman",
                            ballot_name="DeDreana Freeman",
                        ),
                    ),
                ),
            ),
        }
        values.update(overrides)
        return PreElectionBatch(**values)

    return build
