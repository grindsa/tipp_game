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
    _team_row(3, "Koelner Haie", "KEC"),
]

SCHEDULE_HTML = """
<html><body>
<div id="moduleResultContentResultateList">
  <div>1. Spieltag</div>
  <ul class="table_content">
    <li class="heim">Eisbaeren Berlin</li>
    <li class="score">3:2 n.V.</li>
    <li class="auswaerts">Adler Mannheim</li>
  </ul>
  <ul class="table_content">
    <li class="heim">Koelner Haie</li>
    <li class="score">1:4</li>
    <li class="auswaerts">Straubing Tigers</li>
  </ul>
  <ul class="table_content">
    <li class="heim">Adler Mannheim</li>
    <li class="score">-:-</li>
    <li class="auswaerts">Eisbaeren Berlin</li>
  </ul>
  <div>2. Spieltag</div>
  <ul class="table_content">
    <li class="heim">Eisbaeren Berlin</li>
    <li class="score">5:1</li>
    <li class="auswaerts">Adler Mannheim</li>
  </ul>
</div>
</body></html>
"""


class FakeQuerySet(object):
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []

    def filter(self, **kwargs):
        return self

    def values(self, *fields):
        if not fields:
            return self.rows
        projected = []
        for row in self.rows:
            projected.append({field: row.get(field) for field in fields})
        self.rows = projected
        return self

    def update_or_create(self, **kwargs):
        self.calls.append(kwargs)
        return (SimpleNamespace(pk=len(self.calls)), True)

    def __getitem__(self, key):
        return self.rows[key]

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)


class FakeModel(object):
    def __init__(self, rows=None):
        self.objects = FakeQuerySet(rows)


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
        if team["team_name"] == name or team["short_name"] == name:
            return team["team_id"], team["team_name"], team["short_name"]
    return None, None, None


def _winloss(home_team_id, team_id, result):
    home, guest = result.split(":")
    diff = int(home) - int(guest)
    if home_team_id == team_id:
        return ("win" if diff >= 0 else "loss", None, None, None)
    return ("win" if diff < 0 else "loss", None, None, None)


