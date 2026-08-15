from datetime import date

import pytest

from cm2_ingestion.contracts import (
    CandidateFilingRecord,
    ContestRecord,
    ContractValidationError,
    ElectionRecord,
    IngestionNotice,
    JurisdictionRecord,
    OfficeRecord,
    PersonSourceEvidence,
    PreElectionBatch,
    validate_pre_election_batch,
)


def valid_batch(**overrides):
    values = {
        "state": "NC",
        "jurisdictions": (
            JurisdictionRecord(
                public_id="ocd-division/country:us/state:nc",
                name="North Carolina",
                classification="state",
                state="NC",
            ),
        ),
        "offices": (
            OfficeRecord(
                public_id="nc/us-senator",
                jurisdiction_public_id="ocd-division/country:us/state:nc",
                canonical_name="United States Senator",
                role="legislator",
                positions=1,
            ),
        ),
        "elections": (
            ElectionRecord(
                public_id="nc/2026-11-03/general",
                name="2026 General Election",
                election_date=date(2026, 11, 3),
                election_type="general",
                lifecycle_status="upcoming",
            ),
        ),
        "contests": (
            ContestRecord(
                public_id="nc/2026-11-03/general/us-senator",
                election_public_id="nc/2026-11-03/general",
                office_public_id="nc/us-senator",
                vote_for=1,
                is_partisan=True,
            ),
        ),
        "candidates": (
            CandidateFilingRecord(
                filing_key="us-senator/dedreana-freeman",
                contest_public_id="nc/2026-11-03/general/us-senator",
                ballot_name="DeDreana Freeman",
                party_candidate="DEM",
                source_records=(
                    PersonSourceEvidence(
                        source_row_key="candidate-row-county-1",
                        reported_name="DeDreana Freeman",
                        ballot_name="DeDreana Freeman",
                        protected_address="123 Private Lane",
                        protected_phone="919-555-0100",
                        protected_email="private@example.test",
                    ),
                    PersonSourceEvidence(
                        source_row_key="candidate-row-county-2",
                        reported_name="DeDreana Freeman",
                        ballot_name="DeDreana Freeman",
                    ),
                ),
            ),
        ),
    }
    values.update(overrides)
    return PreElectionBatch(**values)


def test_valid_batch_accepts_multiple_source_rows_for_one_normalized_candidacy():
    validate_pre_election_batch(valid_batch())


def test_valid_batch_accepts_public_structured_ingestion_notice():
    batch = valid_batch(
        notices=(
            IngestionNotice(
                code="csv_only_election",
                subject_type="election",
                subject_public_id="nc/election/2026-03-03/primary",
            ),
        )
    )

    validate_pre_election_batch(batch)


@pytest.mark.parametrize(
    "notice",
    [
        IngestionNotice("CSV-only", "election", "nc/election/2026-03-03/primary"),
        IngestionNotice("csv_only_election", "", "nc/election/2026-03-03/primary"),
        IngestionNotice("csv_only_election", "election", ""),
    ],
)
def test_batch_rejects_malformed_ingestion_notice_without_echoing_source_evidence(notice):
    protected_value = "never-publish@example.test"
    batch = valid_batch(
        notices=(notice,),
        candidates=(
            CandidateFilingRecord(
                filing_key="private-filing",
                contest_public_id="nc/2026-11-03/general/us-senator",
                ballot_name="Private Candidate",
                source_records=(
                    PersonSourceEvidence(
                        source_row_key="private-row",
                        reported_name="Private Candidate",
                        protected_email=protected_value,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ContractValidationError) as exc_info:
        validate_pre_election_batch(batch)

    assert protected_value not in str(exc_info.value)


def test_batch_rejects_duplicate_ingestion_notice():
    notice = IngestionNotice(
        code="measure_excluded",
        subject_type="source_contest",
        subject_public_id="nc/source-contest/abc123",
    )

    with pytest.raises(ContractValidationError, match="duplicate ingestion notice"):
        validate_pre_election_batch(valid_batch(notices=(notice, notice)))


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        (
            "jurisdictions",
            (
                JurisdictionRecord("duplicate", "One", "county", "NC"),
                JurisdictionRecord("duplicate", "Two", "county", "NC"),
            ),
            "duplicate jurisdiction public_id",
        ),
        (
            "offices",
            (OfficeRecord("office", "missing-jurisdiction", "Mayor", "executive"),),
            "unknown jurisdiction",
        ),
        (
            "contests",
            (ContestRecord("contest", "missing-election", "nc/us-senator"),),
            "unknown election",
        ),
    ],
)
def test_batch_rejects_duplicate_or_missing_relationship_keys(field, replacement, message):
    with pytest.raises(ContractValidationError, match=message):
        validate_pre_election_batch(valid_batch(**{field: replacement}))


def test_batch_rejects_duplicate_source_row_lineage():
    evidence = PersonSourceEvidence(
        source_row_key="same-row",
        reported_name="First Person",
        ballot_name="First Person",
    )
    candidates = (
        CandidateFilingRecord("first", "nc/2026-11-03/general/us-senator", "First Person", source_records=(evidence,)),
        CandidateFilingRecord("second", "nc/2026-11-03/general/us-senator", "Second Person", source_records=(evidence,)),
    )

    with pytest.raises(ContractValidationError, match="duplicate source row key"):
        validate_pre_election_batch(valid_batch(candidates=candidates))


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        (
            "offices",
            (
                OfficeRecord(
                    "nc/us-senator",
                    "ocd-division/country:us/state:nc",
                    "United States Senator",
                    "legislator",
                    positions=0,
                ),
            ),
            "positions must be positive",
        ),
        (
            "contests",
            (
                ContestRecord(
                    "nc/2026-11-03/general/us-senator",
                    "nc/2026-11-03/general",
                    "nc/us-senator",
                    vote_for=0,
                ),
            ),
            "vote_for must be positive",
        ),
    ],
)
def test_batch_rejects_invalid_numeric_values(field, replacement, message):
    with pytest.raises(ContractValidationError, match=message):
        validate_pre_election_batch(valid_batch(**{field: replacement}))


def test_validation_error_never_echoes_protected_values():
    protected_values = ("987 Never Publish Avenue", "919-555-0199", "never-publish@example.test")
    candidate = CandidateFilingRecord(
        filing_key="private-invalid",
        contest_public_id="missing-contest",
        ballot_name="Private Candidate",
        source_records=(
            PersonSourceEvidence(
                source_row_key="private-row",
                reported_name="Private Candidate",
                ballot_name="Private Candidate",
                protected_address=protected_values[0],
                protected_phone=protected_values[1],
                protected_email=protected_values[2],
            ),
        ),
    )

    with pytest.raises(ContractValidationError) as exc_info:
        validate_pre_election_batch(valid_batch(candidates=(candidate,)))

    message = str(exc_info.value)
    assert all(value not in message for value in protected_values)
