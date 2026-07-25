from __future__ import annotations

import re
from typing import Callable, Union

from django.db import models as django_models

from elections.models import Candidate, Race

from .enrichment import get_fields_to_update, merge_source_metadata


def _contact_office_priority(candidate: Candidate) -> list[str]:
    """
    OCPF's address is the candidate's committee/mailing address (accurate for
    challengers, who have no official office) while openstates/congress carry
    the actual Capitol office (accurate for sitting officeholders, absent for
    challengers). Which one is "correct" depends on whether this specific
    candidate currently holds office, not on which source is generally more
    authoritative.
    """
    if candidate.incumbent:
        return ['congress', 'openstates', 'ocpf', 'openelections']
    return ['ocpf', 'congress', 'openstates', 'openelections']


FieldPriority = Union[list[str], Callable[[Candidate], list[str]]]

FIELD_PRIORITY: dict[str, FieldPriority] = {
    'party': ['ocpf', 'civic_api', 'fec', 'congress', 'openstates', 'openelections'],
    'incumbent': ['civic_api', 'congress', 'openstates', 'openelections'],
    'image_url': ['civic_api', 'openstates', 'ocpf', 'openelections'],
    'website_url': ['civic_api', 'congress', 'openstates', 'openelections'],
    'description': ['civic_api', 'congress', 'openelections'],
    'contact_phone': ['congress', 'openstates', 'openelections'],
    'contact_office': _contact_office_priority,
}

IMMUTABLE_FROM_ENRICHMENT = {'name'}
CONGRESSIONAL_DISTRICT_RE = re.compile(r'(?:/cd:|district\s+)(\d+)', re.IGNORECASE)


