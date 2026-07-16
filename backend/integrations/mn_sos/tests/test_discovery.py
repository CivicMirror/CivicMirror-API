from unittest.mock import MagicMock, patch

import pytest

from integrations.mn_sos.client import MnSosClient
from integrations.mn_sos.discovery import probe_in_scope_files
from integrations.mn_sos.exceptions import MnSosRetryableError

_SCOPE = ["USPres.txt", "ussenate.txt", "judicial.txt"]


def _client(exists_map):
    """A client whose file_exists follows exists_map; file_url stays real."""
    client = MagicMock(spec=MnSosClient)
    client.file_url.side_effect = MnSosClient.file_url
    client.file_exists.side_effect = lambda dp, name: exists_map[name]
    return client


def test_probe_returns_only_existing_in_scope_files():
    client = _client({"USPres.txt": True, "ussenate.txt": True, "judicial.txt": False})
    with patch("integrations.mn_sos.discovery.filenames.in_scope_filenames", return_value=_SCOPE):
        files = probe_in_scope_files(client, "20241105")

    urls = [f["url"] for f in files]
    assert urls == [
        "https://electionresultsfiles.sos.mn.gov/20241105/USPres.txt",
        "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt",
    ]


def test_probe_returns_empty_when_no_in_scope_files_exist():
    # e.g. an odd-year local election with no Federal/State offices.
    client = _client(dict.fromkeys(_SCOPE, False))
    with patch("integrations.mn_sos.discovery.filenames.in_scope_filenames", return_value=_SCOPE):
        assert probe_in_scope_files(client, "20251104") == []


def test_probe_propagates_retryable_error_from_transient_host_failure():
    client = MagicMock(spec=MnSosClient)
    client.file_exists.side_effect = MnSosRetryableError("host 503")
    with patch("integrations.mn_sos.discovery.filenames.in_scope_filenames", return_value=_SCOPE):
        with pytest.raises(MnSosRetryableError):
            probe_in_scope_files(client, "20241105")
