import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import get_life_ranking as glr


TEAM_LIST = [
    {"team_id": 1, "team_name": "Eisbaeren Berlin", "short_name": "EBB", "del_team": True},
    {"team_id": 2, "team_name": "Adler Mannheim", "short_name": "MAN", "del_team": True},
    {"team_id": 3, "team_name": "Koelner Haie", "short_name": "KEC", "del_team": True},
]


def _team_node(name, rank, **overrides):
    row = {
        "rnk": rank,
        "Tnm": name,
        "ptsn": "3",
        "pts": 3,
        "gf": 4,
        "ga": 2,
        "win": 1,
        "pld": 1,
    }
    row.update(overrides)
    return row


SAMPLE_PAYLOAD = {
    "Stages": [
        {
            "LeagueTable": {
                "L": [
                    {
                        "Tables": [
                            {
                                "LTT": 1,
                                "team": [
                                    _team_node("Eisbaeren Berlin", 1),
                                    _team_node(
                                        "Adler Mannheim",
                                        2,
                                        ptsn="0",
                                        pts=0,
                                        gf=0,
                                        ga=0,
                                        win=0,
                                        pld=0,
                                    ),
                                    _team_node(
                                        "Unknown Team",
                                        3,
                                        ptsn="1",
                                        pts=1,
                                        gf=1,
                                        ga=1,
                                        win=0,
                                        pld=1,
                                    ),
                                ],
                            },
                            {
                                "LTT": 3,
                                "team": [_team_node("Koelner Haie", 1)],
                            },
                        ]
                    }
                ]
            }
        }
    ]
}


def _event(home, guest, esd, **overrides):
    event = {
        "Esd": esd,
        "Eps": "NS",
        "T1": [{"Nm": home}],
        "T2": [{"Nm": guest}],
    }
    event.update(overrides)
    return event


SAMPLE_EVENTS = [
    _event(
        "Eisbaeren Berlin",
        "Adler Mannheim",
        20260917193000,
        Eps="FT",
        Tr1="4",
        Tr2="2",
    ),
    _event("Koelner Haie", "Adler Mannheim", 20260918193000),
    _event(
        "Adler Mannheim",
        "Koelner Haie",
        20260918193000,
        Eps="P2",
        Tr1="1",
        Tr2="0",
    ),
    _event("Eisbaeren Berlin", "Unknown Team", 20260918193000, Eps="P2", Tr1="1", Tr2="0"),
    _event("Adler Mannheim", "Eisbaeren Berlin", 20260920140000),
]

MATCH_PAYLOAD = {
    "Stages": [
        {
            "LeagueTable": SAMPLE_PAYLOAD["Stages"][0]["LeagueTable"],
            "Events": SAMPLE_EVENTS,
        }
    ]
}


class FakeRankingManager(object):
    def __init__(self):
        self.calls = []

    def update_or_create(self, **kwargs):
        self.calls.append(kwargs)
        return (SimpleNamespace(pk=len(self.calls)), True)


class FakeRanking(object):
    def __init__(self):
        self.objects = FakeRankingManager()


class FakeDelmatch(object):
    def __init__(self):
        self.objects = FakeRankingManager()


def _lookup(team_list, name):
    for team in team_list:
        if team["team_name"] == name:
            return team["team_id"], team["team_name"], team["short_name"]
    return None, None, None


