from datetime import date, timedelta

import pytest
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_ingestion.artifacts import register_source_artifact


@pytest.mark.django_db
def test_identical_content_reuses_content_addressed_artifact():
    retrieved_at = timezone.now()
    first, first_created = register_source_artifact(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.CANDIDATES,
        url="https://example.test/nc/candidates.csv",
        content=b"candidate,data\n",
        retrieved_at=retrieved_at,
        parser_version="nc-candidates-v1",
        election_date=date(2026, 11, 3),
    )
    second, second_created = register_source_artifact(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.CANDIDATES,
        url="https://example.test/nc/candidates.csv",
        content=b"candidate,data\n",
        retrieved_at=retrieved_at + timedelta(hours=1),
        parser_version="nc-candidates-v2",
        election_date=date(2026, 11, 3),
    )

    assert first_created is True
    assert second_created is False
    assert second == first
    assert SourceArtifact.objects.count() == 1
    assert first.content_sha256 == "a3fdcbc1e1188d32468a2292bc2f234792c1e94519c21c3a596f587477a7f86d"


@pytest.mark.django_db
def test_changed_content_creates_successive_artifact():
    retrieved_at = timezone.now()
    first, _ = register_source_artifact(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.RESULTS,
        url="https://example.test/nc/results.zip",
        content=b"version-one",
        retrieved_at=retrieved_at,
        parser_version="nc-results-v1",
    )
    second, created = register_source_artifact(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.RESULTS,
        url="https://example.test/nc/results.zip",
        content=b"version-two",
        retrieved_at=retrieved_at + timedelta(hours=1),
        parser_version="nc-results-v1",
    )

    assert created is True
    assert second != first
    assert second.supersedes == first
    assert SourceArtifact.objects.count() == 2
