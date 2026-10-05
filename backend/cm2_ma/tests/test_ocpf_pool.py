from cm2_ma.mapping.ocpf_pool import OcpfCandidatePool
from cm2_ma.source_records import OcpfCandidateRow, OcpfDistrict

_DISTRICTS = (
    OcpfDistrict(district_code=231, office_type="House", district_description="9th Essex"),
    OcpfDistrict(district_code=1114, office_type="Statewide", district_description="Auditor"),
)


def _candidate(**overrides) -> OcpfCandidateRow:
    defaults = dict(
        cpf_id=10010,
        first_name="Steven",
        last_name="Angelo",
        street_address="39 Popmonet Rd",
        city="E. Falmouth",
        state="MA",
        zip_code="02536",
        district_code_sought=231,
        office_type_sought="House",
        district_name_sought="9th Essex",
        closed_date="",
        party_affiliation="Democratic",
    )
    defaults.update(overrides)
    return OcpfCandidateRow(**defaults)


def test_finds_exact_active_match_by_name_and_district_code():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_candidate(),))

    match = pool.find_by_name_and_district_code(full_name="Steven Angelo", district_code=231)

    assert match is not None
    assert match.cpf_id == 10010


def test_match_is_case_and_whitespace_insensitive():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_candidate(),))

    match = pool.find_by_name_and_district_code(full_name="  steven   ANGELO ", district_code=231)

    assert match is not None
    assert match.cpf_id == 10010


def test_closed_candidates_are_excluded_from_matching():
    closed = _candidate(cpf_id=10025, closed_date="7/12/2013")
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(closed,))

    match = pool.find_by_name_and_district_code(full_name="Steven Angelo", district_code=231)

    assert match is None


def test_wrong_district_code_does_not_match():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_candidate(),))

    match = pool.find_by_name_and_district_code(full_name="Steven Angelo", district_code=1114)

    assert match is None


def test_ambiguous_same_name_same_district_returns_none():
    same_name_twice = (
        _candidate(cpf_id=10010),
        _candidate(cpf_id=99999),
    )
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=same_name_twice)

    match = pool.find_by_name_and_district_code(full_name="Steven Angelo", district_code=231)

    assert match is None


def test_no_match_returns_none_not_an_error():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_candidate(),))

    match = pool.find_by_name_and_district_code(full_name="Nobody Here", district_code=231)

    assert match is None
