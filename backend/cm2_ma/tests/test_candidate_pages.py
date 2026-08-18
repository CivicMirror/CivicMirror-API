from cm2_ma.constants import SEC_BASE_URL
from cm2_ma.sources.candidate_pages import MaCandidatePageSource, parse_candidate_page

# Real markup, captured live from dem-state-primary-candidates2026.htm during design.
_FIXTURE = b"""
<h2 id="senator-in-congress">Senator in Congress</h2>
<p>Edward J. Markey, 360 Charles St., Malden</p>
<p>Seth Moulton, 37 Chestnut St., Salem</p>

<h2 id="councillor">Councillor</h2>
<h3>Fourth District</h3>
<p>Christopher A. Iannella, Jr., 263 Pond St., Boston</p>
<p>Ronald Primo Iacobucci, 430 Adams St., Quincy</p>

<h2 id="DA">District Attorney</h2>
<h3>Plymouth District</h3>
<p>No Nominations</p>

<h3>Suffolk District</h3>
<p>Kevin R. Hayden, 199 Beech St., Boston</p>
"""


def test_statewide_rows_have_no_district_label():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    markey = next(c for c in result.candidates if c.reported_name == "Edward J. Markey")
    assert markey.office_label == "Senator in Congress"
    assert markey.district_label is None
    assert markey.address == "360 Charles St., Malden"
    assert markey.party == "DEMOCRATIC"


def test_district_rows_carry_the_h3_label():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    iacobucci = next(c for c in result.candidates if c.reported_name == "Ronald Primo Iacobucci")
    assert iacobucci.office_label == "Councillor"
    assert iacobucci.district_label == "Fourth District"


def test_suffix_in_name_does_not_break_on_the_embedded_comma():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    iannella = next(c for c in result.candidates if "Iannella" in c.reported_name)
    assert iannella.reported_name == "Christopher A. Iannella, Jr."
    assert iannella.suffix == "Jr."
    assert iannella.given_name == "Christopher"
    assert iannella.family_name == "Iannella"
    assert iannella.address == "263 Pond St., Boston"


def test_no_nominations_is_not_a_candidate_but_is_recorded():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    assert not any(c.district_label == "Plymouth District" for c in result.candidates)
    assert ("District Attorney", "Plymouth District") in result.no_nominations


def test_reported_name_survives_even_with_imperfect_given_family_split():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    hayden = next(c for c in result.candidates if c.reported_name == "Kevin R. Hayden")
    assert hayden.given_name == "Kevin"
    assert hayden.family_name == "Hayden"
    assert hayden.middle_name == "R."


def test_source_url_and_party_are_configured():
    url = f"{SEC_BASE_URL}/divisions/elections/research-and-statistics/dem-state-primary-candidates2026.htm"
    source = MaCandidatePageSource(url=url, party="DEMOCRATIC")

    assert source.url == url

    result = source.parse(_FIXTURE)
    # Markey, Moulton, Iannella, Iacobucci, Hayden -- "No Nominations" isn't a candidate.
    assert len(result.candidates) == 5
