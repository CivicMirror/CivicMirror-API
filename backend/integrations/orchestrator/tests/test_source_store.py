import pytest

from integrations.orchestrator.source_store import SourceRecordStore
from ops.models import SourceRecord


@pytest.mark.django_db
def test_upsert_creates_new_source_record():
    store = SourceRecordStore()

    record, changed = store.upsert('fec', 'abc', {'name': 'Alex'})

    assert changed is True
    assert record.pk is not None
    assert SourceRecord.objects.count() == 1


@pytest.mark.django_db
def test_upsert_returns_unchanged_when_checksum_matches():
    store = SourceRecordStore()
    store.upsert('fec', 'abc', {'name': 'Alex'})

    record, changed = store.upsert('fec', 'abc', {'name': 'Alex'})

    assert changed is False
    assert record.raw_payload == {'name': 'Alex'}


@pytest.mark.django_db
def test_upsert_updates_existing_record_when_checksum_changes():
    store = SourceRecordStore()
    store.upsert('fec', 'abc', {'name': 'Alex'})

    record, changed = store.upsert('fec', 'abc', {'name': 'Taylor'})

    assert changed is True
    assert record.raw_payload == {'name': 'Taylor'}
