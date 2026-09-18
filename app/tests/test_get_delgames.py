import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import get_delgames as gd


SETTINGS = SimpleNamespace(
    WA_ADMIN_NUMBER="491700000000",
    WA_SRV="wa.local",
    WA_PORT=9009,
)

TEAM_LIST = [
    {"team_id": 1, "team_name": "Eisbaeren Berlin", "short_name": "EBB", "del_team": True},
    {"team_id": 2, "team_name": "Adler Mannheim", "short_name": "MAN", "del_team": True},
    {"team_id": 3, "team_name": "Koelner Haie", "short_name": "KEC", "del_team": True},
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
        self.filter_kwargs = None

    def filter(self, **kwargs):
        self.filter_kwargs = kwargs
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


class GetDelgamesTests(SimpleTestCase):
    def test_parse_args_defaults_debug_and_dry_run(self):
        defaults = gd.parse_args([])
        self.assertFalse(defaults.debug)
        self.assertFalse(defaults.dry_run)
        self.assertIsNone(defaults.season_id)
        self.assertEqual(defaults.url, gd.DEFAULT_SCHEDULE_URL)
        self.assertTrue(gd.parse_args(["-d"]).debug)
        self.assertTrue(gd.parse_args(["--debug"]).debug)
        self.assertTrue(gd.parse_args(["--dry-run"]).dry_run)
        args = gd.parse_args(["--season-id", "4", "--url", "http://example.test"])
        self.assertEqual(args.season_id, 4)
        self.assertEqual(args.url, "http://example.test")

    def test_fetch_html_uses_requests(self):
        payload = b"<html>schedule</html>"
        response = mock.Mock()
        response.content = payload
        get_fn = mock.Mock(return_value=response)
        result = gd.fetch_html("https://example.test/schedule", get_fn=get_fn)
        get_fn.assert_called_once_with(
            "https://example.test/schedule", timeout=gd.HTTP_TIMEOUT_SECONDS
        )
        response.raise_for_status.assert_called_once()
        self.assertEqual(result, payload)

    def test_parse_score_and_extension(self):
        self.assertEqual(gd.parse_score("3:2"), "3:2")
        self.assertEqual(gd.parse_score("10:3 n.V."), "10:3")
        self.assertEqual(gd.parse_score(" 4 : 1 n.P. "), "4:1")
        self.assertIsNone(gd.parse_score("-:-"))
        self.assertIsNone(gd.parse_score(""))
        self.assertEqual(gd.parse_extension("3:2 n.V."), "OT")
        self.assertEqual(gd.parse_extension("3:2 n.P."), "PP")
        self.assertIsNone(gd.parse_extension("3:2"))

    def test_extract_matchday_html_stops_at_next_spieltag(self):
        fragment = gd.extract_matchday_html(SCHEDULE_HTML, 1)
        self.assertIn("1. Spieltag", fragment)
        self.assertIn("3:2 n.V.", fragment)
        self.assertNotIn("5:1", fragment)
        self.assertEqual(gd.extract_matchday_html(SCHEDULE_HTML, None), "")
        self.assertEqual(gd.extract_matchday_html("<div></div>", 1), "")

    def test_parse_match_nodes(self):
        fragment = gd.extract_matchday_html(SCHEDULE_HTML, 1)
        matches = gd.parse_match_nodes(fragment)
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
        ot_win = gd.increment_team_stats(base, "win", "OT")
        self.assertEqual(ot_win["matches"], 2)
        self.assertEqual(ot_win["ebb_wins"], 1)
        self.assertEqual(ot_win["ebb_ot_wins"], 1)
        pp_loss = gd.increment_team_stats(base, "loss", "PP")
        self.assertEqual(pp_loss["ebb_losses"], 1)
        self.assertEqual(pp_loss["ebb_ps_losses"], 1)
        self.assertEqual(base["matches"], 1)

    def test_format_admin_message(self):
        message = gd.format_admin_message(8, 2, ["EBB - MAN: 3:2"])
        self.assertEqual(
            message,
            "*get_delgames.py*\n\n8.Spieltag: 2 Spiele eingetragen.\n\nEBB - MAN: 3:2\n",
        )

    def test_run_persists_finished_matches_and_notifies(self):
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

        lines = gd.run(
            argv=["--season-id", "5"],
            now_uts=200,
            teams=TEAM_LIST,
            last_match=(9, 150, 1),
            html=SCHEDULE_HTML,
            lookup_fn=_lookup,
            team_model=team_model,
            delmatch_model=delmatch,
            winloss_fn=_winloss,
            settings_obj=SETTINGS,
            send_fn=lambda *args: sent.append(args),
        )

        self.assertEqual(lines, ["EBB - MAN: 3:2"])
        self.assertEqual(len(delmatch.objects.calls), 1)
        call = delmatch.objects.calls[0]
        self.assertEqual(call["matchday"], 1)
        self.assertEqual(call["home_team_id"], 1)
        self.assertEqual(call["guest_team_id"], 2)
        self.assertEqual(call["defaults"]["result"], "3:2")
        self.assertEqual(call["defaults"]["season_id"], 5)
        self.assertEqual(len(team_model.objects.calls), 1)
        self.assertEqual(team_model.objects.calls[0]["defaults"]["ebb_wins"], 2)
        self.assertEqual(team_model.objects.calls[0]["defaults"]["ebb_ot_wins"], 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2], SETTINGS.WA_ADMIN_NUMBER)
        self.assertIn("1.Spieltag: 1 Spiele eingetragen", sent[0][3])

    def test_run_dry_run_skips_persist_and_send(self):
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
            lines = gd.run(
                argv=["--dry-run", "--debug"],
                now_uts=200,
                season_id=3,
                teams=TEAM_LIST,
                last_match=(9, 150, 1),
                html=SCHEDULE_HTML,
                lookup_fn=_lookup,
                team_model=team_model,
                delmatch_model=delmatch,
                winloss_fn=_winloss,
                settings_obj=SETTINGS,
                send_fn=lambda *args: sent.append(args),
            )

        printed = output.getvalue()
        self.assertEqual(lines, ["EBB - MAN: 3:2"])
        self.assertEqual(delmatch.objects.calls, [])
        self.assertEqual(team_model.objects.calls, [])
        self.assertEqual(sent, [])
        self.assertIn("dry-run delmatch EBB - MAN: 3:2", printed)
        self.assertIn("dry-run team_stats team_id=2", printed)
        self.assertIn("dry-run whatsapp 491700000000:", printed)

    def test_run_uses_fetch_fn_url(self):
        fetched = []

        def fetch_fn(url):
            fetched.append(url)
            return SCHEDULE_HTML

        gd.run(
            argv=["--url", "http://schedule.test"],
            now_uts=1,
            season_id=1,
            teams=[],
            last_match=(None, None, 1),
            fetch_fn=fetch_fn,
            delmatch_model=FakeModel(),
            settings_obj=SimpleNamespace(),
        )
        self.assertEqual(fetched, ["http://schedule.test"])

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(gd, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = gd.main([])
        self.assertEqual(rc, gd.EXIT_RUNTIME_ERROR)
        self.assertIn("get_delgames failed: boom", output.getvalue())

    def test_main_reports_stored_count(self):
        with mock.patch.object(gd, "run", return_value=["EBB - MAN: 3:2"]):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = gd.main(["--debug", "--dry-run"])
        self.assertEqual(rc, gd.EXIT_SUCCESS)
        self.assertIn("stored 1 del matches", output.getvalue())
