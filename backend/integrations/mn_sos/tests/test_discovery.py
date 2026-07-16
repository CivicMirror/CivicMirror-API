from unittest.mock import MagicMock

import pytest

from integrations.mn_sos.discovery import discover_in_scope_files
from integrations.mn_sos.exceptions import MnSosRetryableError
from integrations.mn_sos.manifests import KNOWN_IN_SCOPE_FILES

_REAL_INDEX_HTML = (
    '<a class="downloadlink" href="https://x/ussenate.txt">U.S. Senator Statewide</a>'
    '<a class="downloadlink" href="https://x/cntyRaces.txt">County Races</a>'
)


def _client_returning(html):
    client = MagicMock()
    client.fetch_file_index.return_value = html
    return client


def _client_raising(exc):
    client = MagicMock()
    client.fetch_file_index.side_effect = exc
    return client


def test_discover_uses_live_index_and_keeps_only_in_scope():
    client = _client_returning(_REAL_INDEX_HTML)

    files = discover_in_scope_files(client, 170)

    labels = [f["label"] for f in files]
    assert labels == ["U.S. Senator Statewide"]  # County Races dropped
    client.fetch_file_index.assert_called_once_with(170)


def test_discover_falls_back_to_manifest_when_index_blocked_for_known_election():
    client = _client_raising(MnSosRetryableError("captcha"))

    files = discover_in_scope_files(client, 170)

    assert files == KNOWN_IN_SCOPE_FILES[170]
    # Returned entries are copies, not the shared manifest objects.
    assert files is not KNOWN_IN_SCOPE_FILES[170]
    assert all(f["url"].endswith(".txt") for f in files)


def test_discover_raises_when_index_blocked_and_no_manifest():
    client = _client_raising(MnSosRetryableError("captcha"))

    with pytest.raises(MnSosRetryableError):
        discover_in_scope_files(client, 999999)  # unknown election, no manifest


def test_discover_returns_empty_for_genuinely_empty_live_index():
    # A real index that loads cleanly but lists no in-scope files must return
    # empty — not silently fall back to a manifest.
    client = _client_returning(
        '<a class="downloadlink" href="https://x/cntyRaces.txt">County Races</a>'
    )

    files = discover_in_scope_files(client, 170)

    assert files == []
