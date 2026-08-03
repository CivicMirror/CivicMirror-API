"""
Business logic for mock voting, tally calculation, and community race submission.
"""
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_date

from elections.models import Candidate, MeasureOption, Race

from .models import MockVote, UserProfile

# ---------------------------------------------------------------------------
# Vote casting
# ---------------------------------------------------------------------------

def cast_vote(*, uid: str, race: Race, payload: dict):
    """
    Validate and record a mock vote.

    Returns (result_dict, error_dict, http_status).
    On success: (result, None, 201).
    On failure: (None, error, 400/409).
    """
    if race.race_status != Race.RaceStatus.ACTIVE:
        return None, {'error': 'Voting is not open for this race.'}, 400

    error = _validate_vote_payload(race, payload)
    if error:
        return None, error, 400

    candidate_ids = payload.get('candidate_ids')
    measure_option_id = payload.get('measure_option_id')
    ranked_selections = payload.get('ranked_selections')

    try:
        with transaction.atomic():
            vote = MockVote.objects.create(
                uid=uid,
                race=race,
                candidate_ids=candidate_ids,
                measure_option_id=measure_option_id,
                ranked_selections=ranked_selections,
            )
            _get_or_create_profile(uid)
    except IntegrityError:
        return None, {'error': 'You have already voted on this race.'}, 409

    result = {
        'id': vote.id,
        'race': vote.race_id,
        'selection_type': vote.selection_type,
        'candidate_ids': vote.candidate_ids,
        'measure_option_id': vote.measure_option_id,
        'ranked_selections': vote.ranked_selections,
        'created_at': vote.created_at.isoformat(),
    }
    return result, None, 201


def _validate_vote_payload(race: Race, payload: dict):
    """Return an error dict if the payload is invalid, else None."""
    candidate_ids = payload.get('candidate_ids')
    measure_option_id = payload.get('measure_option_id')
    ranked_selections = payload.get('ranked_selections')

    if race.race_type == Race.RaceType.MEASURE:
        if measure_option_id is None:
            return {'error': 'measure_option_id is required for measure races.'}
        if candidate_ids or ranked_selections:
            return {'error': 'Only measure_option_id should be provided for measure races.'}
        if not MeasureOption.objects.filter(pk=measure_option_id, race=race).exists():
            return {'error': 'Invalid measure_option_id for this race.'}
        return None

    # Candidate race
    if measure_option_id is not None:
        return {'error': 'measure_option_id should not be provided for candidate races.'}

    vote_method = race.vote_method

    if vote_method == Race.VoteMethod.RANKED_CHOICE:
        if not ranked_selections:
            return {'error': 'ranked_selections is required for ranked-choice races.'}
        if candidate_ids:
            return {'error': 'Use ranked_selections (not candidate_ids) for ranked-choice races.'}
        if not isinstance(ranked_selections, list) or not ranked_selections:
            return {'error': 'ranked_selections must be a non-empty list.'}
        if len(ranked_selections) != len(set(ranked_selections)):
            return {'error': 'ranked_selections must not contain duplicate candidate IDs.'}
        valid_ids = set(Candidate.objects.filter(race=race).values_list('id', flat=True))
        invalid = [cid for cid in ranked_selections if cid not in valid_ids]
        if invalid:
            return {'error': f'Invalid candidate IDs: {invalid}'}
        return None

    # single_choice / multi_seat / yes_no — all use candidate_ids
    if not candidate_ids:
        return {'error': 'candidate_ids is required for this vote method.'}
    if ranked_selections:
        return {'error': 'Use candidate_ids (not ranked_selections) for this vote method.'}
    if not isinstance(candidate_ids, list) or not candidate_ids:
        return {'error': 'candidate_ids must be a non-empty list.'}
    if len(candidate_ids) != len(set(candidate_ids)):
        return {'error': 'candidate_ids must not contain duplicates.'}

    if vote_method == Race.VoteMethod.SINGLE_CHOICE or vote_method == Race.VoteMethod.YES_NO:
        if len(candidate_ids) != 1:
            return {'error': 'Exactly one candidate must be selected for this vote method.'}
    elif vote_method == Race.VoteMethod.MULTI_SEAT:
        if len(candidate_ids) > race.max_selections:
            return {'error': f'Too many selections; this race allows up to {race.max_selections}.'}

    valid_ids = set(Candidate.objects.filter(race=race).values_list('id', flat=True))
    invalid = [cid for cid in candidate_ids if cid not in valid_ids]
    if invalid:
        return {'error': f'Invalid candidate IDs: {invalid}'}

    return None


