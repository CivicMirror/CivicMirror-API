import hashlib
from datetime import date, datetime

from django.db import transaction

from cm2_core.models import SourceArtifact


@transaction.atomic
def register_source_artifact(
    *,
    source_system: str,
    source_type: str,
    url: str,
    content: bytes,
    retrieved_at: datetime,
    parser_version: str,
    source_timestamp: datetime | None = None,
    election_date: date | None = None,
    metadata: dict | None = None,
) -> tuple[SourceArtifact, bool]:
    content_sha256 = hashlib.sha256(content).hexdigest()
    existing = SourceArtifact.objects.filter(
        source_system=source_system,
        url=url,
        content_sha256=content_sha256,
    ).first()
    if existing is not None:
        return existing, False

    supersedes = (
        SourceArtifact.objects.filter(source_system=source_system, url=url)
        .order_by("-retrieved_at", "-created_at")
        .first()
    )
    artifact, created = SourceArtifact.objects.get_or_create(
        source_system=source_system,
        url=url,
        content_sha256=content_sha256,
        defaults={
            "source_type": source_type,
            "retrieved_at": retrieved_at,
            "source_timestamp": source_timestamp,
            "parser_version": parser_version,
            "election_date": election_date,
            "metadata": metadata or {},
            "supersedes": supersedes,
        },
    )
    return artifact, created
