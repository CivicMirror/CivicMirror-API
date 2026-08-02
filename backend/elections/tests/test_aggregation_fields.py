from datetime import date

import pytest

from elections.models import Candidate, Election, ElectionSourceLink, Race


@pytest.mark.django_db
def test_election_has_canonical_and_provenance_fields():
    e = Election.objects.create(
        name="2026 California Primary Election", election_date=date(2026, 6, 2),
        election_type="primary", jurisdiction_level="state", state="CA",
        source_id="ca:primary:2026-06-02:state",
        canonical_key="CA:primary:2026-06-02:state",
    )
    assert e.field_provenance == {}
    assert e.contributing_sources == []
    assert e.needs_review is False


@pytest.mark.django_db
def test_election_source_link_unique_per_source():
    e = Election.objects.create(
        name="x", election_date=date(2026, 6, 2), election_type="primary",
        jurisdiction_level="state", state="CA", source_id="k1",
        canonical_key="CA:primary:2026-06-02:state",
    )
    ElectionSourceLink.objects.create(election=e, source="civic_api", source_id="11255")
    with pytest.raises(Exception):
        ElectionSourceLink.objects.create(election=e, source="civic_api", source_id="other")


@pytest.mark.django_db
def test_candidate_normalized_party_field_exists():
    e = Election.objects.create(
        name="x", election_date=date(2026, 6, 2), election_type="primary",
        jurisdiction_level="state", state="CA", source_id="k2",
    )
    r = Race.objects.create(election=e, race_type="candidate", office_title="Governor",
                            jurisdiction="California", geography_scope="statewide", source="ca_sos")
    c = Candidate.objects.create(race=r, name="Jane Doe", party="Dem", normalized_party="DEM")
    assert c.normalized_party == "DEM"


@pytest.mark.django_db
def test_candidate_image_url_and_website_url_accept_long_cdn_urls():
    """
    Regression test for #127: OpenStates CDN photo URLs with long query
    strings/tokens routinely exceed Django's URLField default max_length=200,
    crashing enrichment with StringDataRightTruncation. Both fields were
    widened to max_length=1000.
    """
    e = Election.objects.create(
        name="x", election_date=date(2026, 6, 2), election_type="primary",
        jurisdiction_level="state", state="CA", source_id="k3",
    )
    r = Race.objects.create(election=e, race_type="candidate", office_title="Governor",
                            jurisdiction="California", geography_scope="statewide", source="ca_sos")
    long_url = "https://cdn.example.com/photos/legislator.jpg?" + "token=" + "a" * 250
    assert len(long_url) > 200
    c = Candidate.objects.create(race=r, name="Jane Doe", image_url=long_url, website_url=long_url)
    c.refresh_from_db()
    assert c.image_url == long_url
    assert c.website_url == long_url
