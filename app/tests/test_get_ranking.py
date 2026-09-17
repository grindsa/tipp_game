import io
import os
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import get_ranking as gr


SETTINGS = SimpleNamespace(
    WA_ADMIN_NUMBER="491700000000",
    WA_SRV="wa.local",
    WA_PORT=9009,
)


class FakeRankingManager(object):
    def __init__(self):
        self.calls = []

    def update_or_create(self, **kwargs):
        self.calls.append(kwargs)
        return (SimpleNamespace(pk=len(self.calls)), True)


class FakeRanking(object):
    def __init__(self):
        self.objects = FakeRankingManager()


class FakeDelAppHelper(object):
    def __init__(self, table=None, fairplay=None):
        self.table = table if table is not None else []
        self.fairplay = fairplay if fairplay is not None else []
        self.standings_called_with = None
        self.fairplay_called_with = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def standings_get(self, table_id=None):
        self.standings_called_with = table_id
        return {"table": self.table}

    def fairplay_ranking_get(self, year, league_id):
        self.fairplay_called_with = (year, league_id)
        return self.fairplay


def _team_row(team_id, name, short_name):
    return {
        "team_id": team_id,
        "team_name": name,
        "short_name": short_name,
    }


TEAM_LIST = [
    _team_row(1, "Eisbaeren Berlin", "EBB"),
    _team_row(2, "Adler Mannheim", "MAN"),
]


def _standing(team_id, name, position, **overrides):
    row = {
        "id": team_id,
        "name": name,
        "position": position,
        "games": 10,
        "wins": 6,
        "onlyOTwins": 1,
        "onlySOwins": 1,
        "onlyOTlosts": 2,
        "score1": 30,
        "score2": 20,
        "points": 20,
    }
    row.update(overrides)
    return row


def _lookup(team_list, name):
    for team in team_list:
        if team["team_name"] == name:
            return team["team_id"], team["team_name"], team["short_name"]
    return None, None, None