class GetLifeRankingTests(SimpleTestCase):
    def test_parse_args_defaults_debug_and_dry_run(self):
        defaults = glr.parse_args([])
        self.assertFalse(defaults.debug)
        self.assertFalse(defaults.dry_run)
        self.assertIsNone(defaults.season_id)
        self.assertIsNone(defaults.day)
        self.assertEqual(defaults.url, glr.DEFAULT_API_URL)
        self.assertTrue(glr.parse_args(["-d"]).debug)
        self.assertTrue(glr.parse_args(["--debug"]).debug)
        self.assertTrue(glr.parse_args(["--dry-run"]).dry_run)
        args = glr.parse_args(
            ["--season-id", "4", "--url", "http://example.test", "--day", "2026-09-17"]
        )
        self.assertEqual(args.season_id, 4)
        self.assertEqual(args.url, "http://example.test")
        self.assertEqual(args.day, "2026-09-17")

    def test_script_filename_uses_basename(self):
        self.assertEqual(
            glr.script_filename("/tmp/tools/get_life_ranking.py"),
            "get_life_ranking.py",
        )

    def test_as_int_handles_strings_and_invalid_values(self):
        self.assertEqual(glr.as_int("3"), 3)
        self.assertEqual(glr.as_int(4), 4)
        self.assertEqual(glr.as_int(None), 0)
        self.assertEqual(glr.as_int(""), 0)
        self.assertEqual(glr.as_int("x", default=9), 9)

    def test_extract_league_teams_uses_overall_table(self):
        teams = glr.extract_league_teams(SAMPLE_PAYLOAD)
        self.assertEqual(len(teams), 3)
        self.assertEqual(teams[0]["Tnm"], "Eisbaeren Berlin")
        self.assertEqual(teams[1]["Tnm"], "Adler Mannheim")
        self.assertEqual(glr.extract_league_teams({}), [])
        self.assertEqual(glr.extract_league_teams({"Stages": [{}]}), [])

    def test_extract_league_teams_supports_legacy_path(self):
        payload = {
            "Stages": [
                {
                    "League-Table": {
                        "L": [
                            {
                                "team": [_team_node("Eisbaeren Berlin", 1)],
                            }
                        ]
                    }
                }
            ]
        }
        teams = glr.extract_league_teams(payload)
        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0]["Tnm"], "Eisbaeren Berlin")

    def test_parse_team_row_maps_api_fields(self):
        parsed = glr.parse_team_row(_team_node("Eisbaeren Berlin", 1))
        self.assertEqual(parsed["ranking"], 1)
        self.assertEqual(parsed["team_name"], "Eisbaeren Berlin")
        self.assertEqual(parsed["score"], 3)
        self.assertEqual(parsed["goal"], 4)
        self.assertEqual(parsed["ggoal"], 2)
        self.assertEqual(parsed["won"], 1)
        self.assertEqual(parsed["match"], 1)

    def test_parse_team_row_accepts_user_field_aliases(self):
        parsed = glr.parse_team_row(
            {"rank": "2", "Tmn": "Adler Mannheim", "ptsn": "5", "gf": 8, "ga": 3, "win": 2, "pld": 4},
            fallback_rank=9,
        )
        self.assertEqual(parsed["ranking"], 2)
        self.assertEqual(parsed["team_name"], "Adler Mannheim")
        self.assertEqual(parsed["score"], 5)
        self.assertEqual(parsed["match"], 4)

    def test_select_ranking_match_keeps_last_and_kicks_in_next(self):
        last_match = (10, 100, 3)
        next_match = (11, 180, False)
        self.assertEqual(
            glr.select_ranking_match(110, last_match, next_match),
            (10, 100, 3),
        )
        self.assertEqual(
            glr.select_ranking_match(160, last_match, next_match),
            (11, 180, 4),
        )

    def test_build_ranking_defaults_maps_parsed_row(self):
        row = glr.parse_team_row(_team_node("Eisbaeren Berlin", 1))
        defaults = glr.build_ranking_defaults(row, 1, 7, 1000, "get_life_ranking.py")
        self.assertEqual(defaults["season_id"], 7)
        self.assertEqual(defaults["ranking"], 1)
        self.assertEqual(defaults["team_id"], 1)
        self.assertEqual(defaults["match"], 1)
        self.assertEqual(defaults["won"], 1)
        self.assertEqual(defaults["goal"], 4)
        self.assertEqual(defaults["ggoal"], 2)
        self.assertEqual(defaults["score"], 3)
        self.assertEqual(defaults["uts"], 1000)
        self.assertEqual(defaults["source"], "get_life_ranking.py")
        self.assertEqual(defaults["type"], glr.RANKING_TYPE)

    def test_persist_ranking_calls_update_or_create(self):
        fake_ranking = FakeRanking()
        row = glr.parse_team_row(_team_node("Eisbaeren Berlin", 1))
        glr.persist_ranking(
            55, row, 1, 7, 1000, "get_life_ranking.py", ranking_model=fake_ranking
        )
        self.assertEqual(len(fake_ranking.objects.calls), 1)
        call = fake_ranking.objects.calls[0]
        self.assertEqual(call["matchday_id"], 55)
        self.assertEqual(call["ranking"], 1)
        self.assertEqual(call["defaults"]["team_id"], 1)
        self.assertEqual(call["defaults"]["source"], "get_life_ranking.py")

    def test_persist_ranking_dry_run_skips_write(self):
        fake_ranking = FakeRanking()
        row = glr.parse_team_row(_team_node("Eisbaeren Berlin", 1))
        result = glr.persist_ranking(
            55,
            row,
            1,
            7,
            1000,
            "get_life_ranking.py",
            ranking_model=fake_ranking,
            dry_run=True,
        )
        self.assertEqual(result, (None, False))
        self.assertEqual(fake_ranking.objects.calls, [])

    def test_format_dry_run_table_aligns_standings(self):
        table = glr.format_dry_run_table(
            [
                {
                    "ranking": 1,
                    "team_name": "Eisbaeren Berlin",
                    "short_name": "EBB",
                    "team_id": 1,
                    "match": 1,
                    "won": 1,
                    "goal": 4,
                    "ggoal": 2,
                    "score": 3,
                },
                {
                    "ranking": 2,
                    "team_name": "Adler Mannheim",
                    "short_name": "MAN",
                    "team_id": 2,
                    "match": 0,
                    "won": 0,
                    "goal": 0,
                    "ggoal": 0,
                    "score": 0,
                },
            ],
            55,
            3,
            200,
            "get_life_ranking.py",
        )
        self.assertIn("dry-run ranking (database not updated)", table)
        self.assertIn(
            "Matchday: 55    Season: 3    UTS: 200    Source: get_life_ranking.py",
            table,
        )
        self.assertIn("Eisbaeren Berlin", table)
        self.assertIn("Adler Mannheim", table)
        self.assertIn("EBB", table)
        self.assertIn("Pts", table)
        empty = glr.format_dry_run_table([], 1, 2, 3, "src")
        self.assertIn("No ranking rows to store.", empty)

    def test_can_store_ranking(self):
        self.assertTrue(glr.can_store_ranking(1, "Eisbaeren Berlin", 9))
        self.assertFalse(glr.can_store_ranking(None, "Eisbaeren Berlin", 9))
        self.assertFalse(glr.can_store_ranking(1, "", 9))
        self.assertFalse(glr.can_store_ranking(1, "Eisbaeren Berlin", None))

    def test_format_lookup_warning(self):
        self.assertEqual(
            glr.format_lookup_warning("Unknown Team", 3),
            "warning: lookup_team failed for 'Unknown Team' (ranking 3)",
        )
        self.assertEqual(
            glr.format_lookup_warning(""),
            "warning: lookup_team failed for '<empty>'",
        )

    def test_fetch_json_uses_requests(self):
        payload = {"Stages": []}
        response = mock.Mock()
        response.json.return_value = payload
        response.status_code = 200
        get_fn = mock.Mock(return_value=response)
        result = glr.fetch_json("https://example.test/table", get_fn=get_fn)
        get_fn.assert_called_once_with(
            "https://example.test/table",
            timeout=glr.HTTP_TIMEOUT_SECONDS,
            headers=glr.HTTP_HEADERS,
        )
        response.raise_for_status.assert_called_once()
        self.assertEqual(result, payload)

    def test_run_stores_known_teams_and_skips_unknown(self):
        fake_ranking = FakeRanking()
        output = io.StringIO()
        with redirect_stdout(output):
            lines, matches = glr.run(
                argv=["--season-id", "5"],
                now_uts=200,
                teams=TEAM_LIST,
                last_match=(55, 150, 8),
                next_match=(None, None, None),
                payload=SAMPLE_PAYLOAD,
                lookup_fn=_lookup,
                ranking_model=fake_ranking,
                source="get_life_ranking.py",
            )
        self.assertEqual(
            lines,
            [
                "1: EBB - Eisbaeren Berlin P3 4:2",
                "2: MAN - Adler Mannheim P0 0:0",
            ],
        )
        self.assertEqual(matches, [])
        self.assertIn(
            "warning: lookup_team failed for 'Unknown Team' (ranking 3)",
            output.getvalue(),
        )
        self.assertEqual(len(fake_ranking.objects.calls), 2)
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["season_id"], 5)
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["team_id"], 1)
        self.assertEqual(fake_ranking.objects.calls[1]["defaults"]["team_id"], 2)
        self.assertEqual(
            fake_ranking.objects.calls[0]["defaults"]["source"], "get_life_ranking.py"
        )

    def test_run_dry_run_prints_and_skips_persist(self):
        fake_ranking = FakeRanking()
        output = io.StringIO()
        with redirect_stdout(output):
            lines, matches = glr.run(
                argv=["--dry-run", "--debug"],
                now_uts=200,
                season_id=3,
                teams=TEAM_LIST,
                last_match=(55, 150, 8),
                next_match=(None, None, None),
                payload=SAMPLE_PAYLOAD,
                lookup_fn=_lookup,
                ranking_model=fake_ranking,
                source="get_life_ranking.py",
            )
        printed = output.getvalue()
        self.assertEqual(len(lines), 2)
        self.assertEqual(matches, [])
        self.assertEqual(fake_ranking.objects.calls, [])
        self.assertIn("dry-run ranking (database not updated)", printed)
        self.assertIn("dry-run del matches (database not updated)", printed)
        self.assertIn("No del matches to store.", printed)
        self.assertIn(
            "Matchday: 55    Season: 3    UTS: 200    Source: get_life_ranking.py",
            printed,
        )
        self.assertIn("Eisbaeren Berlin", printed)
        self.assertIn("Adler Mannheim", printed)
        self.assertIn("lookup Eisbaeren Berlin", printed)
        self.assertIn(
            "warning: lookup_team failed for 'Unknown Team' (ranking 3)",
            printed,
        )

    def test_run_uses_next_match_when_closer(self):
        fake_ranking = FakeRanking()
        with redirect_stdout(io.StringIO()):
            glr.run(
                argv=["--season-id", "5"],
                now_uts=160,
                teams=TEAM_LIST,
                last_match=(10, 100, 3),
                next_match=(11, 180, False),
                payload=SAMPLE_PAYLOAD,
                lookup_fn=_lookup,
                ranking_model=fake_ranking,
            )
        self.assertEqual(fake_ranking.objects.calls[0]["matchday_id"], 11)

    def test_run_uses_fetch_fn_url(self):
        fetched = []

        def fetch_fn(url):
            fetched.append(url)
            return SAMPLE_PAYLOAD

        with redirect_stdout(io.StringIO()):
            glr.run(
                argv=["--url", "http://table.test"],
                now_uts=1,
                season_id=1,
                teams=TEAM_LIST,
                last_match=(9, 1, 1),
                next_match=(None, None, None),
                fetch_fn=fetch_fn,
                lookup_fn=_lookup,
                ranking_model=FakeRanking(),
            )
        self.assertEqual(fetched, ["http://table.test"])

    def test_run_loads_season_id_when_cli_omits_it(self):
        with mock.patch.object(glr, "load_season_id", return_value=9) as load_fn:
            glr.run(
                argv=[],
                now_uts=1,
                teams=[],
                last_match=(None, None, None),
                next_match=(None, None, None),
                payload={"Stages": []},
                ranking_model=FakeRanking(),
            )
        load_fn.assert_called_once()

    def test_run_cli_season_id_overrides_injected_value(self):
        fake_ranking = FakeRanking()
        with redirect_stdout(io.StringIO()):
            glr.run(
                argv=["--season-id", "8"],
                now_uts=200,
                season_id=4,
                teams=TEAM_LIST,
                last_match=(12, 150, 2),
                next_match=(None, None, None),
                payload=SAMPLE_PAYLOAD,
                lookup_fn=_lookup,
                ranking_model=fake_ranking,
            )
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["season_id"], 8)

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(glr, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = glr.main([])
        self.assertEqual(rc, glr.EXIT_RUNTIME_ERROR)
        self.assertIn("get_life_ranking failed: boom", output.getvalue())

    def test_main_reports_stored_count(self):
        with mock.patch.object(
            glr,
            "run",
            return_value=(["1: EBB - Eisbaeren Berlin P3 4:2"], ["EBB - MAN: 4:2 (beendet)"]),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = glr.main([])
        self.assertEqual(rc, glr.EXIT_SUCCESS)
        printed = output.getvalue()
        self.assertIn("stored 1 ranking rows", printed)
        self.assertIn("stored 1 del matches", printed)

    def test_parse_day_value_rejects_invalid(self):
        with self.assertRaises(glr.argparse.ArgumentTypeError):
            glr.parse_day_value("17.09.2026")
        self.assertEqual(glr.parse_day_value("2026-09-17"), "2026-09-17")

    def test_today_berlin_and_resolve_day(self):
        self.assertEqual(glr.today_berlin(now_uts=1789666200), "2026-09-17")
        self.assertEqual(glr.resolve_day("2026-09-18", now_uts=1789666200), "2026-09-18")
        self.assertEqual(glr.resolve_day(None, now_uts=1789666200), "2026-09-17")

    def test_esd_helpers(self):
        self.assertEqual(glr.esd_day(20260917193000), "2026-09-17")
        self.assertEqual(glr.esd_kickoff_time(20260917193000), "19:30")
        self.assertEqual(glr.esd_kickoff_time(20260920140000), "14:00")
        self.assertIsNone(glr.esd_day("abc"))
        self.assertEqual(glr.esd_to_uts(20260917193000), 1789666200)
        self.assertEqual(glr.esd_to_uts("202609171930"), 1789666200)

    def test_parse_event_result_and_status(self):
        self.assertEqual(glr.parse_event_result({"Tr1": "4", "Tr2": "2"}), "4:2")
        self.assertEqual(glr.parse_event_result({}), "-")
        self.assertEqual(glr.parse_event_result({"Tr1": None, "Tr2": None}), "-")
        self.assertEqual(
            glr.parse_event_status({"Eps": "FT", "Esd": 20260917193000}),
            "beendet",
        )
        self.assertEqual(
            glr.parse_event_status({"Eps": "NS", "Esd": 20260917193000}),
            "19:30",
        )
        self.assertEqual(
            glr.parse_event_status({"Eps": "P2", "Esd": 20260917193000}),
            "LIVE",
        )

    def test_team_name_from_side_and_parse_event(self):
        self.assertEqual(glr.team_name_from_side([{"Nm": "Eisbaeren Berlin"}]), "Eisbaeren Berlin")
        self.assertEqual(glr.team_name_from_side({"Nm": "Adler Mannheim"}), "Adler Mannheim")
        parsed = glr.parse_event(SAMPLE_EVENTS[0])
        self.assertEqual(parsed["home_name"], "Eisbaeren Berlin")
        self.assertEqual(parsed["guest_name"], "Adler Mannheim")
        self.assertEqual(parsed["result"], "4:2")
        self.assertEqual(parsed["status"], "beendet")
        self.assertEqual(parsed["kickoff"], "19:30")
        self.assertEqual(parsed["date"], 1789666200)
        not_started = glr.parse_event(SAMPLE_EVENTS[1])
        self.assertEqual(not_started["result"], "-")
        self.assertEqual(not_started["status"], "19:30")

    def test_filter_events_for_day(self):
        matched = glr.filter_events_for_day(SAMPLE_EVENTS, "2026-09-18")
        self.assertEqual(len(matched), 3)
        self.assertEqual(glr.filter_events_for_day(SAMPLE_EVENTS, "2026-01-01"), [])

    def test_run_stores_finished_match_for_cli_day(self):
        fake_ranking = FakeRanking()
        fake_delmatch = FakeDelmatch()
        output = io.StringIO()
        with redirect_stdout(output):
            _lines, matches = glr.run(
                argv=["--season-id", "5", "--day", "2026-09-17"],
                now_uts=1789666200,
                teams=TEAM_LIST,
                last_match=(55, 150, 8),
                next_match=(None, None, None),
                payload=MATCH_PAYLOAD,
                lookup_fn=_lookup,
                ranking_model=fake_ranking,
                delmatch_model=fake_delmatch,
                source="get_life_ranking.py",
            )
        self.assertEqual(matches, ["EBB - MAN: 4:2 (beendet)"])
        self.assertEqual(len(fake_delmatch.objects.calls), 1)
        call = fake_delmatch.objects.calls[0]
        self.assertEqual(call["matchday"], 8)
        self.assertEqual(call["home_team_id"], 1)
        self.assertEqual(call["guest_team_id"], 2)
        self.assertEqual(call["season_id"], 5)
        self.assertEqual(call["defaults"]["result"], "4:2")
        self.assertEqual(call["defaults"]["status"], "beendet")
        self.assertEqual(call["defaults"]["date"], 1789666200)
        self.assertEqual(call["defaults"]["update_date"], 1789666200)

    def test_run_dry_run_prints_matches_and_warns_on_lookup(self):
        fake_ranking = FakeRanking()
        fake_delmatch = FakeDelmatch()
        output = io.StringIO()
        with redirect_stdout(output):
            _lines, matches = glr.run(
                argv=["--dry-run", "--day", "2026-09-18"],
                now_uts=1789666200,
                season_id=5,
                teams=TEAM_LIST,
                last_match=(55, 150, 8),
                next_match=(None, None, None),
                payload=MATCH_PAYLOAD,
                lookup_fn=_lookup,
                ranking_model=fake_ranking,
                delmatch_model=fake_delmatch,
            )
        printed = output.getvalue()
        self.assertEqual(
            matches,
            ["KEC - MAN: - (19:30)", "MAN - KEC: 1:0 (LIVE)"],
        )
        self.assertEqual(fake_delmatch.objects.calls, [])
        self.assertIn("dry-run del matches (database not updated)", printed)
        self.assertIn("Koelner Haie", printed)
        self.assertIn("warning: lookup_team failed for 'Unknown Team'", printed)
        self.assertIn("LIVE", printed)
