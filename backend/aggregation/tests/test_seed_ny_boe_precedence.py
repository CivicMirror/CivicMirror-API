from datetime import date

import pytest

from aggregation import ingest
from aggregation.models import SourcePrecedence
from elections.models import Candidate, Election, Race

_NY_ROWS = [
    ("identity", "ny_boe", 0),
    ("identity", "civic_api", 1),
    ("date", "ny_boe", 0),
    ("date", "civic_api", 1),
    ("status", "ny_boe", 0),
    ("status", "civic_api", 1),
    ("party", "ny_boe", 0),
    ("party", "civic_api", 1),
    ("district", "ny_boe", 0),
    ("district", "civic_api", 1),
    ("results", "ny_boe", 0),
    ("results", "civic_api", 1),
    ("contacts", "civic_api", 0),
    ("contacts", "ny_boe", 1),
]


@pytest.fixture
def ny_precedence(db):
    for field_group, source, rank in _NY_ROWS:
        SourcePrecedence.objects.update_or_create(
            state="NY",
            field_group=field_group,
            source=source,
            defaults={"rank": rank},
        )


@pytest.mark.django_db
def test_ny_boe_precedence_rows_exist(ny_precedence):
    rows = set(
        SourcePrecedence.objects.filter(state="NY").values_list("field_group", "source", "rank")
    )

    assert rows.issuperset(set(_NY_ROWS))


@pytest.mark.django_db
def test_ny_boe_owns_authoritative_race_fields_over_civic(ny_precedence):
    election = Election.objects.create(
        name="NY Primary",
        election_date=date(2026, 6, 23),
        election_type=Election.ElectionType.PRIMARY,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NY",
    )
    race, _ = ingest.ingest_race(
        election=election,
        source="civic_api",
        identity={"office_title": "Representative in Congress", "ocd_division_id": "", "race_type": "candidate"},
        fields={
            "office_title": "Representative in Congress",
            "jurisdiction": "New York",
            "geography_scope": "statewide",
            "max_selections": 1,
        },
    )

    updated, _ = ingest.ingest_race(
        election=election,
        source="ny_boe",
        identity={"office_title": "Representative in Congress", "ocd_division_id": "", "race_type": "candidate"},
        fields={
            "office_title": "Representative in Congress",
            "jurisdiction": "Congressional District 19",
            "geography_scope": "district",
            "max_selections": 2,
        },
    )

    assert updated.pk == race.pk
    assert updated.source == "ny_boe"
    assert updated.geography_scope == "district"
    assert updated.max_selections == 2
    assert updated.field_provenance["max_selections"] == "ny_boe"


@pytest.mark.django_db
def test_ny_boe_candidate_party_wins_but_civic_contact_remains(ny_precedence):
    election = Election.objects.create(
        name="NY Primary",
        election_date=date(2026, 6, 23),
        election_type=Election.ElectionType.PRIMARY,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NY",
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="Governor",
        jurisdiction="New York",
        geography_scope="statewide",
        source=Race.Source.CIVIC_API,
    )

    candidate, _ = ingest.ingest_candidate(
        race=race,
        source="civic_api",
        name="Alex Rivera",
        party="",
        fields={"website_url": "https://example.test/alex"},
    )
    updated, _ = ingest.ingest_candidate(
        race=race,
        source="ny_boe",
        name="Alex Rivera",
        party="Democratic",
        fields={"candidate_status": Candidate.CandidateStatus.RUNNING, "website_url": ""},
    )

    assert updated.pk == candidate.pk
    assert updated.party == "Democratic"
    assert updated.website_url == "https://example.test/alex"
    assert updated.field_provenance["party"] == "ny_boe"
    assert updated.field_provenance["website_url"] == "civic_api"