class GetRankingTests(SimpleTestCase):
    def test_parse_args_defaults(self):
        args = gr.parse_args([])
        self.assertFalse(args.debug)
        self.assertIsNone(args.season_id)
        self.assertEqual(args.table_id, gr.DEFAULT_TABLE_ID)
        self.assertEqual(args.year, gr.DEFAULT_FAIRPLAY_YEAR)

    def test_parse_args_reads_flags(self):
        args = gr.parse_args(
            ["-d", "--season-id", "4", "--table-id", "12", "--year", "2026"]
        )
        self.assertTrue(args.debug)
        self.assertEqual(args.season_id, 4)
        self.assertEqual(args.table_id, 12)
        self.assertEqual(args.year, 2026)
        self.assertTrue(gr.parse_args(["--debug"]).debug)

    def test_load_season_id_counts_season_rows(self):
        class SeasonModel(object):
            class objects(object):
                @staticmethod
                def values():
                    return [{"id": 1}, {"id": 2}, {"id": 3}]

        self.assertEqual(gr.load_season_id(season_model=SeasonModel), 3)

    def test_fairplay_penalties_maps_team_minutes(self):
        helper = FakeDelAppHelper(
            fairplay=[
                {"teamId": 1, "penaltyMinutes": {"total": 44}},
                {"teamId": 2, "penaltyMinutes": {}},
                {"penaltyMinutes": {"total": 9}},
            ]
        )
        self.assertEqual(gr.fairplay_penalties(helper, 2026, 1), {1: 44, 2: 0})
        self.assertEqual(helper.fairplay_called_with, ("2026", 1))

    def test_fetch_standings_table_handles_missing_payload(self):
        helper = FakeDelAppHelper(table=[{"id": 1}])
        self.assertEqual(gr.fetch_standings_table(helper, 37), [{"id": 1}])
        self.assertEqual(helper.standings_called_with, 37)

        class EmptyHelper(object):
            def standings_get(self, table_id=None):
                return None

        self.assertEqual(gr.fetch_standings_table(EmptyHelper(), 1), [])

    def test_build_ranking_defaults_maps_standings_fields(self):
        team = _standing(9, "Eisbaeren Berlin", 3)
        defaults = gr.build_ranking_defaults(team, 1, 7, 1000, 44)
        self.assertEqual(defaults["season_id"], 7)
        self.assertEqual(defaults["ranking"], 3)
        self.assertEqual(defaults["team_id"], 1)
        self.assertEqual(defaults["match"], 10)
        self.assertEqual(defaults["won"], 6)
        self.assertEqual(defaults["wono"], 1)
        self.assertEqual(defaults["wonp"], 1)
        self.assertEqual(defaults["losto"], 2)
        self.assertEqual(defaults["lostp"], 2)
        self.assertEqual(defaults["goal"], 30)
        self.assertEqual(defaults["ggoal"], 20)
        self.assertEqual(defaults["score"], 20)
        self.assertEqual(defaults["uts"], 1000)
        self.assertEqual(defaults["penalty"], 44)
        self.assertEqual(defaults["source"], gr.SOURCE_NAME)
        self.assertEqual(defaults["type"], gr.RANKING_TYPE)

    def test_persist_ranking_calls_update_or_create(self):
        fake_ranking = FakeRanking()
        team = _standing(9, "Eisbaeren Berlin", 3)
        gr.persist_ranking(55, team, 1, 7, 1000, 12, ranking_model=fake_ranking)
        self.assertEqual(len(fake_ranking.objects.calls), 1)
        call = fake_ranking.objects.calls[0]
        self.assertEqual(call["matchday_id"], 55)
        self.assertEqual(call["ranking"], 3)
        self.assertEqual(call["type"], "all")
        self.assertEqual(call["defaults"]["team_id"], 1)
        self.assertEqual(call["defaults"]["penalty"], 12)

    def test_format_admin_message(self):
        message = gr.format_admin_message(8, ["1: EBB - Eisbaeren Berlin"])
        self.assertEqual(
            message,
            "*get_ranking.py*\n\n8.Spieltag:\n\nall:\n1: EBB - Eisbaeren Berlin\n",
        )

    def test_within_notify_window(self):
        self.assertTrue(gr.within_notify_window(100, 50, window=100))
        self.assertFalse(gr.within_notify_window(151, 50, window=100))
        self.assertFalse(gr.within_notify_window(100, None))

    def test_can_store_ranking(self):
        self.assertTrue(gr.can_store_ranking(1, 9, 3))
        self.assertFalse(gr.can_store_ranking(None, 9, 3))
        self.assertFalse(gr.can_store_ranking(1, None, 3))
        self.assertFalse(gr.can_store_ranking(1, 9, 0))
        self.assertFalse(gr.can_store_ranking(1, 9, None))

    def test_run_stores_rows_and_notifies_admin(self):
        helper = FakeDelAppHelper(
            table=[
                _standing(11, "Eisbaeren Berlin", 1),
                _standing(22, "Adler Mannheim", 2),
                _standing(33, "Unknown Team", 3),
            ],
            fairplay=[{"teamId": 11, "penaltyMinutes": {"total": 17}}],
        )
        fake_ranking = FakeRanking()
        sent = []

        def send_fn(server, port, number, message):
            sent.append((server, port, number, message))

        lines = gr.run(
            argv=["--season-id", "5", "--table-id", "37", "--year", "2026"],
            now_uts=200,
            teams=TEAM_LIST,
            last_match=(55, 150, 8),
            helper_factory=lambda debug, cfg_file=None: helper,
            ranking_model=fake_ranking,
            lookup_fn=_lookup,
            settings_obj=SETTINGS,
            send_fn=send_fn,
        )

        self.assertEqual(helper.standings_called_with, 37)
        self.assertEqual(helper.fairplay_called_with, ("2026", 1))
        self.assertEqual(len(fake_ranking.objects.calls), 2)
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["season_id"], 5)
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["penalty"], 17)
        self.assertEqual(fake_ranking.objects.calls[1]["defaults"]["penalty"], 0)
        self.assertEqual(
            lines,
            [
                "1: EBB - Eisbaeren Berlin",
                "2: MAN - Adler Mannheim",
            ],
        )
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2], SETTINGS.WA_ADMIN_NUMBER)
        self.assertIn("8.Spieltag", sent[0][3])

    def test_run_skips_persist_without_matchday_and_skips_stale_notify(self):
        helper = FakeDelAppHelper(table=[_standing(11, "Eisbaeren Berlin", 1)])
        fake_ranking = FakeRanking()
        sent = []

        lines = gr.run(
            argv=[],
            now_uts=200000,
            season_id=3,
            teams=TEAM_LIST,
            last_match=(55, 100, 0),
            helper_factory=lambda debug, cfg_file=None: helper,
            ranking_model=fake_ranking,
            lookup_fn=_lookup,
            settings_obj=SETTINGS,
            send_fn=lambda *args: sent.append(args),
        )

        self.assertEqual(lines, [])
        self.assertEqual(fake_ranking.objects.calls, [])
        self.assertEqual(sent, [])

    def test_run_loads_season_id_when_cli_omits_it(self):
        helper = FakeDelAppHelper(table=[])
        with mock.patch.object(gr, "load_season_id", return_value=9) as load_fn:
            gr.run(
                argv=["--table-id", "37"],
                now_uts=1,
                teams=[],
                last_match=(None, None, None),
                helper_factory=lambda debug, cfg_file=None: helper,
                ranking_model=FakeRanking(),
                settings_obj=SimpleNamespace(),
            )
        load_fn.assert_called_once()

    def test_run_cli_season_id_overrides_injected_value(self):
        helper = FakeDelAppHelper(table=[_standing(11, "Eisbaeren Berlin", 1)])
        fake_ranking = FakeRanking()
        gr.run(
            argv=["--season-id", "8"],
            now_uts=200,
            season_id=4,
            teams=TEAM_LIST,
            last_match=(12, 150, 2),
            helper_factory=lambda debug, cfg_file=None: helper,
            ranking_model=fake_ranking,
            lookup_fn=_lookup,
            settings_obj=SimpleNamespace(),
        )
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["season_id"], 8)

    def test_run_forwards_debug_to_helper(self):
        seen = []
        helper = FakeDelAppHelper(table=[])

        def factory(debug, cfg_file=None):
            seen.append(debug)
            return helper

        gr.run(
            argv=["--debug"],
            now_uts=1,
            season_id=1,
            teams=[],
            last_match=(None, None, None),
            helper_factory=factory,
            ranking_model=FakeRanking(),
            settings_obj=SimpleNamespace(),
        )
        self.assertEqual(seen, [True])

    def test_run_uses_injected_season_when_cli_omits_it(self):
        helper = FakeDelAppHelper(table=[_standing(11, "Eisbaeren Berlin", 1)])
        fake_ranking = FakeRanking()
        gr.run(
            argv=["--table-id", "9", "--year", "2025"],
            now_uts=200,
            season_id=4,
            teams=TEAM_LIST,
            last_match=(12, 150, 2),
            helper_factory=lambda debug, cfg_file=None: helper,
            ranking_model=fake_ranking,
            lookup_fn=_lookup,
            settings_obj=SimpleNamespace(),
        )
        self.assertEqual(helper.standings_called_with, 9)
        self.assertEqual(helper.fairplay_called_with, ("2025", 1))
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["season_id"], 4)

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(gr, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = gr.main([])
        self.assertEqual(rc, gr.EXIT_RUNTIME_ERROR)
        self.assertIn("get_ranking failed: boom", output.getvalue())

    def test_main_reports_stored_count(self):
        with mock.patch.object(gr, "run", return_value=["1: EBB - Eisbaeren Berlin"]):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = gr.main([])
        self.assertEqual(rc, gr.EXIT_SUCCESS)
        self.assertIn("stored 1 ranking rows", output.getvalue())

    def test_default_config_path_uses_script_directory(self):
        path = gr.default_config_path("/tmp/tools/get_ranking.py")
        self.assertEqual(path, "/tmp/tools/delapphelper.cfg")

    @mock.patch.dict(os.environ, {"DELAPPHELPER_CFG": "/secret/delapphelper.cfg"}, clear=False)
    def test_default_config_path_prefers_env(self):
        self.assertEqual(
            gr.default_config_path("/tmp/tools/get_ranking.py"),
            "/secret/delapphelper.cfg",
        )

    def test_create_del_app_helper_requires_config_file(self):
        with mock.patch.dict("sys.modules", {"delapphelper": mock.Mock(DelAppHelper=mock.Mock())}):
            with self.assertRaises(RuntimeError) as raised:
                gr.create_del_app_helper(False, cfg_file="/missing/delapphelper.cfg")
        self.assertIn("delapphelper config not found", str(raised.exception))
