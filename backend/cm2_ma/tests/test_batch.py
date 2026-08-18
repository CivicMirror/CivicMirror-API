from datetime import date

import pytest

from cm2_ingestion.contracts import ContractValidationError, ElectionRecord
from cm2_ma.mapping.batch import build_pre_election_batch
from cm2_ma.mapping.ocpf_pool import OcpfCandidatePool
from cm2_ma.source_records import OcpfCandidateRow, OcpfDistrict, SecretaryCandidateRow

_PRIMARY = ElectionRecord(
    public_id="ma/election/2026-09-01/primary/test",
    name="2026 Massachusetts State Primary",
    election_date=date(2026, 9, 1),
    election_type="primary",
    lifecycle_status="upcoming",
)

_DISTRICTS = (
    OcpfDistrict(district_code=1114, office_type="Statewide", district_description="Auditor"),
    OcpfDistrict(district_code=231, office_type="House", district_description="9th Essex"),
)


def _row(**overrides) -> SecretaryCandidateRow:
    defaults = dict(
        office_label="Representative in General Court",
        district_label="9th Essex District",
        party="DEMOCRATIC",
        raw_line="Steven Angelo, 39 Popmonet Rd, E. Falmouth",
        reported_name="Steven Angelo",
        given_name="Steven",
        middle_name="",
        family_name="Angelo",
        suffix="",
        address="39 Popmonet Rd, E. Falmouth",
    )
    defaults.update(overrides)
    return SecretaryCandidateRow(**defaults)


def _ocpf_candidate(**overrides) -> OcpfCandidateRow:
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


def test_matched_candidate_gets_a_pre_resolved_person_public_id():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_ocpf_candidate(),))
    batch = build_pre_election_batch(
        (_row(),), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=pool
    )

    assert len(batch.candidates) == 1
    candidate = batch.candidates[0]
    assert candidate.person_public_id is not None
    assert candidate.person_public_id.startswith("ma/person/")


def test_unmatched_candidate_falls_back_to_no_pre_resolved_identity():
    empty_pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    batch = build_pre_election_batch(
        (_row(),), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=empty_pool
    )

    assert batch.candidates[0].person_public_id is None


def test_federal_office_never_pre_resolves_even_with_a_populated_pool():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_ocpf_candidate(),))
    row = _row(
        office_label="Representative in Congress",
        district_label="First District",
        reported_name="Someone Federal",
        given_name="Someone",
        family_name="Federal",
        raw_line="Someone Federal, 1 Main St., Boston",
        address="1 Main St., Boston",
    )
    batch = build_pre_election_batch(
        (row,), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=pool
    )

    assert batch.candidates[0].person_public_id is None


def test_contests_carry_the_fixed_party_and_default_vote_for():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    batch = build_pre_election_batch(
        (_row(),), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=pool
    )

    assert len(batch.contests) == 1
    contest = batch.contests[0]
    assert contest.party_contest == "DEMOCRATIC"
    assert contest.is_partisan is True
    assert contest.vote_for == 1
    assert contest.election_public_id == _PRIMARY.public_id


def test_no_nominations_becomes_a_notice_not_a_candidate():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    batch = build_pre_election_batch(
        (),
        no_nominations=(("District Attorney", "Plymouth District"),),
        discovered_elections=(_PRIMARY,),
        ocpf_pool=pool,
    )

    assert batch.candidates == ()
    assert len(batch.notices) == 1
    assert batch.notices[0].code == "no_nominations"


def test_missing_primary_election_raises():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    general = ElectionRecord(
        public_id="ma/election/2026-11-03/general/test",
        name="2026 Massachusetts State Election",
        election_date=date(2026, 11, 3),
        election_type="general",
    )

    with pytest.raises(ContractValidationError, match="primary"):
        build_pre_election_batch(
            (_row(),), no_nominations=(), discovered_elections=(general,), ocpf_pool=pool
        )


def test_batch_state_is_ma_and_validates_cleanly():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    batch = build_pre_election_batch(
        (_row(),), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=pool
    )

    assert batch.state == "MA"
    assert len(batch.jurisdictions) == 2  # state + 9th Essex District
    assert len(batch.offices) == 1
