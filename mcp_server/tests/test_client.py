import unittest

import requests

from civicmirror_mcp.client import UNREPORTED_SOURCE_KEY, CivicMirrorAPIClient, CivicMirrorAPIError


class FakeResponse:
    def __init__(self, payload, status_code=200, raise_value_error=False):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self._raise_value_error = raise_value_error

    def json(self):
        if self._raise_value_error:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    """A session exposing only ``get`` -- any write attempt raises AttributeError."""

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


def make_client(session, **kwargs):
    kwargs.setdefault("base_url", "https://api.example.test/api/v1")
    kwargs.setdefault("api_key", "secret")
    return CivicMirrorAPIClient(session=session, **kwargs)


class RequestTests(unittest.TestCase):
    def test_request_sends_api_key_and_normalizes_base_url(self):
        session = FakeSession([FakeResponse({"ok": True})])
        client = make_client(session, base_url="https://api.example.test/api/v1/", timeout=9)

        result = client.request("/elections/", {"state": "WA"})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(session.calls[0]["url"], "https://api.example.test/api/v1/elections/")
        self.assertEqual(session.calls[0]["headers"]["X-Api-Key"], "secret")
        self.assertEqual(session.calls[0]["params"], {"state": "WA"})
        self.assertEqual(session.calls[0]["timeout"], 9)

    def test_request_omits_api_key_header_when_no_key_configured(self):
        session = FakeSession([FakeResponse({"ok": True})])
        client = make_client(session, api_key=None)

        # Explicitly unset so a developer's real environment cannot leak into the test.
        client.api_key = None
        client.request("/races/")

        self.assertNotIn("X-Api-Key", session.calls[0]["headers"])

    def test_http_error_is_wrapped_as_api_error(self):
        session = FakeSession([FakeResponse({"detail": "forbidden"}, status_code=403)])
        client = make_client(session)

        with self.assertRaises(CivicMirrorAPIError) as ctx:
            client.request("/races/")
        self.assertIn("request failed", str(ctx.exception))

    def test_non_json_response_is_wrapped_as_api_error(self):
        session = FakeSession([FakeResponse("<html>", raise_value_error=True)])
        client = make_client(session)

        with self.assertRaises(CivicMirrorAPIError) as ctx:
            client.request("/races/")
        self.assertIn("non-JSON", str(ctx.exception))


class PaginationTests(unittest.TestCase):
    def test_list_paginated_follows_drf_next_links(self):
        session = FakeSession([
            FakeResponse({"results": [{"id": 1}], "next": "https://api.example.test/api/v1/races/?page=2"}),
            FakeResponse({"results": [{"id": 2}], "next": None}),
        ])
        client = make_client(session)

        result = client.list_paginated("/races/", {"state": "CA", "page_size": 1})

        self.assertEqual(result, [{"id": 1}, {"id": 2}])
        self.assertEqual(session.calls[0]["params"], {"state": "CA", "page_size": 1})
        self.assertEqual(session.calls[1]["url"], "https://api.example.test/api/v1/races/?page=2")
        self.assertEqual(session.calls[1]["params"], {})

    def test_list_paginated_stops_at_max_pages(self):
        session = FakeSession([
            FakeResponse({"results": [{"id": 1}], "next": "https://api.example.test/api/v1/races/?page=2"}),
            FakeResponse({"results": [{"id": 2}], "next": "https://api.example.test/api/v1/races/?page=3"}),
        ])
        client = make_client(session)

        with self.assertRaises(CivicMirrorAPIError) as ctx:
            client.list_paginated("/races/", max_pages=2)
        self.assertIn("max_pages=2", str(ctx.exception))

    def test_list_paginated_rejects_unexpected_shape(self):
        session = FakeSession([FakeResponse({"detail": "nope"})])
        client = make_client(session)

        with self.assertRaises(CivicMirrorAPIError):
            client.list_paginated("/races/")


def race_list_payload(races):
    return FakeResponse({"results": races, "next": None})


