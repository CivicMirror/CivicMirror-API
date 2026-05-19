from __future__ import annotations

from django.db.models import Q


def resolve_ocd_id(state: str, office: str, district_number: str):
    """Query DistrictRecord rows to resolve an OCD division for an office/district."""
    from elections.models import DistrictRecord as DR

    office = (office or '').strip().upper()
    if office == 'P':
        return None
    if office not in {'H', 'S'}:
        return None

    district_type = 'cd' if office == 'H' else 's'
    qs = DR.objects.filter(state=(state or '').upper(), district_type=district_type)
    raw_district = (district_number or '').strip()
    if raw_district:
        normalized = raw_district.lstrip('0') or '0'
        qs = qs.filter(Q(district_number=normalized) | Q(district_number=raw_district))
    return qs.first()
