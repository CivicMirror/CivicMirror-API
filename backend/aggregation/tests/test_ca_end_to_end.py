from datetime import date

import pytest

from aggregation import ingest
from aggregation.migrations._seed_data import seed
from aggregation.models import SourcePrecedence
from elections.models import Election


@pytest.mark.django_db
def test_civic_and_ca_sos_merge_into_one_election_with_expected_ownership():
    seed(SourcePrecedence)
    identity = dict(state="CA", election_type="primary",
                    election_date=date(2026, 6, 2), jurisdiction_level="state")

    # Civic first (baseline)
    civic = ingest.ingest_election(
        source="civic_api", source_id="11255", identity=identity,
        fields={"name": "California Primary Election"},
    )
    r = ingest.ingest_race(
        election=civic, source="civic_api",
        identity={"office_title": "Governor", "ocd_division_id": "ocd-division/country:us/state:ca", "race_type": "candidate"},
        fields={"office_title": "Governor", "jurisdiction": "California"},
    )
    ingest.ingest_candidate(race=r, source="civic_api", name="Xavier Becerra",
                            party="Democratic Party", fields={"image_url": "https://civic/p.jpg"})

    # CA SOS augments (results + date authority)
    ca = ingest.ingest_election(
        source="ca_sos", source_id="ca_sos_2026_primary", identity=identity,
        fields={"name": "2026 California Primary Election"},
    )
    r2 = ingest.ingest_race(
        election=ca, source="ca_sos",
        identity={"office_title": "Governor", "ocd_division_id": "ocd-division/country:us/state:ca", "race_type": "candidate"},
        fields={"results_url": "https://api.sos.ca.gov/returns/governor"},
    )
    ingest.ingest_candidate(race=r2, source="ca_sos", name="Becerra, Xavier",
                            party="Dem", fields={"incumbent": False,
                            "source_metadata": {"ca_votes": "89,380"}})

    assert Election.objects.filter(state="CA", election_type="primary").count() == 1
    assert civic.pk == ca.pk
    assert set(ca.contributing_sources) == {"civic_api", "ca_sos"}
    assert r.pk == r2.pk                                   # one merged race
    assert r2.results_url == "https://api.sos.ca.gov/returns/governor"
    assert r2.field_provenance["results_url"] == "ca_sos"
    cand = r2.candidates.get()                             # one merged candidate
    assert cand.image_url == "https://civic/p.jpg"         # contacts: civic
    assert cand.normalized_party == "DEM"