# ---------------------------------------------------------------------------
# Tally calculation
# ---------------------------------------------------------------------------

def get_tally(race: Race) -> dict:
    """Compute the current mock vote tally for a race."""
    votes = list(MockVote.objects.filter(race=race))
    total = len(votes)

    if race.race_type == Race.RaceType.MEASURE:
        options = _tally_measure(race, votes, total)
    else:
        options = _tally_candidates(race, votes, total)

    return {
        'race_id': race.id,
        'total_votes': total,
        'options': options,
        'breakdowns': {},
    }


def _tally_measure(race, votes, total):
    counts: dict[int, int] = {}
    for v in votes:
        if v.measure_option_id is not None:
            counts[v.measure_option_id] = counts.get(v.measure_option_id, 0) + 1

    options = []
    for opt in race.measure_options.all():
        count = counts.get(opt.id, 0)
        options.append({
            'id': opt.id,
            'label': opt.option_label,
            'type': 'measure_option',
            'count': count,
            'percent': _pct(count, total),
        })
    return sorted(options, key=lambda o: -o['count'])


def _tally_candidates(race, votes, total):
    """
    For ranked-choice races counts first-choice selections.
    For all other methods counts candidate_ids selections.
    """
    counts: dict[int, int] = {}
    for v in votes:
        if v.ranked_selections:
            # First-choice only for ranked-choice tally
            first = v.ranked_selections[0] if v.ranked_selections else None
            if first is not None:
                counts[first] = counts.get(first, 0) + 1
        elif v.candidate_ids:
            for cid in v.candidate_ids:
                counts[cid] = counts.get(cid, 0) + 1

    # total_votes for percentage: number of voters (not total selections)
    voter_count = len(votes)

    options = []
    for cand in race.candidates.all():
        count = counts.get(cand.id, 0)
        options.append({
            'id': cand.id,
            'label': cand.name,
            'type': 'candidate',
            'party': cand.party,
            'count': count,
            'percent': _pct(count, voter_count),
        })
    return sorted(options, key=lambda o: -o['count'])


def _pct(count: int, total: int) -> float:
    if not total:
        return 0.0
    return round(count / total * 100, 1)


# ---------------------------------------------------------------------------
# UserProfile helpers
# ---------------------------------------------------------------------------

def _get_or_create_profile(uid: str) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(uid=uid)
    return profile


def get_or_create_profile(uid: str) -> UserProfile:
    return _get_or_create_profile(uid)


# ---------------------------------------------------------------------------
# Community race creation
# ---------------------------------------------------------------------------

def _resolve_election(payload: dict):
    """
    Return (election, error_dict). If election_id is given, attach to that
    existing election. Otherwise auto-create one from election_date +
    location_name so community submitters never need to pick from a list.
    """
    from elections.models import Election

    if payload.get('election_id'):
        try:
            return Election.objects.get(pk=int(payload['election_id'])), None
        except (Election.DoesNotExist, ValueError, TypeError):
            return None, {'error': 'Invalid election_id.'}

    election_date = parse_date(str(payload.get('election_date') or ''))
    if not election_date:
        return None, {'error': 'election_date is required.'}

    location_name = (payload.get('location_name') or '').strip()
    if not location_name:
        return None, {'error': 'location_name is required.'}

    election, _ = Election.objects.get_or_create(
        election_date=election_date,
        name=f'{location_name} Local Election',
        defaults={'jurisdiction_level': Election.JurisdictionLevel.LOCAL},
    )
    return election, None


