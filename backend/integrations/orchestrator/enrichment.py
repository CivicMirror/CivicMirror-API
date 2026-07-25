from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elections.models import Candidate


def _is_blank(value):
    return value in (None, '')


def _priorities_for(field: str, candidate: Candidate) -> list[str]:
    """
    FIELD_PRIORITY entries are normally a static source-priority list, but
    some fields (e.g. contact_office) need the winning source to depend on
    the candidate being enriched — see candidate_matcher._contact_office_priority.
    """
    from .candidate_matcher import FIELD_PRIORITY

    priorities = FIELD_PRIORITY.get(field, [])
    if callable(priorities):
        return priorities(candidate)
    return priorities


def _has_higher_priority(priorities: list[str], incoming_source: str, current_source: str | None) -> bool:
    if incoming_source not in priorities:
        return False
    if not current_source or current_source not in priorities:
        return True
    return priorities.index(incoming_source) < priorities.index(current_source)


def get_fields_to_update(candidate: Candidate, source: str, payload: dict) -> dict:
    from .candidate_matcher import FIELD_PRIORITY

    updates: dict = {}
    source_metadata = dict(candidate.source_metadata or {})
    field_sources = dict(source_metadata.get('_field_sources') or {})

    for field in FIELD_PRIORITY:
        if field not in payload:
            continue

        incoming_value = payload.get(field)
        if field != 'incumbent' and incoming_value in (None, ''):
            continue

        current_value = getattr(candidate, field)
        current_source = field_sources.get(field)
        priorities = _priorities_for(field, candidate)

        if field == 'incumbent':
            if current_value == incoming_value:
                continue
            if current_source is None or _has_higher_priority(priorities, source, current_source):
                updates[field] = incoming_value
                field_sources[field] = source
            continue

        if current_value == incoming_value:
            continue

        if _is_blank(current_value) or _has_higher_priority(priorities, source, current_source):
            updates[field] = incoming_value
            field_sources[field] = source

    if field_sources != (candidate.source_metadata or {}).get('_field_sources', {}):
        source_metadata['_field_sources'] = field_sources
        updates['source_metadata'] = source_metadata

    return updates


def merge_source_metadata(existing: dict, source: str, new_metadata: dict) -> dict:
    merged = dict(existing or {})
    source_block = dict(merged.get(source) or {})
    source_block.update(new_metadata or {})
    merged[source] = source_block
    return merged
