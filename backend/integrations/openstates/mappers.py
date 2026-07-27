from __future__ import annotations

from django.utils import timezone


def _extract_current_party(parties) -> str:
    if isinstance(parties, str):
        return parties.strip()
    for party in parties or []:
        if not isinstance(party, dict):
            continue
        if not party.get('end_date'):
            return party.get('name') or party.get('party') or ''
    return ''


def _first_value(items: list[dict] | None, key: str) -> str:
    for item in items or []:
        if isinstance(item, dict) and item.get(key):
            return item[key]
    return ''


def _extract_other_names(other_names: list[dict] | None) -> list[str]:
    names = []
    for item in other_names or []:
        if isinstance(item, dict) and item.get('name'):
            names.append(str(item['name']).strip())
    return names


def map_person(raw: dict, state: str) -> dict:
    """
    Map an OpenStates v3 /people record → CandidateMatcher enrichment payload.

    `state` is the two-letter code the caller queried OpenStates for (see
    sync_openstates_legislators), not derived from the payload: the v3 API's
    `current_role` has no `jurisdiction` key (jurisdiction is a separate
    top-level dict, e.g. {"id": "ocd-jurisdiction/.../state:ma/government"}),
    so parsing a state code out of `current_role` silently returned "" for
    every person in every state — which made every enrich_or_create match
    tier bail out on the empty-state guard, so OpenStates enrichment (and
    the Race.ocd_division_id backfill piggybacked on it) never fired for
    anyone. See issue #26.
    """
    current_role = raw.get('current_role') or {}
    incumbent = bool(current_role)
    jurisdiction = raw.get('jurisdiction') or {}

    return {
        'openstates_person_id': str(raw.get('id') or ''),
        'party': _extract_current_party(raw.get('party')),
        'image_url': raw.get('image') or '',
        'website_url': _first_value(raw.get('links'), 'url'),
        'contact_phone': _first_value(raw.get('offices'), 'voice'),
        'contact_office': _first_value(raw.get('offices'), 'address'),
        'incumbent': incumbent,
        'state': (state or '').upper(),
        'chamber': (current_role.get('org_classification') or '').lower(),
        'district': str(current_role.get('district') or ''),
        'display_name': (raw.get('name') or '').strip(),
        'other_names': _extract_other_names(raw.get('other_names')),
        'family_name': (raw.get('family_name') or '').strip(),
        'ocd_division_id': current_role.get('division_id') or '',
        'source_metadata': {
            'openstates': {
                'person_id': str(raw.get('id') or ''),
                'jurisdiction': jurisdiction.get('id') or '',
                'email': raw.get('email') or '',
                'last_synced': timezone.now().isoformat(),
            }
        },
    }
