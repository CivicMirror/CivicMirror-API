from __future__ import annotations

import hashlib
import json

from ops.models import SourceRecord


class SourceRecordStore:
    def upsert(self, source: str, external_id: str, raw_payload: dict) -> tuple[SourceRecord, bool]:
        checksum = hashlib.sha256(json.dumps(raw_payload, sort_keys=True).encode()).hexdigest()
        record, created = SourceRecord.objects.get_or_create(
            source=source,
            external_id=str(external_id),
            defaults={'raw_payload': raw_payload, 'payload_checksum': checksum},
        )
        if created:
            return record, True
        if record.payload_checksum == checksum:
            return record, False
        record.raw_payload = raw_payload
        record.payload_checksum = checksum
        record.save(update_fields=['raw_payload', 'payload_checksum', 'last_seen_at'])
        return record, True
