from __future__ import annotations

from datetime import date


def _normalize_text(value: str) -> str:
    return ' '.join((value or '').strip().lower().split())


def map_candidate(raw: dict) -> dict | None:
    candidate_status = (raw.get('candidate_status') or '').strip().upper()
    if candidate_status not in {'C', 'F'}:
        return None

    district = raw.get('district')
    district_value = str(district).strip() if district not in (None, '') else ''
    state = (raw.get('state') or '').strip().upper() or None

    source_fields = {
        'candidate_id': raw.get('candidate_id'),
        'name': (raw.get('name') or '').strip(),
        'office': raw.get('office'),
        'office_full': raw.get('office_full'),
        'state': state,
        'district': district_value,
        'party_full': raw.get('party_full'),
        'incumbent_challenge_full': raw.get('incumbent_challenge_full'),
        'election_years': raw.get('election_years') or [],
        'candidate_status': candidate_status,
    }

    return {
        'fec_candidate_id': str(raw.get('candidate_id') or '').strip(),
        'office_type': (raw.get('office') or '').strip(),
        'state': state,
        'district': district_value,
        'party': (raw.get('party_full') or '').strip(),
        'incumbent': (raw.get('incumbent_challenge_full') or '').strip() == 'Incumbent',
        'normalized_office_title': _normalize_text(raw.get('office_full') or ''),
        'source_metadata': {'fec': source_fields},
    }


def fec_office_to_ocd_type(office: str) -> str:
    return {
        'H': 'cd',
        'S': 's',
        'P': '',
    }.get((office or '').strip().upper(), '')


def current_cycle() -> int:
    year = date.today().year
    return year if year % 2 == 0 else year + 1
