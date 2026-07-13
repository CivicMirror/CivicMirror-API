import os

from integrations.mn_sos.parsers import parse_file_index

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_file_index_extracts_label_url_pairs():
    html = _load_fixture("file_index.html")
    files = parse_file_index(html)

    labels = {f["label"] for f in files}
    assert "U.S. Senator Statewide" in labels
    assert "U.S. Representative by District" in labels
    assert "County Races" in labels  # out-of-scope label must still be parsed here;
    # scope filtering is mappers.is_in_scope_file's job, not the parser's.

    by_label = {f["label"]: f["url"] for f in files}
    assert by_label["U.S. Senator Statewide"] == (
        "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt"
    )


def test_parse_file_index_returns_empty_list_for_no_matches():
    assert parse_file_index("<html><body>no links here</body></html>") == []
