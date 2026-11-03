"""Tests for the sweep_civic_api management command (issue #229).

The two hold rules are the point of the command: provenance alone cannot tell
you whether a Civic-only race is safe to delete, because the results layer
writes OfficialResult without recording itself in contributing_sources.
"""
import pytest
from django.core.management import call_command

from aggregation.models import SourcePrecedence
from elections.models import Candidate, Election, Race
from results.models import OfficialResult

pytestmark = pytest.mark.django_db


def _election(**kw):
    defaults = dict(
        name="Test Election",
        election_date="2026-06-02",
        election_type=Election.ElectionType.PRIMARY,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="CA",
        canonical_key=None,
    )
    defaults.update(kw)
    return Election.objects.create(**defaults)


def _race(election, *, sources=None, office="Governor", key=None, source="civic_api"):
    return Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title=office,
        jurisdiction="CA",
        geography_scope="statewide",
        source=source,
        normalized_office_title=office.lower(),
        canonical_key=key or f"k-{election.pk}-{office}",
        contributing_sources=["civic_api"] if sources is None else sources,
    )


def test_deletes_civic_race_when_state_adapter_races_remain():
    election = _election(canonical_key="CA:primary:2026-06-02:state")
    civic = _race(election, office="Governor")
    _race(election, office="Governor (state)", sources=["ca_sos"], source="ca_sos")

    call_command("sweep_civic_api")

    assert not Race.objects.filter(pk=civic.pk).exists()


def test_holds_civic_race_that_is_sole_source_for_its_election():
    """Deleting these dedupes nothing -- it empties the election."""
    election = _election(canonical_key="WI:primary:2026-08-11:state", state="WI")
    civic = _race(election, office="Governor")

    call_command("sweep_civic_api")

    assert Race.objects.filter(pk=civic.pk).exists()


def test_holds_civic_race_carrying_official_results():
    """The MD #1888 case: civic_api on every field, yet holds certified results.
    OfficialResult.race is CASCADE, so deleting would destroy them silently."""
    election = _election(canonical_key="MD:primary:2026-06-23:state", state="MD")
    civic = _race(election, office="Attorney General")
    _race(election, office="Other", sources=["md_sbe"], source="md_sbe")
    cand = Candidate.objects.create(race=civic, name="A Brown", contributing_sources=["civic_api"])
    OfficialResult.objects.create(
        race=civic, candidate=cand, vote_count=568685,
        result_type="official", source_url="https://elections.maryland.gov/x",
    )

    call_command("sweep_civic_api")

    assert Race.objects.filter(pk=civic.pk).exists()
    assert OfficialResult.objects.filter(race=civic).count() == 1


def test_strips_civic_from_a_merged_race_without_deleting_it():
    election = _election(canonical_key="CA:primary:2026-06-02:state")
    merged = _race(election, office="Senator", sources=["ca_sos", "civic_api"], source="ca_sos")
    merged.field_provenance = {"office_title": "civic_api", "jurisdiction": "ca_sos"}
    merged.save()
    _race(election, office="Keep", sources=["ca_sos"], source="ca_sos")

    call_command("sweep_civic_api")

    merged.refresh_from_db()
    assert merged.contributing_sources == ["ca_sos"]
    assert merged.field_provenance["office_title"] == "ca_sos"


def test_releases_empty_contact_lock_but_preserves_a_real_value():
    election = _election(canonical_key="CA:primary:2026-06-02:state")
    race = _race(election, sources=["ca_sos"], source="ca_sos")
    empty = Candidate.objects.create(
        race=race, name="Empty", image_url="",
        field_provenance={"image_url": "civic_api"},
    )
    real = Candidate.objects.create(
        race=race, name="Real", image_url="https://example.test/p.jpg",
        field_provenance={"image_url": "civic_api"},
    )

    call_command("sweep_civic_api")

    empty.refresh_from_db()
    real.refresh_from_db()
    assert "image_url" not in empty.field_provenance
    assert real.field_provenance["image_url"] == "civic_api"
    assert real.image_url == "https://example.test/p.jpg"


def test_deletes_precedence_rows_including_the_global_wildcard():
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="contacts", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="contacts", source="ca_sos", rank=1)

    call_command("sweep_civic_api")

    assert not SourcePrecedence.objects.filter(source="civic_api").exists()
    assert SourcePrecedence.objects.filter(source="ca_sos").exists()


def test_deletes_civic_races_in_a_keyless_election_even_though_sole_source():
    """#2232: a keyless election IS the Civic defect -- ingest_election could not
    build a canonical key. Its contests belong to the per-state elections, so
    "sole source" must not protect them or the bug is preserved."""
    shell = _election(name="2026 General Midterm Election", state=None, canonical_key=None)
    civic = _race(shell, office="United States Senator", key="e2232|us senator")

    call_command("sweep_civic_api")

    assert not Race.objects.filter(pk=civic.pk).exists()
    shell.refresh_from_db()
    assert shell.state is None


def test_leaves_state_null_on_keyless_shells():
    """A NULL state is what keeps these rows poller-ineligible; both pollers
    filter state__in=supported."""
    shell = _election(name="2026 General Midterm Election", state=None, canonical_key=None)

    call_command("sweep_civic_api")

    shell.refresh_from_db()
    assert shell.state is None


def test_dry_run_writes_nothing():
    election = _election(canonical_key="CA:primary:2026-06-02:state")
    civic = _race(election, office="Governor")
    _race(election, office="Keep", sources=["ca_sos"], source="ca_sos")
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)

    call_command("sweep_civic_api", "--dry-run")

    assert Race.objects.filter(pk=civic.pk).exists()
    assert SourcePrecedence.objects.filter(source="civic_api").exists()


def test_is_idempotent():
    election = _election(canonical_key="CA:primary:2026-06-02:state")
    _race(election, office="Governor")
    _race(election, office="Keep", sources=["ca_sos"], source="ca_sos")
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)

    call_command("sweep_civic_api")
    before = Race.objects.count()
    call_command("sweep_civic_api")

    assert Race.objects.count() == before
