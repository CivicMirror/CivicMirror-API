import os

from results.adapters.il_aggregate import aggregate_csv_rows

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_aggregate_csv_rows_sums_votes_across_precincts_by_candidate():
    csv_text = _load_fixture("il_us_senator_sample.csv")
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")

    by_candidate = {r.candidate_name: r.vote_count for r in rows if r.candidate_name}
    # STEVE BOTSFORD JR. appears in both fixture precincts (CLAYTON PCT 1, CAMP POINT PCT 2).
    assert "STEVE BOTSFORD JR." in by_candidate
    assert by_candidate["STEVE BOTSFORD JR."] >= 0

    for row in rows:
        assert row.office_title == "UNITED STATES SENATOR"
        assert row.result_type == "official"


def test_aggregate_csv_rows_excludes_under_over_votes_and_blank_ballots():
    csv_text = _load_fixture("il_us_senator_sample.csv")
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")

    names = {r.candidate_name for r in rows if r.candidate_name}
    assert "Under Votes" not in names
    assert "Over Votes" not in names
    assert "Blank Ballots" not in names


def test_aggregate_csv_rows_normalizes_write_in_capitalization_variants():
    csv_text = (
        "JurisdictionID,JurisContainerID,JurisName,EISCandidateID,CandidateName,"
        "EISContestID,ContestName,PrecinctName,Registration,EISPartyID,PartyName,VoteCount\n"
        "1,0,ADAMS,0,WRITE-IN,150,UNITED STATES SENATOR,PCT 1,500,11,DEMOCRATIC,2\n"
        "1,0,ADAMS,0,Write-in,150,UNITED STATES SENATOR,PCT 2,500,11,DEMOCRATIC,3\n"
    )
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")

    write_in_rows = [r for r in rows if r.is_write_in_aggregate]
    assert len(write_in_rows) == 1
    assert write_in_rows[0].vote_count == 5


def test_aggregate_csv_rows_handles_empty_csv():
    header_only = (
        "JurisdictionID,JurisContainerID,JurisName,EISCandidateID,CandidateName,"
        "EISContestID,ContestName,PrecinctName,Registration,EISPartyID,PartyName,VoteCount\n"
    )
    assert aggregate_csv_rows(header_only, "UNITED STATES SENATOR") == []


def test_aggregate_csv_rows_strips_control_bytes_from_candidate_name():
    csv_text = (
        "JurisdictionID,JurisContainerID,JurisName,EISCandidateID,CandidateName,"
        "EISContestID,ContestName,PrecinctName,Registration,EISPartyID,PartyName,VoteCount\n"
        "1,0,ADAMS,1,JANE\x00 DOE,150,UNITED STATES SENATOR,PCT 1,500,11,DEMOCRATIC,10\n"
    )
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")
    assert rows[0].candidate_name == "JANE DOE"


def test_aggregate_csv_rows_emits_zero_vote_write_in_aggregate():
    """Write-in ResultRow should be emitted even when total write-in votes = 0."""
    csv_text = (
        "JurisdictionID,JurisContainerID,JurisName,EISCandidateID,CandidateName,"
        "EISContestID,ContestName,PrecinctName,Registration,EISPartyID,PartyName,VoteCount\n"
        "1,0,ADAMS,0,WRITE-IN,150,UNITED STATES SENATOR,PCT 1,500,11,DEMOCRATIC,0\n"
        "1,0,ADAMS,0,Write-in,150,UNITED STATES SENATOR,PCT 2,500,11,DEMOCRATIC,0\n"
    )
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")

    write_in_rows = [r for r in rows if r.is_write_in_aggregate]
    assert len(write_in_rows) == 1
    assert write_in_rows[0].candidate_name == "Write-In"
    assert write_in_rows[0].vote_count == 0
    assert write_in_rows[0].is_write_in_aggregate is True