class GetResultsTests(unittest.TestCase):
    def test_filters_by_ocd_id_date_and_contest_then_fetches_details(self):
        session = FakeSession([
            race_list_payload([
                {"id": 11, "office_title": "U.S. Senate", "ocd_division_id": "ocd-division/country:us/state:wa"},
                {"id": 12, "office_title": "Governor", "ocd_division_id": "ocd-division/country:us/state:wa"},
            ]),
            FakeResponse({
                "id": 11,
                "office_title": "U.S. Senate",
                "candidates": [{"id": 5, "name": "Jane Example"}],
                "source": "wa_votewa",
                "last_synced_at": "2026-08-05T01:00:00Z",
                "certification_status": "unofficial",
                "race_status": "partial",
                "sources": ["wa_votewa"],
            }),
            FakeResponse([
                {
                    "id": 1,
                    "candidate": 5,
                    "candidate_name": "Jane Example",
                    "vote_count": 1200,
                    "vote_pct": "54.2",
                    "result_type": "unofficial",
                    "is_winner": None,
                    "jurisdiction_fragment": "",
                    "source_url": "https://results.example.test/senate",
                },
            ]),
        ])
        client = make_client(session)

        result = client.get_results(
            ocd_id="ocd-division/country:us/state:wa",
            election_date="2026-08-04",
            contest="senate",
        )

        self.assertEqual(result.ocd_id, "ocd-division/country:us/state:wa")
        self.assertEqual(result.election_date, "2026-08-04")
        self.assertEqual(result.race_count, 1)
        self.assertEqual([entry.race.id for entry in result.races], [11])
        self.assertEqual(session.calls[0]["params"]["state"], "WA")
        self.assertEqual(session.calls[0]["params"]["election_date__gte"], "2026-08-04")
        self.assertEqual(session.calls[0]["params"]["election_date__lte"], "2026-08-04")

    def test_retains_status_authority_freshness_and_partial_reporting_metadata(self):
        session = FakeSession([
            race_list_payload([
                {"id": 11, "office_title": "Mayor", "ocd_division_id": "ocd-division/country:us/state:wa/place:seattle"},
            ]),
            FakeResponse({
                "id": 11,
                "office_title": "Mayor",
                "race_status": "partial",
                "certification_status": "unofficial",
                "source": "king_county",
                "sources": ["king_county", "wa_votewa"],
                "last_synced_at": "2026-08-05T01:00:00Z",
                "field_provenance": {"office_title": "king_county"},
            }),
            FakeResponse([
                {
                    "id": 7,
                    "candidate_name": "A",
                    "vote_count": 10,
                    "result_type": "unofficial",
                    "is_winner": False,
                    "jurisdiction_fragment": "Precinct 1",
                    "certified_at": None,
                    "source_url": "https://kingcounty.example.test/results",
                },
            ]),
        ])
        client = make_client(session)

        result = client.get_results(
            ocd_id="ocd-division/country:us/state:wa/place:seattle",
            election_date="2026-08-04",
        )
        entry = result.races[0]

        self.assertEqual(entry.race.race_status, "partial")
        self.assertEqual(entry.race.certification_status, "unofficial")
        self.assertEqual(entry.race.source, "king_county")
        self.assertEqual(entry.race.sources, ["king_county", "wa_votewa"])
        self.assertEqual(entry.race.last_synced_at, "2026-08-05T01:00:00Z")
        self.assertEqual(entry.race.field_provenance, {"office_title": "king_county"})
        self.assertEqual(entry.results[0].result_type, "unofficial")
        self.assertIs(entry.results[0].is_winner, False)
        self.assertEqual(entry.results[0].source_url, "https://kingcounty.example.test/results")
        # Partial-reporting signal: a sub-jurisdiction row with no contest total.
        self.assertEqual(entry.sub_jurisdiction_rows, 1)
        self.assertEqual(entry.contest_total_rows, 0)
        self.assertTrue(any("no contest-total row" in note for note in result.notes))

    def test_unreported_metadata_stays_null_and_is_called_out_in_notes(self):
        session = FakeSession([
            race_list_payload([
                {"id": 11, "office_title": "Mayor", "ocd_division_id": "ocd-division/country:us/state:wa/place:seattle"},
            ]),
            FakeResponse({"id": 11, "office_title": "Mayor"}),
            FakeResponse([]),
        ])
        client = make_client(session)

        entry = client.get_results(
            ocd_id="ocd-division/country:us/state:wa/place:seattle",
            election_date="2026-08-04",
        )
        race = entry.races[0].race

        self.assertIsNone(race.source)
        self.assertIsNone(race.sources)
        self.assertIsNone(race.last_synced_at)
        self.assertIsNone(race.certification_status)
        self.assertIsNone(race.race_status)
        self.assertTrue(any("no source" in note for note in entry.notes))
        self.assertTrue(any("last_synced_at" in note for note in entry.notes))
        self.assertTrue(any("no official result rows" in note for note in entry.notes))

    def test_empty_match_is_reported_as_absence_of_record(self):
        session = FakeSession([race_list_payload([])])
        client = make_client(session)

        result = client.get_results(ocd_id="ocd-division/country:us/state:wa", election_date="2026-08-04")

        self.assertEqual(result.race_count, 0)
        self.assertTrue(any("holds no such record" in note for note in result.notes))

    def test_missing_state_in_ocd_id_raises_api_error(self):
        client = make_client(FakeSession([]))

        with self.assertRaises(CivicMirrorAPIError):
            client.get_results("ocd-division/country:us", "2026-08-04")

    def test_race_without_id_raises_api_error(self):
        session = FakeSession([race_list_payload([
            {"office_title": "Mayor", "ocd_division_id": "ocd-division/country:us/state:wa"},
        ])])
        client = make_client(session)

        with self.assertRaises(CivicMirrorAPIError) as ctx:
            client.get_results("ocd-division/country:us/state:wa", "2026-08-04")
        self.assertIn("missing id", str(ctx.exception))

    def test_non_list_results_payload_raises_api_error(self):
        session = FakeSession([
            race_list_payload([{"id": 11, "ocd_division_id": "ocd-division/country:us/state:wa"}]),
            FakeResponse({"id": 11}),
            FakeResponse({"detail": "not a list"}),
        ])
        client = make_client(session)

        with self.assertRaises(CivicMirrorAPIError):
            client.get_results("ocd-division/country:us/state:wa", "2026-08-04")


