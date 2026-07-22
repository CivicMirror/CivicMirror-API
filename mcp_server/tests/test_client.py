import unittest

import requests

from civicmirror_mcp.client import CivicMirrorAPIClient, CivicMirrorAPIError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({
            "url": url,
            "headers": headers or {},
            "params": params or {},
            "timeout": timeout,
        })
        if not self.responses:
            raise AssertionError(f"unexpected GET {url}")
        return self.responses.pop(0)


class CivicMirrorAPIClientTests(unittest.TestCase):
    def test_request_sends_api_key_and_normalizes_base_url(self):
        session = FakeSession([FakeResponse({"ok": True})])
        client = CivicMirrorAPIClient(
            base_url="https://api.example.test/api/v1/",
            api_key="secret",
            session=session,
            timeout=9,
        )

        result = client.request("/elections/", {"state": "WA"})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(session.calls[0]["url"], "https://api.example.test/api/v1/elections/")
        self.assertEqual(session.calls[0]["headers"]["X-Api-Key"], "secret")
        self.assertEqual(session.calls[0]["params"], {"state": "WA"})
        self.assertEqual(session.calls[0]["timeout"], 9)

    def test_list_paginated_follows_drf_next_links(self):
        session = FakeSession([
            FakeResponse({"results": [{"id": 1}], "next": "https://api.example.test/api/v1/races/?page=2"}),
            FakeResponse({"results": [{"id": 2}], "next": None}),
        ])
        client = CivicMirrorAPIClient(base_url="https://api.example.test/api/v1", api_key="secret", session=session)

        result = client.list_paginated("/races/", {"state": "CA", "page_size": 1})

        self.assertEqual(result, [{"id": 1}, {"id": 2}])
        self.assertEqual(session.calls[0]["params"], {"state": "CA", "page_size": 1})
        self.assertEqual(session.calls[1]["url"], "https://api.example.test/api/v1/races/?page=2")
        self.assertEqual(session.calls[1]["params"], {})

    def test_get_results_filters_by_ocd_id_date_and_contest_then_fetches_details(self):
        session = FakeSession([
            FakeResponse({
                "results": [
                    {
                        "id": 11,
                        "office_title": "U.S. Senate",
                        "ocd_division_id": "ocd-division/country:us/state:wa",
                    },
                    {
                        "id": 12,
                        "office_title": "Governor",
                        "ocd_division_id": "ocd-division/country:us/state:wa",
                    },
                ],
                "next": None,
            }),
            FakeResponse({
                "id": 11,
                "office_title": "U.S. Senate",
                "candidates": [{"id": 5, "name": "Jane Example"}],
            }),
            FakeResponse([
                {"candidate": 5, "vote_count": 1200, "vote_pct": "54.2", "result_type": "official"},
            ]),
        ])
        client = CivicMirrorAPIClient(base_url="https://api.example.test/api/v1", api_key="secret", session=session)

        result = client.get_results(
            ocd_id="ocd-division/country:us/state:wa",
            election_date="2026-08-04",
            contest="senate",
        )

        self.assertEqual(result["ocd_id"], "ocd-division/country:us/state:wa")
        self.assertEqual(result["election_date"], "2026-08-04")
        self.assertEqual([race["race"]["id"] for race in result["races"]], [11])
        self.assertEqual(result["races"][0]["results"][0]["vote_count"], 1200)
        self.assertEqual(session.calls[0]["params"]["state"], "WA")
        self.assertEqual(session.calls[0]["params"]["election_date__gte"], "2026-08-04")
        self.assertEqual(session.calls[0]["params"]["election_date__lte"], "2026-08-04")

    def test_list_adapters_filters_sync_status_by_state(self):
        session = FakeSession([
            FakeResponse({
                "adapter_states": ["CA", "WA"],
                "by_state": {"WA": {"wa_votewa": {"status": "completed"}}},
                "coverage_tiers": {"WA": "full", "CA": "full"},
                "as_of": "2026-07-22T12:00:00Z",
            }),
        ])
        client = CivicMirrorAPIClient(base_url="https://api.example.test/api/v1", api_key="secret", session=session)

        result = client.list_adapters(state="wa")

        self.assertEqual(result["adapter_states"], ["WA"])
        self.assertEqual(result["by_state"], {"WA": {"wa_votewa": {"status": "completed"}}})
        self.assertEqual(result["coverage_tiers"], {"WA": "full"})

    def test_compare_sources_returns_vote_deltas_for_matching_contest_sources(self):
        session = FakeSession([
            FakeResponse({
                "results": [
                    {
                        "id": 21,
                        "office_title": "County Commissioner",
                        "ocd_division_id": "ocd-division/country:us/state:co/county:mesa",
                        "source": "clarity",
                    },
                    {
                        "id": 22,
                        "office_title": "County Commissioner",
                        "ocd_division_id": "ocd-division/country:us/state:co/county:mesa",
                        "source": "certified_pdf",
                    },
                ],
                "next": None,
            }),
            FakeResponse({"id": 21, "office_title": "County Commissioner", "candidates": [{"id": 1, "name": "A"}]}),
            FakeResponse([{"candidate": 1, "vote_count": 100, "vote_pct": 50}]),
            FakeResponse({"id": 22, "office_title": "County Commissioner", "candidates": [{"id": 1, "name": "A"}]}),
            FakeResponse([{"candidate": 1, "vote_count": 104, "vote_pct": 52}]),
        ])
        client = CivicMirrorAPIClient(base_url="https://api.example.test/api/v1", api_key="secret", session=session)

        result = client.compare_sources(
            ocd_id="ocd-division/country:us/state:co/county:mesa",
            contest="commissioner",
        )

        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["comparisons"][0]["candidate_or_option"], "A")
        self.assertEqual(result["comparisons"][0]["vote_count_delta"], 4)
        self.assertEqual(result["comparisons"][0]["vote_pct_delta"], 2.0)

    def test_missing_state_in_ocd_id_raises_api_error(self):
        client = CivicMirrorAPIClient(base_url="https://api.example.test/api/v1", api_key="secret", session=FakeSession([]))

        with self.assertRaises(CivicMirrorAPIError):
            client.get_results("ocd-division/country:us", "2026-08-04")


if __name__ == "__main__":
    unittest.main()