class GetRankingTests(SimpleTestCase):
    def test_parse_args_defaults(self):
        args = gr.parse_args([])
        self.assertFalse(args.debug)
        self.assertIsNone(args.season_id)
        self.assertEqual(args.table_id, gr.DEFAULT_TABLE_ID)
        self.assertEqual(args.year, gr.DEFAULT_FAIRPLAY_YEAR)
        self.assertFalse(args.dry_run)
        self.assertEqual(args.url, gr.DEFAULT_SCHEDULE_URL)

    def test_parse_args_reads_flags(self):
        args = gr.parse_args(
            ["-d", "--season-id", "4", "--table-id", "12", "--year", "2026"]
        )
        self.assertTrue(args.debug)
        self.assertEqual(args.season_id, 4)
        self.assertEqual(args.table_id, 12)
        self.assertEqual(args.year, 2026)
        self.assertTrue(gr.parse_args(["--debug"]).debug)
        self.assertTrue(gr.parse_args(["--dry-run"]).dry_run)
        self.assertEqual(
            gr.parse_args(["--url", "http://schedule.test"]).url,
            "http://schedule.test",
        )

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

    def test_format_admin_message_includes_match_results(self):
        message = gr.format_admin_message(
            8,
            ["1: EBB - Eisbaeren Berlin"],
            ["EBB - MAN: 3:2"],
        )
        self.assertEqual(
            message,
            "*get_ranking.py*\n\n8.Spieltag: 1 Spiele eingetragen.\n\n"
            "EBB - MAN: 3:2\n\nall:\n1: EBB - Eisbaeren Berlin\n",
        )

    def test_within_notify_window(self):
        self.assertTrue(gr.within_notify_window(100, 50, window=100))
        self.assertFalse(gr.within_notify_window(151, 50, window=100))
        self.assertFalse(gr.within_notify_window(100, None))

    def test_whatsapp_notify_decision(self):
        self.assertEqual(
            gr.whatsapp_notify_decision(True, SETTINGS, 200000, 100),
            (True, "dry-run"),
        )
        self.assertEqual(
            gr.whatsapp_notify_decision(False, SimpleNamespace(), 200, 150),
            (False, "WhatsApp settings missing"),
        )
        should_send, reason = gr.whatsapp_notify_decision(False, SETTINGS, 200000, 100)
        self.assertFalse(should_send)
        self.assertIn("last match older than 86400s", reason)
        self.assertEqual(
            gr.whatsapp_notify_decision(False, SETTINGS, 200, 150),
            (True, "ok"),
        )

    def test_can_store_ranking(self):
        self.assertTrue(gr.can_store_ranking(1, 9, 3))
        self.assertFalse(gr.can_store_ranking(None, 9, 3))
        self.assertFalse(gr.can_store_ranking(1, None, 3))
        self.assertFalse(gr.can_store_ranking(1, 9, 0))
        self.assertFalse(gr.can_store_ranking(1, 9, None))

    def test_fetch_html_uses_requests(self):
        payload = b"<html>schedule</html>"
        response = mock.Mock()
        response.content = payload
        get_fn = mock.Mock(return_value=response)
        result = gr.fetch_html("https://example.test/schedule", get_fn=get_fn)
        get_fn.assert_called_once_with(
            "https://example.test/schedule", timeout=gr.HTTP_TIMEOUT_SECONDS
        )
        response.raise_for_status.assert_called_once()
        self.assertEqual(result, payload)

    def test_parse_score_and_extension(self):
        self.assertEqual(gr.parse_score("3:2"), "3:2")
        self.assertEqual(gr.parse_score("10:3 n.V."), "10:3")
        self.assertEqual(gr.parse_score(" 4 : 1 n.P. "), "4:1")
        self.assertIsNone(gr.parse_score("-:-"))
        self.assertIsNone(gr.parse_score(""))
        self.assertEqual(gr.parse_extension("3:2 n.V."), "OT")
        self.assertEqual(gr.parse_extension("3:2 n.P."), "PP")
        self.assertIsNone(gr.parse_extension("3:2"))

    def test_extract_matchday_html_stops_at_next_spieltag(self):
        fragment = gr.extract_matchday_html(SCHEDULE_HTML, 1)
        self.assertIn("1. Spieltag", fragment)
        self.assertIn("3:2 n.V.", fragment)
        self.assertNotIn("5:1", fragment)
        self.assertEqual(gr.extract_matchday_html(SCHEDULE_HTML, None), "")
        self.assertEqual(gr.extract_matchday_html("<div></div>", 1), "")

    def test_parse_match_nodes(self):
        fragment = gr.extract_matchday_html(SCHEDULE_HTML, 1)
        matches = gr.parse_match_nodes(fragment)
        self.assertEqual(len(matches), 3)
        self.assertEqual(matches[0]["home_name"], "Eisbaeren Berlin")
        self.assertEqual(matches[0]["guest_name"], "Adler Mannheim")
        self.assertEqual(matches[0]["raw_result"], "3:2 n.V.")

    def test_increment_team_stats_ot_win_and_pp_loss(self):
        base = {
            "matches": 1,
            "ebb_wins": 0,
            "ebb_losses": 0,
            "ebb_ot_wins": 0,
            "ebb_ot_losses": 0,
            "ebb_ps_wins": 0,
            "ebb_ps_losses": 0,
        }
        ot_win = gr.increment_team_stats(base, "win", "OT")
        self.assertEqual(ot_win["matches"], 2)
        self.assertEqual(ot_win["ebb_wins"], 1)
        self.assertEqual(ot_win["ebb_ot_wins"], 1)
        pp_loss = gr.increment_team_stats(base, "loss", "PP")
        self.assertEqual(pp_loss["ebb_losses"], 1)
        self.assertEqual(pp_loss["ebb_ps_losses"], 1)
        self.assertEqual(base["matches"], 1)

    def test_existing_delmatch_result_reads_stored_score(self):
        delmatch = FakeModel(
            [
                {
                    "matchday": 1,
                    "home_team_id": 1,
                    "guest_team_id": 2,
                    "season_id": 5,
                    "result": "3:2",
                }
            ]
        )
        match = gr.ParsedMatch(
            1, "Eisbaeren Berlin", "EBB", 2, "Adler Mannheim", "MAN", "3:2", "OT", "3:2 n.V."
        )
        self.assertEqual(
            gr.existing_delmatch_result(match, 1, 5, delmatch_model=delmatch),
            "3:2",
        )
        empty = FakeModel()
        self.assertIsNone(
            gr.existing_delmatch_result(match, 1, 5, delmatch_model=empty)
        )

    def test_import_matches_skips_team_stats_when_result_unchanged(self):
        delmatch = FakeModel(
            [
                {
                    "matchday": 1,
                    "home_team_id": 1,
                    "guest_team_id": 2,
                    "season_id": 5,
                    "result": "3:2",
                }
            ]
        )
        team_model = FakeModel(
            [
                {
                    "team_id": 2,
                    "matches": 4,
                    "ebb_wins": 1,
                    "ebb_losses": 0,
                    "ebb_ot_wins": 0,
                    "ebb_ot_losses": 0,
                    "ebb_ps_wins": 0,
                    "ebb_ps_losses": 0,
                }
            ]
        )
        lines = gr.import_matches(
            [
                {
                    "home_name": "Eisbaeren Berlin",
                    "guest_name": "Adler Mannheim",
                    "raw_result": "3:2 n.V.",
                }
            ],
            TEAM_LIST,
            1,
            150,
            5,
            200,
            lookup_fn=_lookup,
            team_model=team_model,
            delmatch_model=delmatch,
            winloss_fn=_winloss,
        )
        self.assertEqual(lines, ["EBB - MAN: 3:2"])
        self.assertEqual(len(delmatch.objects.calls), 1)
        self.assertEqual(team_model.objects.calls, [])

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
            html="",
        )

        self.assertEqual(helper.standings_called_with, 37)
        self.assertEqual(helper.fairplay_called_with, ("2026", 1))
        self.assertEqual(len(fake_ranking.objects.calls), 2)
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["season_id"], 5)
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["penalty"], 17)
        self.assertEqual(fake_ranking.objects.calls[1]["defaults"]["penalty"], 0)
        self.assertEqual(
            lines.ranking_lines,
            [
                "1: EBB - Eisbaeren Berlin",
                "2: MAN - Adler Mannheim",
            ],
        )
        self.assertEqual(lines.match_lines, [])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2], SETTINGS.WA_ADMIN_NUMBER)
        self.assertIn("8.Spieltag", sent[0][3])

    def test_run_dry_run_prints_and_skips_send(self):
        helper = FakeDelAppHelper(
            table=[_standing(11, "Eisbaeren Berlin", 1)],
        )
        fake_ranking = FakeRanking()
        delmatch = FakeModel()
        team_model = FakeModel(
            [
                {
                    "team_id": 2,
                    "matches": 0,
                    "ebb_wins": 0,
                    "ebb_losses": 0,
                    "ebb_ot_wins": 0,
                    "ebb_ot_losses": 0,
                    "ebb_ps_wins": 0,
                    "ebb_ps_losses": 0,
                }
            ]
        )
        sent = []
        output = io.StringIO()
        with redirect_stdout(output):
            lines = gr.run(
                argv=["--dry-run", "--season-id", "5"],
                now_uts=200,
                teams=TEAM_LIST,
                last_match=(55, 150, 1),
                helper_factory=lambda debug, cfg_file=None: helper,
                ranking_model=fake_ranking,
                lookup_fn=_lookup,
                settings_obj=SETTINGS,
                send_fn=lambda *args: sent.append(args),
                html=SCHEDULE_HTML,
                team_model=team_model,
                delmatch_model=delmatch,
                winloss_fn=_winloss,
            )
        self.assertEqual(lines.ranking_lines, ["1: EBB - Eisbaeren Berlin"])
        self.assertEqual(lines.match_lines, ["EBB - MAN: 3:2"])
        self.assertEqual(len(fake_ranking.objects.calls), 0)
        self.assertEqual(delmatch.objects.calls, [])
        self.assertEqual(team_model.objects.calls, [])
        self.assertEqual(sent, [])
        printed = output.getvalue()
        self.assertIn("dry-run ranking 1: Eisbaeren Berlin", printed)
        self.assertIn("dry-run delmatch EBB - MAN: 3:2", printed)
        self.assertIn("dry-run team_stats team_id=2", printed)
        self.assertIn("dry-run whatsapp {0}:".format(SETTINGS.WA_ADMIN_NUMBER), printed)
        self.assertIn("1.Spieltag: 1 Spiele eingetragen", printed)
        self.assertIn("1: EBB - Eisbaeren Berlin", printed)

    def test_dispatch_whatsapp_sends_admin_message(self):
        sent = []
        sent_flag = gr.dispatch_whatsapp(
            SETTINGS,
            SETTINGS.WA_ADMIN_NUMBER,
            "hello",
            send_fn=lambda *args: sent.append(args),
        )
        self.assertTrue(sent_flag)
        self.assertEqual(
            sent,
            [(SETTINGS.WA_SRV, SETTINGS.WA_PORT, SETTINGS.WA_ADMIN_NUMBER, "hello")],
        )

    def test_notify_admin_dry_run_prints_without_whatsapp_settings(self):
        sent = []
        output = io.StringIO()
        with redirect_stdout(output):
            sent_flag = gr.notify_admin(
                "hello",
                SimpleNamespace(),
                send_fn=lambda *args: sent.append(args),
                dry_run=True,
            )
        self.assertTrue(sent_flag)
        self.assertEqual(sent, [])
        self.assertIn("dry-run whatsapp WA_ADMIN_NUMBER:", output.getvalue())
        self.assertIn("hello", output.getvalue())

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

        self.assertEqual(lines.ranking_lines, [])
        self.assertEqual(lines.match_lines, [])
        self.assertEqual(fake_ranking.objects.calls, [])
        self.assertEqual(sent, [])

    def test_run_prints_when_whatsapp_is_skipped(self):
        helper = FakeDelAppHelper(table=[])
        output = io.StringIO()
        with redirect_stdout(output):
            gr.run(
                argv=[],
                now_uts=200000,
                season_id=3,
                teams=[],
                last_match=(55, 100, 8),
                helper_factory=lambda debug, cfg_file=None: helper,
                ranking_model=FakeRanking(),
                settings_obj=SETTINGS,
                send_fn=lambda *args: None,
                html="",
            )
        self.assertIn("skipped whatsapp: last match older than 86400s", output.getvalue())

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
            html="",
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

    def test_run_forwards_schedule_url(self):
        helper = FakeDelAppHelper(table=[])
        fetched = []

        def fetch_fn(url):
            fetched.append(url)
            return ""

        gr.run(
            argv=["--url", "http://schedule.test"],
            now_uts=1,
            season_id=1,
            teams=[],
            last_match=(1, 1, 1),
            helper_factory=lambda debug, cfg_file=None: helper,
            ranking_model=FakeRanking(),
            settings_obj=SimpleNamespace(),
            fetch_fn=fetch_fn,
        )
        self.assertEqual(fetched, ["http://schedule.test"])

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
            html="",
        )
        self.assertEqual(helper.standings_called_with, 9)
        self.assertEqual(helper.fairplay_called_with, ("2025", 1))
        self.assertEqual(fake_ranking.objects.calls[0]["defaults"]["season_id"], 4)

    def test_run_imports_del_results_and_sends_combined_message(self):
        helper = FakeDelAppHelper(
            table=[
                _standing(11, "Eisbaeren Berlin", 1),
                _standing(22, "Adler Mannheim", 2),
            ]
        )
        fake_ranking = FakeRanking()
        delmatch = FakeModel()
        team_model = FakeModel(
            [
                {
                    "team_id": 2,
                    "matches": 4,
                    "ebb_wins": 1,
                    "ebb_losses": 0,
                    "ebb_ot_wins": 0,
                    "ebb_ot_losses": 0,
                    "ebb_ps_wins": 0,
                    "ebb_ps_losses": 0,
                }
            ]
        )
        sent = []

        result = gr.run(
            argv=["--season-id", "5"],
            now_uts=200,
            teams=TEAM_LIST,
            last_match=(55, 150, 1),
            helper_factory=lambda debug, cfg_file=None: helper,
            ranking_model=fake_ranking,
            lookup_fn=_lookup,
            settings_obj=SETTINGS,
            send_fn=lambda *args: sent.append(args),
            html=SCHEDULE_HTML,
            team_model=team_model,
            delmatch_model=delmatch,
            winloss_fn=_winloss,
        )

        self.assertEqual(result.match_lines, ["EBB - MAN: 3:2"])
        self.assertEqual(
            result.ranking_lines,
            ["1: EBB - Eisbaeren Berlin", "2: MAN - Adler Mannheim"],
        )
        self.assertEqual(len(delmatch.objects.calls), 1)
        self.assertEqual(delmatch.objects.calls[0]["defaults"]["result"], "3:2")
        self.assertEqual(len(team_model.objects.calls), 1)
        self.assertEqual(team_model.objects.calls[0]["defaults"]["ebb_wins"], 2)
        self.assertEqual(team_model.objects.calls[0]["defaults"]["ebb_ot_wins"], 1)
        self.assertEqual(len(sent), 1)
        message = sent[0][3]
        self.assertIn("1.Spieltag: 1 Spiele eingetragen", message)
        self.assertIn("EBB - MAN: 3:2", message)
        self.assertIn("1: EBB - Eisbaeren Berlin", message)
        self.assertIn("2: MAN - Adler Mannheim", message)

    def test_run_keeps_ranking_when_delgames_fetch_fails(self):
        helper = FakeDelAppHelper(table=[_standing(11, "Eisbaeren Berlin", 1)])
        fake_ranking = FakeRanking()
        output = io.StringIO()

        def fetch_fn(_url):
            raise RuntimeError("sportal down")

        with redirect_stdout(output):
            result = gr.run(
                argv=["--season-id", "5"],
                now_uts=200,
                teams=TEAM_LIST,
                last_match=(55, 150, 8),
                helper_factory=lambda debug, cfg_file=None: helper,
                ranking_model=fake_ranking,
                lookup_fn=_lookup,
                settings_obj=SimpleNamespace(),
                fetch_fn=fetch_fn,
            )
        self.assertEqual(result.ranking_lines, ["1: EBB - Eisbaeren Berlin"])
        self.assertEqual(result.match_lines, [])
        self.assertEqual(len(fake_ranking.objects.calls), 1)
        self.assertIn("result import failed: sportal down", output.getvalue())

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(gr, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = gr.main([])
        self.assertEqual(rc, gr.EXIT_RUNTIME_ERROR)
        self.assertIn("get_ranking failed: boom", output.getvalue())

    def test_main_reports_stored_count(self):
        with mock.patch.object(
            gr,
            "run",
            return_value=gr.RunResult(["1: EBB - Eisbaeren Berlin"], ["EBB - MAN: 3:2"]),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = gr.main([])
        self.assertEqual(rc, gr.EXIT_SUCCESS)
        self.assertIn("stored 1 ranking rows, 1 del matches", output.getvalue())

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