class CandidateMatcher:
    external_id_fields = ('fec_candidate_id', 'bioguide_id', 'openstates_person_id', 'ocpf_filer_id')

    def enrich(
        self,
        race: Race | None,
        source: str,
        external_id: str,
        enrichment_payload: dict,
    ) -> tuple['Candidate | None', str]:
        candidate, ambiguous = self._find_candidate(race, enrichment_payload)
        if ambiguous:
            return None, 'ambiguous'
        if candidate is None:
            return None, 'no_match'

        ocd_division_id = enrichment_payload.get('ocd_division_id')
        if ocd_division_id and candidate.race_id and not candidate.race.ocd_division_id:
            candidate.race.ocd_division_id = ocd_division_id
            candidate.race.save(update_fields=['ocd_division_id'])

        updates = get_fields_to_update(candidate, source, enrichment_payload)
        metadata_updates = {'external_id': str(external_id)}
        source_metadata_payload = enrichment_payload.get('source_metadata') or {}
        if isinstance(source_metadata_payload.get(source), dict):
            metadata_updates.update(source_metadata_payload[source])
        else:
            metadata_updates.update(source_metadata_payload)
        merged_source_metadata = merge_source_metadata(candidate.source_metadata or {}, source, metadata_updates)

        field_source_metadata = updates.pop('source_metadata', None)
        if field_source_metadata and field_source_metadata.get('_field_sources'):
            merged_source_metadata['_field_sources'] = field_source_metadata['_field_sources']

        for field in self.external_id_fields:
            incoming_value = enrichment_payload.get(field)
            if incoming_value and not getattr(candidate, field):
                updates[field] = incoming_value

        if merged_source_metadata != (candidate.source_metadata or {}):
            updates['source_metadata'] = merged_source_metadata

        if not updates:
            return candidate, 'skipped'

        for field, value in updates.items():
            setattr(candidate, field, value)
        candidate.save(update_fields=list(updates.keys()))
        return candidate, 'enriched'

    def enrich_or_create(
        self,
        race: Race | None,
        source: str,
        external_id: str,
        enrichment_payload: dict,
    ) -> tuple['Candidate | None', str]:
        candidate, action = self.enrich(race, source, external_id, enrichment_payload)
        if action != 'no_match':
            return candidate, action

        state = (enrichment_payload.get('state') or '').upper()
        chamber = (enrichment_payload.get('chamber') or '').lower()
        district = str(enrichment_payload.get('district') or '').strip()
        name = enrichment_payload.get('display_name') or enrichment_payload.get('name') or ''

        if not (state and chamber and name):
            return None, 'no_match'

        target_race = self._find_race_for_legislator(state, chamber, district)
        if target_race is None:
            return None, 'no_match'

        candidate = Candidate.objects.create(
            race=target_race,
            name=name,
            party=enrichment_payload.get('party') or '',
            incumbent=bool(enrichment_payload.get('incumbent')),
            candidate_status=Candidate.CandidateStatus.RUNNING,
            image_url=enrichment_payload.get('image_url') or '',
            website_url=enrichment_payload.get('website_url') or '',
            contact_phone=enrichment_payload.get('contact_phone') or '',
            contact_office=enrichment_payload.get('contact_office') or '',
            openstates_person_id=str(external_id) if external_id else '',
            source_metadata=merge_source_metadata(
                {},
                source,
                {
                    'external_id': str(external_id),
                    **(enrichment_payload.get('source_metadata', {}).get(source) or {}),
                },
            ),
        )
        return candidate, 'created'

    def _find_race_for_legislator(self, state: str, chamber: str, district: str) -> 'Race | None':
        if not state or not chamber:
            return None

        qs = Race.objects.filter(
            election__state=state.upper(),
            race_status='active',
        ).select_related('election')

        if chamber == 'upper':
            qs = qs.filter(office_title__iregex=r'senate')
        elif chamber == 'lower':
            qs = qs.filter(office_title__iregex=r'house|represent|assembl|delegate')
        elif chamber == 'executive':
            qs = qs.filter(
                office_title__iregex=r'governor|attorney general|secretary|treasurer|auditor|comptroller'
            )
        else:
            return None

        if district:
            qs = qs.filter(
                django_models.Q(office_title__icontains=district) |
                django_models.Q(jurisdiction__icontains=district)
            )

        matches = list(qs[:2])
        return matches[0] if len(matches) == 1 else None

    def _find_candidate(self, race: Race | None, payload: dict) -> tuple[Candidate | None, bool]:
        candidate, ambiguous = self._match_by_external_ids(payload)
        if candidate is not None or ambiguous:
            return candidate, ambiguous

        candidate, ambiguous = self._match_by_cross_reference(payload)
        if candidate is not None or ambiguous:
            return candidate, ambiguous

        for name in self._payload_names(payload):
            if race is not None:
                candidate, ambiguous = self._match_by_name_within_race(race, name)
                if candidate is not None or ambiguous:
                    return candidate, ambiguous
                candidate, ambiguous = self._match_cross_race(race, name)
            else:
                candidate, ambiguous = self._match_cross_race_from_payload(payload, name)
            if candidate is not None or ambiguous:
                return candidate, ambiguous

        # Last-resort fallback: surname only, using the source's own structured
        # family_name field (not a guess parsed off a display name) — e.g.
        # OpenStates' display name can be a nickname ("Dru Tarr") that never
        # matches a ballot name ("Andrew Francis Robert Tarr") on any full-name
        # variant, but family_name ("Tarr") does. Scoped exactly like the
        # full-name tiers above, so a same-surname collision within that scope
        # still correctly returns ambiguous rather than guessing.
        last_name = self._normalize(payload.get('family_name') or '')
        if last_name:
            if race is not None:
                candidate, ambiguous = self._match_by_last_name_within_race(race, last_name)
                if candidate is not None or ambiguous:
                    return candidate, ambiguous
                candidate, ambiguous = self._match_last_name_cross_race(race, last_name)
            else:
                candidate, ambiguous = self._match_last_name_cross_race_from_payload(payload, last_name)
            if candidate is not None or ambiguous:
                return candidate, ambiguous

        return None, False

    def _match_by_external_ids(self, payload: dict) -> tuple[Candidate | None, bool]:
        for field in self.external_id_fields:
            value = payload.get(field)
            if not value:
                continue
            matches = list(Candidate.objects.filter(**{field: value})[:2])
            if len(matches) == 1:
                return matches[0], False
            if len(matches) > 1:
                return None, True
        return None, False

    def _match_by_cross_reference(self, payload: dict) -> tuple[Candidate | None, bool]:
        fec_ids = payload.get('fec_candidate_ids') or payload.get('fec_ids') or []
        if isinstance(fec_ids, str):
            fec_ids = [fec_ids]
        matches = list(Candidate.objects.filter(fec_candidate_id__in=fec_ids).distinct()[:2])
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            return None, True
        return None, False

    def _match_by_name_within_race(self, race: Race, name: str) -> tuple[Candidate | None, bool]:
        normalized_name = self._normalize(name)
        if not normalized_name:
            return None, False
        matches = [candidate for candidate in race.candidates.all() if self._normalize(candidate.name) == normalized_name]
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            return None, True
        return None, False

    def _match_cross_race(self, race: Race, name: str) -> tuple[Candidate | None, bool]:
        normalized_name = self._normalize(name)
        state = race.election.state
        office_type = race.normalized_office_title or self._normalize(race.office_title)
        if not normalized_name or not state or not office_type:
            return None, False

        matches = [
            candidate
            for candidate in Candidate.objects.filter(
                race__election__state=state,
                race__normalized_office_title=office_type,
            ).select_related('race', 'race__election')
            if self._normalize(candidate.name) == normalized_name
        ]
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            return None, True
        return None, False

    def _candidate_last_name(self, name: str) -> str:
        parts = self._normalize(name).split()
        return parts[-1] if parts else ''

    def _match_by_last_name_within_race(self, race: Race, last_name: str) -> tuple[Candidate | None, bool]:
        if not last_name:
            return None, False
        matches = [
            candidate
            for candidate in race.candidates.all()
            if self._candidate_last_name(candidate.name) == last_name
        ]
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            return None, True
        return None, False

    def _match_last_name_cross_race(self, race: Race, last_name: str) -> tuple[Candidate | None, bool]:
        state = race.election.state
        office_type = race.normalized_office_title or self._normalize(race.office_title)
        if not last_name or not state or not office_type:
            return None, False

        matches = [
            candidate
            for candidate in Candidate.objects.filter(
                race__election__state=state,
                race__normalized_office_title=office_type,
            ).select_related('race', 'race__election')
            if self._candidate_last_name(candidate.name) == last_name
        ]
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            return None, True
        return None, False

    def _match_last_name_cross_race_from_payload(self, payload: dict, last_name: str) -> tuple[Candidate | None, bool]:
        state = (payload.get('state') or '').upper()
        if not last_name or not state:
            return None, False

        office_type = (payload.get('office_type') or '').upper()
        district = self._normalize_district(payload.get('district'))

        if office_type in {'H', 'S'}:
            matches = [
                candidate
                for candidate in Candidate.objects.filter(race__election__state=state).select_related('race', 'race__election')
                if self._candidate_last_name(candidate.name) == last_name
                and self._race_matches_congressional_office(candidate.race, office_type, district)
            ]
            if len(matches) == 1:
                return matches[0], False
            if len(matches) > 1:
                return None, True
            return None, False

        chamber = (payload.get('chamber') or '').lower()
        if chamber in {'upper', 'lower'}:
            keywords = self._UPPER_CHAMBER_KEYWORDS if chamber == 'upper' else self._LOWER_CHAMBER_KEYWORDS
            candidates = list(Candidate.objects.filter(race__election__state=state).select_related('race', 'race__election'))
            matches = [
                candidate
                for candidate in candidates
                if self._candidate_last_name(candidate.name) == last_name
                and any(
                    keyword in self._normalize(candidate.race.normalized_office_title or candidate.race.office_title)
                    for keyword in keywords
                )
            ]
            if len(matches) == 1:
                return matches[0], False
            if len(matches) > 1:
                return None, True

        return None, False

    _UPPER_CHAMBER_KEYWORDS = frozenset({'senate'})
    _LOWER_CHAMBER_KEYWORDS = frozenset({'house', 'assembly', 'delegate', 'representative'})

    def _match_cross_race_from_payload(self, payload: dict, name: str) -> tuple[Candidate | None, bool]:
        normalized_name = self._normalize(name)
        state = (payload.get('state') or '').upper()
        if not normalized_name or not state:
            return None, False

        office_type = (payload.get('office_type') or '').upper()
        district = self._normalize_district(payload.get('district'))

        if office_type in {'H', 'S'}:
            matches = [
                candidate
                for candidate in Candidate.objects.filter(race__election__state=state).select_related('race', 'race__election')
                if self._normalize(candidate.name) == normalized_name
                and self._race_matches_congressional_office(candidate.race, office_type, district)
            ]
            if len(matches) == 1:
                return matches[0], False
            if len(matches) > 1:
                return None, True
            return None, False

        chamber = (payload.get('chamber') or '').lower()
        if chamber in {'upper', 'lower'}:
            keywords = self._UPPER_CHAMBER_KEYWORDS if chamber == 'upper' else self._LOWER_CHAMBER_KEYWORDS
            candidates = list(Candidate.objects.filter(race__election__state=state).select_related('race', 'race__election'))
            matches = [
                candidate
                for candidate in candidates
                if self._normalize(candidate.name) == normalized_name
                and any(
                    keyword in self._normalize(candidate.race.normalized_office_title or candidate.race.office_title)
                    for keyword in keywords
                )
            ]
            if len(matches) == 1:
                return matches[0], False
            if len(matches) > 1:
                return None, True

        return None, False

    def _race_matches_congressional_office(self, race: Race, office_type: str, district: str) -> bool:
        race_office_type = self._infer_congressional_office_type(race)
        if race_office_type != office_type:
            return False
        if office_type != 'H':
            return True
        return self._extract_district_number(race) == district

    def _infer_congressional_office_type(self, race: Race) -> str:
        normalized_title = self._normalize(race.normalized_office_title or race.office_title)
        ocd_division_id = (race.ocd_division_id or '').lower()
        if '/cd:' in ocd_division_id:
            return 'H'
        if 'u.s. senate' in normalized_title or 'us senate' in normalized_title or 'united states senate' in normalized_title:
            return 'S'
        if any(token in normalized_title for token in ('u.s. house', 'us house', 'united states house', 'representative')):
            return 'H'
        return ''

    def _extract_district_number(self, race: Race) -> str:
        for value in (race.ocd_division_id, race.office_title, race.jurisdiction):
            match = CONGRESSIONAL_DISTRICT_RE.search(value or '')
            if match:
                return self._normalize_district(match.group(1))
        return ''

    def _payload_name(self, payload: dict) -> str:
        if payload.get('name'):
            return str(payload['name'])
        if payload.get('official_full_name'):
            return str(payload['official_full_name'])
        first_name = str(payload.get('first_name') or '').strip()
        last_name = str(payload.get('last_name') or '').strip()
        return f'{first_name} {last_name}'.strip()

    def _payload_names(self, payload: dict) -> list[str]:
        """Primary payload name, plus any alternate names (e.g. OpenStates
        other_names), tried in order until one produces a match."""
        names = [self._payload_name(payload)]
        for alt in payload.get('other_names') or []:
            alt_name = str(alt or '').strip()
            if alt_name and alt_name not in names:
                names.append(alt_name)
        return [n for n in names if n]

    @staticmethod
    def _normalize_district(value) -> str:
        digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
        return digits.lstrip('0') or ('0' if digits else '')

    @staticmethod
    def _normalize(value: str) -> str:
        return ' '.join((value or '').strip().lower().split())
