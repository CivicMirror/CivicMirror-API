from datetime import date

import pytest

from aggregation import ingest
from aggregation.models import SourcePrecedence
from elections.models import Candidate, Election, Race


@pytest.fixture
def ca_precedence(db):
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="results", source="ca_sos", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="results", source="civic_api", rank=1)
    SourcePrecedence.objects.create(state="CA", field_group="contacts", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="contacts", source="ca_sos", rank=1)


def _election_identity():
    return dict(state="CA", election_type="primary",
                election_date=date(2026, 6, 2), jurisdiction_level="state")


@pytest.mark.django_db
def test_ingest_election_creates_canonical_row_and_source_link(ca_precedence):
    e, _ = ingest.ingest_election(
        source="ca_sos", source_id="ca_sos_2026_primary",
        identity=_election_identity(),
        fields={"name": "2026 California Primary Election", "status": "upcoming"},
    )
    assert e.canonical_key == "CA:primary:2026-06-02:state"
    assert "ca_sos" in e.contributing_sources
    assert e.source_links_rel.filter(source="ca_sos", source_id="ca_sos_2026_primary").exists()
    assert e.field_provenance["name"] == "ca_sos"


@pytest.mark.django_db
def test_two_sources_merge_onto_one_election(ca_precedence):
    e1, _ = ingest.ingest_election(
        source="ca_sos", source_id="ca_sos_2026_primary", identity=_election_identity(),
        fields={"name": "2026 California Primary Election"},
    )
    e2, _ = ingest.ingest_election(
        source="civic_api", source_id="11255", identity=_election_identity(),
        fields={"name": "California Primary Election"},
    )
    assert e1.pk == e2.pk
    assert set(e2.contributing_sources) == {"ca_sos", "civic_api"}
    # name is an 'identity' field; civic (rank 0) outranks ca_sos (inf default) -> civic wins
    assert e2.name == "California Primary Election"
    assert e2.field_provenance["name"] == "civic_api"


@pytest.mark.django_db
def test_higher_precedence_source_wins_per_field(ca_precedence):
    e, _ = ingest.ingest_election(source="ca_sos", source_id="x", identity=_election_identity(), fields={})
    # results field group: ca_sos outranks civic in CA
    ingest.ingest_race(
        election=e, source="civic_api",
        identity={"office_title": "Governor", "ocd_division_id": "", "race_type": "candidate"},
        fields={"office_title": "Governor", "results_url": "https://civic/results"},
    )
    r, _ = ingest.ingest_race(
        election=e, source="ca_sos",
        identity={"office_title": "Governor", "ocd_division_id": "", "race_type": "candidate"},
        fields={"results_url": "https://api.sos.ca.gov/returns/governor"},
    )
    assert r.results_url == "https://api.sos.ca.gov/returns/governor"
    assert r.field_provenance["results_url"] == "ca_sos"
    # office_title still owned by civic (only civic provided it)
    assert r.field_provenance["office_title"] == "civic_api"


@pytest.mark.django_db
def test_ingest_race_without_contest_variant_merges_same_office(ca_precedence):
    """Baseline: confirms the pre-existing collision this fix addresses —
    without contest_variant, two ingests for the same office/ocd/race_type
    merge into one Race (this is correct for non-partisan-primary sources
    like civic_api, and the reason VT's feed needs contest_variant)."""
    e, _ = ingest.ingest_election(source="ca_sos", source_id="x", identity=_election_identity(), fields={})
    r1, created1 = ingest.ingest_race(
        election=e, source="ca_sos",
        identity={"office_title": "Governor", "ocd_division_id": "", "race_type": "candidate"},
        fields={"office_title": "Governor"},
    )
    r2, created2 = ingest.ingest_race(
        election=e, source="ca_sos",
        identity={"office_title": "Governor", "ocd_division_id": "", "race_type": "candidate"},
        fields={"office_title": "Governor"},
    )
    assert created1 is True
    assert created2 is False
    assert r1.pk == r2.pk


@pytest.mark.django_db
def test_ingest_race_contest_variant_keeps_primary_parties_distinct(ca_precedence):
    """The bug contest_variant exists to fix: three primary parties running
    the same office (same office_title, same OCD, same race_type) must
    produce three distinct Races, not collapse into one."""
    e, _ = ingest.ingest_election(source="ca_sos", source_id="x", identity=_election_identity(), fields={})

    dem, dem_created = ingest.ingest_race(
        election=e, source="vt_sos",
        identity={
            "office_title": "Representative to Congress", "ocd_division_id": "",
            "race_type": "candidate", "contest_variant": "vt:federal:D:4:statewide",
        },
        fields={"office_title": "Representative to Congress", "ballot_type": "Democratic"},
    )
    rep, rep_created = ingest.ingest_race(
        election=e, source="vt_sos",
        identity={
            "office_title": "Representative to Congress", "ocd_division_id": "",
            "race_type": "candidate", "contest_variant": "vt:federal:R:4:statewide",
        },
        fields={"office_title": "Representative to Congress", "ballot_type": "Republican"},
    )
    # Re-ingesting the Democratic contest must resolve back to the same row,
    # not create a third one.
    dem_again, dem_again_created = ingest.ingest_race(
        election=e, source="vt_sos",
        identity={
            "office_title": "Representative to Congress", "ocd_division_id": "",
            "race_type": "candidate", "contest_variant": "vt:federal:D:4:statewide",
        },
        fields={"office_title": "Representative to Congress", "ballot_type": "Democratic"},
    )

    assert dem_created is True
    assert rep_created is True
    assert dem_again_created is False
    assert dem.pk != rep.pk
    assert dem.pk == dem_again.pk
    assert Race.objects.filter(election=e).count() == 2