class ListAdaptersTests(unittest.TestCase):
    def test_filters_sync_status_by_state(self):
        session = FakeSession([
            FakeResponse({
                "adapter_states": ["CA", "WA"],
                "by_state": {"WA": {"wa_votewa": {"status": "completed"}}},
                "coverage_tiers": {"WA": "full", "CA": "full"},
                "as_of": "2026-07-22T12:00:00Z",
            }),
        ])
        client = make_client(session)

        result = client.list_adapters(state="wa")

        self.assertEqual(result.adapter_states, ["WA"])
        self.assertEqual(result.by_state, {"WA": {"wa_votewa": {"status": "completed"}}})
        self.assertEqual(result.coverage_tiers, {"WA": "full"})
        self.assertEqual(result.state, "WA")
        self.assertEqual(result.as_of, "2026-07-22T12:00:00Z")
        self.assertEqual(result.notes, [])

    def test_unregistered_state_and_missing_as_of_are_explicit(self):
        session = FakeSession([
            FakeResponse({"adapter_states": ["CA"], "by_state": {}, "coverage_tiers": {}}),
        ])
        client = make_client(session)

        result = client.list_adapters(state="wy")

        self.assertEqual(result.adapter_states, [])
        self.assertIsNone(result.as_of)
        self.assertTrue(any("No results adapter is registered for WY" in note for note in result.notes))
        self.assertTrue(any("as_of" in note for note in result.notes))

    def test_unexpected_payload_shape_raises_api_error(self):
        client = make_client(FakeSession([FakeResponse([1, 2, 3])]))

        with self.assertRaises(CivicMirrorAPIError):
            client.list_adapters()