def create_community_race(*, uid: str, payload: dict):
    """
    Create a community-submitted race, auto-creating its Election from the
    submitted election_date/location_name when no election_id is supplied.

    Returns (race_instance, error_dict, http_status).
    """
    race_type = payload.get('race_type')
    if race_type not in (Race.RaceType.CANDIDATE, Race.RaceType.MEASURE):
        return None, {'error': f'Invalid race_type: {race_type}'}, 400

    election, error = _resolve_election(payload)
    if error:
        return None, error, 400

    location_name = (payload.get('location_name') or '').strip()
    candidates_data = payload.get('candidates') or []

    if race_type == Race.RaceType.CANDIDATE:
        office_title = (payload.get('office_title') or '').strip()
        if not office_title:
            return None, {'error': 'office_title is required.'}, 400

        geography_scope = payload.get('geography_scope') or payload.get('jurisdiction') or ''
        if not geography_scope:
            return None, {'error': 'jurisdiction is required.'}, 400

        if not any(isinstance(c, dict) and c.get('name') for c in candidates_data):
            return None, {'error': 'At least one candidate is required.'}, 400

        vote_method = payload.get('vote_method') or Race.VoteMethod.SINGLE_CHOICE
        ballot_type = ''
        yes_vote_details = ''
        no_vote_details = ''
        source_links = [payload['source_url']] if payload.get('source_url') else []
    else:
        office_title = (payload.get('office_title') or payload.get('question_title') or '').strip()
        if not office_title:
            return None, {'error': 'question_title is required.'}, 400

        yes_vote_details = payload.get('yes_vote_details') or ''
        no_vote_details = payload.get('no_vote_details') or ''
        if not yes_vote_details or not no_vote_details:
            return None, {'error': 'yes_vote_details and no_vote_details are required.'}, 400

        geography_scope = payload.get('geography_scope') or 'local'
        ballot_type = payload.get('ballot_type') or ''
        vote_method = payload.get('vote_method') or Race.VoteMethod.YES_NO
        source_links = list(payload.get('source_links') or [])

    valid_methods = [c[0] for c in Race.VoteMethod.choices]
    if vote_method not in valid_methods:
        return None, {'error': f'Invalid vote_method: {vote_method}'}, 400

    jurisdiction = (location_name or payload.get('jurisdiction') or '').strip()
    if not jurisdiction:
        return None, {'error': 'jurisdiction is required.'}, 400

    canonical_key = f'community:{uuid.uuid4().hex}'

    with transaction.atomic():
        race = Race.objects.create(
            election=election,
            race_type=race_type,
            office_title=office_title,
            jurisdiction=jurisdiction,
            geography_scope=geography_scope,
            location_name=location_name,
            ballot_type=ballot_type,
            yes_vote_details=yes_vote_details,
            no_vote_details=no_vote_details,
            vote_method=vote_method,
            source=Race.Source.COMMUNITY,
            race_status=Race.RaceStatus.PENDING_REVIEW,
            submitted_by_uid=uid,
            canonical_key=canonical_key,
            source_links=source_links,
        )

        if race_type == Race.RaceType.CANDIDATE:
            for c in candidates_data:
                if not isinstance(c, dict) or not c.get('name'):
                    continue
                Candidate.objects.create(
                    race=race,
                    name=c['name'],
                    party=c.get('party', ''),
                    description=c.get('description', ''),
                    image_url=c.get('image_url', ''),
                    website_url=c.get('website_url', ''),
                    candidate_status=(
                        Candidate.CandidateStatus.WRITE_IN
                        if c.get('candidate_type') == 'write_in'
                        else Candidate.CandidateStatus.RUNNING
                    ),
                )
        else:
            MeasureOption.objects.create(race=race, option_label='Yes')
            MeasureOption.objects.create(race=race, option_label='No')

        _get_or_create_profile(uid)

    race.refresh_from_db()
    race.candidates.all()  # warm cache
    race.measure_options.all()  # warm cache
    return race, None, 201
