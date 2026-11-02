import json

import pytest

from cm2_elections.models import PersonSourceRecord
from cm2_elections.serializers import CandidacySerializer, PersonSerializer


@pytest.mark.django_db
def test_public_person_and_candidacy_output_excludes_protected_source_evidence(
    person,
    candidacy,
    source_artifact,
):
    record = PersonSourceRecord.objects.create(
        source_artifact=source_artifact,
        source_row_key="private-candidate-row",
        person=person,
        reported_name="DeDreana Freeman",
        ballot_name="DeDreana Freeman",
        protected_address="987 Never Publish Avenue",
        protected_phone="919-555-0199",
        protected_email="never-publish@example.test",
        parser_version="nc-candidates-v1",
    )
    candidacy.source_records.add(record)

    output = {
        "person": PersonSerializer(person).data,
        "candidacy": CandidacySerializer(candidacy).data,
    }
    serialized = json.dumps(output).lower()

    assert output["candidacy"]["ballot_name"] == "DeDreana Freeman"
    assert output["candidacy"]["person_public_id"] == person.public_id
    assert output["candidacy"]["contest_public_id"] == candidacy.contest.public_id
    assert "protected_address" not in serialized
    assert "protected_phone" not in serialized
    assert "protected_email" not in serialized
    assert "987 never publish avenue" not in serialized
    assert "919-555-0199" not in serialized
    assert "never-publish@example.test" not in serialized
    assert str(person.id) not in serialized
    assert str(candidacy.contest_id) not in serialized