@pytest.mark.django_db
def test_candidate_matching_by_normalized_name_and_party(ca_precedence):
    e, _ = ingest.ingest_election(source="ca_sos", source_id="x", identity=_election_identity(), fields={})
    r, _ = ingest.ingest_race(
        election=e, source="ca_sos",
        identity={"office_title": "Governor", "ocd_division_id": "", "race_type": "candidate"},
        fields={"office_title": "Governor"},
    )
    c1, _ = ingest.ingest_candidate(race=r, source="ca_sos", name="Xavier Becerra", party="Dem",
                                 fields={"incumbent": False})
    c2, _ = ingest.ingest_candidate(race=r, source="civic_api", name="Becerra, Xavier", party="Democratic Party",
                                 fields={"image_url": "https://civic/photo.jpg"})
    assert c1.pk == c2.pk
    assert c2.image_url == "https://civic/photo.jpg"           # contacts: civic owns
    assert c2.normalized_party == "DEM"


@pytest.mark.django_db
def test_ingest_candidate_same_name_different_party_updates_existing_row(ca_precedence):
    """The DB's unique_candidate_name_per_race constraint is (race, name) only —
    it has no notion of party. A second filing for the same name in the same
    race with a party string that doesn't normalize to the same code as the
    first must not attempt a second INSERT (that IntegrityErrors); it should
    reconcile onto the existing row instead, same as any other field update.
    """
    e, _ = ingest.ingest_election(source="or_sos", source_id="x", identity=_election_identity(), fields={})
    r, _ = ingest.ingest_race(
        election=e, source="or_sos",
        identity={"office_title": "State Representative", "ocd_division_id": "", "race_type": "candidate"},
        fields={"office_title": "State Representative"},
    )
    c1, created1 = ingest.ingest_candidate(race=r, source="or_sos", name="April Dobson", party="Democrat",
                                            fields={})
    c2, created2 = ingest.ingest_candidate(race=r, source="or_sos", name="April Dobson", party="D",
                                            fields={})

    assert created1 is True
    assert created2 is False
    assert c1.pk == c2.pk
    assert Candidate.objects.filter(race=r, name="April Dobson").count() == 1


@pytest.mark.django_db
def test_ingest_election_flags_review_when_date_missing(ca_precedence):
    e, _ = ingest.ingest_election(
        source="ca_sos", source_id="bad",
        identity={"state": "CA", "election_type": "primary",
                  "election_date": None, "jurisdiction_level": "state"},
        fields={"name": "Broken"},
    )
    assert e.needs_review is True
    assert e.canonical_key is None


@pytest.mark.django_db
def test_ingest_election_needs_review_is_idempotent(ca_precedence):
    """Re-syncing a needs-review election from the same source must reuse the
    row (looked up via ElectionSourceLink) instead of colliding on
    Election.source_id's unique constraint or creating an orphan duplicate."""
    bad_identity = {
        "state": "CA", "election_type": "primary",
        "election_date": None, "jurisdiction_level": "state",
    }
    e1, created1 = ingest.ingest_election(
        source="ca_sos", source_id="bad", identity=bad_identity, fields={"name": "Broken"},
    )
    e2, created2 = ingest.ingest_election(
        source="ca_sos", source_id="bad", identity=bad_identity, fields={"name": "Broken"},
    )
    assert created1 is True
    assert created2 is False
    assert e1.pk == e2.pk
    assert e2.source_links_rel.filter(source="ca_sos", source_id="bad").count() == 1


@pytest.mark.django_db
def test_ingest_election_returns_false_created_on_resync(ca_precedence):
    """A returning single-source election must report created=False, not True."""
    _, created1 = ingest.ingest_election(
        source="ca_sos", source_id="x", identity=_election_identity(),
        fields={"name": "CA Primary"},
    )
    _, created2 = ingest.ingest_election(
        source="ca_sos", source_id="x", identity=_election_identity(),
        fields={"name": "CA Primary"},
    )
    assert created1 is True
    assert created2 is False