class CompareSourcesTests(unittest.TestCase):
    def two_source_session(self):
        return FakeSession([
            race_list_payload([
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
            ]),
            FakeResponse({"id": 21, "office_title": "County Commissioner", "source": "clarity",
                          "certification_status": "unofficial", "last_synced_at": "2026-11-04T02:00:00Z"}),
            FakeResponse([{"id": 1, "candidate_name": "A", "vote_count": 100, "vote_pct": 50,
                           "result_type": "unofficial", "jurisdiction_fragment": ""}]),
            FakeResponse({"id": 22, "office_title": "County Commissioner", "source": "certified_pdf",
                          "certification_status": "certified", "last_synced_at": "2026-12-01T02:00:00Z"}),
            FakeResponse([{"id": 2, "candidate_name": "A", "vote_count": 104, "vote_pct": 52,
                           "result_type": "certified", "certified_at": "2026-11-30T00:00:00Z",
                           "jurisdiction_fragment": ""}]),
        ])

    def test_returns_vote_deltas_and_flags_conflicts(self):
        client = make_client(self.two_source_session())

        result = client.compare_sources(
            ocd_id="ocd-division/country:us/state:co/county:mesa",
            contest="commissioner",
        )

        self.assertEqual(result.source_count, 2)
        self.assertEqual(sorted(result.sources), ["certified_pdf", "clarity"])
        row = result.comparisons[0]
        # Baseline is the alphabetically first source, not API order.
        self.assertEqual(row.baseline_source, "certified_pdf")
        self.assertEqual(row.comparison_source, "clarity")
        self.assertEqual(row.label, "A")
        self.assertEqual(row.baseline_vote_count, 104)
        self.assertEqual(row.comparison_vote_count, 100)
        self.assertEqual(row.vote_count_delta, -4)
        self.assertEqual(row.vote_pct_delta, -2.0)
        self.assertEqual(row.baseline_result_type, "certified")
        self.assertEqual(row.comparison_result_type, "unofficial")
        self.assertEqual(row.baseline_certified_at, "2026-11-30T00:00:00Z")
        self.assertTrue(row.conflict)
        self.assertEqual(result.conflict_count, 1)

    def test_baseline_is_stable_when_api_order_reverses(self):
        session = self.two_source_session()
        # Reverse the race-list order; the baseline must not move.
        first = session.responses[0]
        first._payload["results"].reverse()
        session.responses[1], session.responses[3] = session.responses[3], session.responses[1]
        session.responses[2], session.responses[4] = session.responses[4], session.responses[2]
        client = make_client(session)

        result = client.compare_sources(
            ocd_id="ocd-division/country:us/state:co/county:mesa",
            contest="commissioner",
        )

        self.assertEqual(result.comparisons[0].baseline_source, "certified_pdf")
        self.assertEqual(result.comparisons[0].vote_count_delta, -4)

    def test_row_missing_from_one_source_is_marked_absent_not_zero(self):
        session = FakeSession([
            race_list_payload([
                {"id": 21, "ocd_division_id": "ocd-division/country:us/state:co/county:mesa", "source": "aaa"},
                {"id": 22, "ocd_division_id": "ocd-division/country:us/state:co/county:mesa", "source": "bbb"},
            ]),
            FakeResponse({"id": 21, "source": "aaa"}),
            FakeResponse([{"id": 1, "candidate_name": "A", "vote_count": 100}]),
            FakeResponse({"id": 22, "source": "bbb"}),
            FakeResponse([{"id": 2, "candidate_name": "B", "vote_count": 7}]),
        ])
        client = make_client(session)

        result = client.compare_sources(ocd_id="ocd-division/country:us/state:co/county:mesa", contest="")
        by_label = {row.label: row for row in result.comparisons}

        self.assertTrue(by_label["A"].baseline_present)
        self.assertFalse(by_label["A"].comparison_present)
        self.assertIsNone(by_label["A"].comparison_vote_count)
        self.assertIsNone(by_label["A"].vote_count_delta)
        self.assertFalse(by_label["A"].conflict)

    def test_unnamed_rows_are_excluded_rather_than_given_invented_labels(self):
        session = FakeSession([
            race_list_payload([
                {"id": 21, "ocd_division_id": "ocd-division/country:us/state:co/county:mesa", "source": "aaa"},
                {"id": 22, "ocd_division_id": "ocd-division/country:us/state:co/county:mesa", "source": "bbb"},
            ]),
            FakeResponse({"id": 21, "source": "aaa"}),
            FakeResponse([{"id": 1, "vote_count": 100}]),
            FakeResponse({"id": 22, "source": "bbb"}),
            FakeResponse([{"id": 2, "vote_count": 100}]),
        ])
        client = make_client(session)

        result = client.compare_sources(ocd_id="ocd-division/country:us/state:co/county:mesa", contest="")

        self.assertEqual(result.comparisons, [])
        self.assertIsNone(result.sources["aaa"].results[0].label)
        self.assertTrue(any("excluded from comparisons" in note for note in result.notes))

    def test_single_source_reports_why_no_comparison_was_made(self):
        session = FakeSession([
            race_list_payload([
                {"id": 21, "ocd_division_id": "ocd-division/country:us/state:co/county:mesa", "source": "clarity"},
            ]),
            FakeResponse({"id": 21, "source": "clarity"}),
            FakeResponse([{"id": 1, "candidate_name": "A", "vote_count": 100}]),
        ])
        client = make_client(session)

        result = client.compare_sources(ocd_id="ocd-division/country:us/state:co/county:mesa", contest="")

        self.assertEqual(result.source_count, 1)
        self.assertEqual(result.comparisons, [])
        self.assertTrue(any("needs at least two" in note for note in result.notes))

    def test_two_races_from_one_source_are_refused_rather_than_silently_dropped(self):
        session = FakeSession([
            race_list_payload([
                {"id": 31, "office_title": "County Commissioner District 1",
                 "ocd_division_id": "ocd-division/country:us/state:co/county:mesa", "source": "co_sos"},
                {"id": 32, "office_title": "County Commissioner District 3",
                 "ocd_division_id": "ocd-division/country:us/state:co/county:mesa", "source": "co_sos"},
            ]),
            FakeResponse({"id": 31, "office_title": "County Commissioner District 1", "source": "co_sos"}),
            FakeResponse([{"id": 1, "candidate_name": "A", "vote_count": 100}]),
            FakeResponse({"id": 32, "office_title": "County Commissioner District 3", "source": "co_sos"}),
            FakeResponse([{"id": 2, "candidate_name": "Z", "vote_count": 200}]),
        ])
        client = make_client(session)

        with self.assertRaises(CivicMirrorAPIError) as ctx:
            client.compare_sources(
                ocd_id="ocd-division/country:us/state:co/county:mesa",
                contest="commissioner",
            )
        message = str(ctx.exception)
        self.assertIn("District 1", message)
        self.assertIn("District 3", message)
        self.assertIn("co_sos", message)

    def test_record_without_reported_source_is_keyed_explicitly(self):
        session = FakeSession([
            race_list_payload([
                {"id": 21, "ocd_division_id": "ocd-division/country:us/state:co/county:mesa"},
            ]),
            FakeResponse({"id": 21}),
            FakeResponse([{"id": 1, "candidate_name": "A", "vote_count": 100}]),
        ])
        client = make_client(session)

        result = client.compare_sources(ocd_id="ocd-division/country:us/state:co/county:mesa", contest="")

        self.assertIn(UNREPORTED_SOURCE_KEY, result.sources)
        self.assertEqual(result.unreported_source_count, 1)
        self.assertTrue(any("no source reported" in note for note in result.notes))


if __name__ == "__main__":
    unittest.main()
