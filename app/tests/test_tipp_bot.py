import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import tipp_bot as tb


SETTINGS = SimpleNamespace(WA_SRV="wa.local", WA_PORT=9009)

HOME_MATCH = [
    {
        "date": 100,
        "matchday": 12,
        "home_team__short_name": "EBB",
        "guest_team__short_name": "MAN",
        "home_team__team_name": "Eisbaeren Berlin",
        "guest_team__team_name": "Adler Mannheim",
    }
]

AWAY_MATCH = [
    {
        "date": 100,
        "matchday": 12,
        "home_team__short_name": "MAN",
        "guest_team__short_name": "EBB",
        "home_team__team_name": "Adler Mannheim",
        "guest_team__team_name": "Eisbaeren Berlin",
    }
]


class TippBotTests(SimpleTestCase):
    def test_parse_args_requires_profile_and_reads_dry_run(self):
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                tb.parse_args([])

        args = tb.parse_args(["--profile", "josi", "--dry-run"])
        self.assertEqual(args.profile, "josi")
        self.assertTrue(args.dry_run)

    def test_profiles_keep_original_usernames_and_tips(self):
        self.assertEqual(tb.PROFILES["josi"]["username"], "Josi")
        self.assertEqual(tb.PROFILES["josi"]["mobile"], "+491723922673")
        self.assertEqual(tb.PROFILES["josi"]["home_tip"], "4:2")
        self.assertEqual(tb.PROFILES["josi"]["away_tip"], "2:4")
        self.assertEqual(tb.PROFILES["hendrik"]["username"], "Hendrik")
        self.assertEqual(tb.PROFILES["hendrik"]["mobile"], "+4917672607130")
        self.assertEqual(tb.PROFILES["hendrik"]["home_tip"], "3:2")
        self.assertEqual(tb.PROFILES["hendrik"]["away_tip"], "2:3")

    def test_choose_tip_and_opponent_for_home_and_away(self):
        tip, opponent, home_short, guest_short = tb.choose_tip_and_opponent(
            HOME_MATCH, "4:2", "2:4"
        )
        self.assertEqual((tip, opponent, home_short, guest_short), ("4:2", "Adler Mannheim", "EBB", "MAN"))

        tip, opponent, home_short, guest_short = tb.choose_tip_and_opponent(
            AWAY_MATCH, "3:2", "2:3"
        )
        self.assertEqual((tip, opponent, home_short, guest_short), ("2:3", "Adler Mannheim", "MAN", "EBB"))

    def test_choose_tip_and_opponent_handles_empty_rows(self):
        tip, opponent, home_short, guest_short = tb.choose_tip_and_opponent([], "4:2", "2:4")
        self.assertEqual((tip, opponent, home_short, guest_short), (None, None, None, None))

    def test_rankings_for_match_maps_ebb_and_opponent(self):
        rows = [
            {"ranking": 1, "team__short_name": "EBB"},
            {"ranking": 5, "team__short_name": "MAN"},
        ]
        self.assertEqual(tb.rankings_for_match(rows, "EBB", "MAN"), (1, 5))
        self.assertEqual(tb.rankings_for_match(rows, "MAN", "EBB"), (1, 5))

    def test_build_message_includes_rankings_when_both_present(self):
        with_rank = tb.build_message("Josi", "Adler Mannheim", "4:2", 1, 5)
        self.assertIn("Hallo Josi,", with_rank)
        self.assertIn("gegen Adler Mannheim", with_rank)
        self.assertIn("4:2 getippt", with_rank)
        self.assertIn(tb.BOOT_EMOJI, with_rank)
        self.assertIn("auf Platz 1", with_rank)
        self.assertIn('"Adler Mannheim" auf Platz 5', with_rank)

        without_rank = tb.build_message("Josi", "Adler Mannheim", "4:2", None, None)
        self.assertIn("Hallo Josi,", without_rank)
        self.assertNotIn("PS:", without_rank)

    def test_build_tip_defaults_keeps_original_luser(self):
        defaults = tb.build_tip_defaults(9, "4:2", 3, 1700000000)
        self.assertEqual(
            defaults,
            {
                "match_id": 9,
                "tip": "4:2",
                "user_id": 3,
                "date": 1700000000,
                "luser": "Josi-Bot",
            },
        )

    def test_dispatch_whatsapp_dry_run_keeps_plus_and_skips_send(self):
        send_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            tb.dispatch_whatsapp(SETTINGS, "+491723922673", "hello", dry_run=True, send_fn=send_fn)
        send_fn.assert_not_called()
        self.assertIn("dry-run whatsapp +491723922673:", output.getvalue())

    def test_dispatch_whatsapp_sends_mobile_unchanged(self):
        send_fn = mock.Mock()
        tb.dispatch_whatsapp(SETTINGS, "+491723922673", "hello", dry_run=False, send_fn=send_fn)
        send_fn.assert_called_once_with("wa.local", 9009, "+491723922673", "hello")

    def test_place_and_notify_skips_missing_user(self):
        persist_fn = mock.Mock()
        send_fn = mock.Mock()
        rc = tb.place_and_notify(
            tb.PROFILES["josi"],
            50,
            SETTINGS,
            load_user_id_fn=lambda _name: None,
            persist_fn=persist_fn,
            send_fn=send_fn,
            season_id=15,
        )
        self.assertEqual(rc, tb.EXIT_SUCCESS)
        persist_fn.assert_not_called()
        send_fn.assert_not_called()

    def test_place_and_notify_persists_josi_home_tip_and_sends(self):
        persist_fn = mock.Mock()
        send_fn = mock.Mock()
        tb.place_and_notify(
            tb.PROFILES["josi"],
            50,
            SETTINGS,
            next_match_fn=lambda _uts, _season: (9, 100, False),
            last_match_fn=lambda _uts, _season: (8, 90, 11),
            load_user_id_fn=lambda _name: 3,
            load_match_rows_fn=lambda _match_id: HOME_MATCH,
            load_ranking_rows_fn=lambda _last_id: [
                {"ranking": 1, "team__short_name": "EBB"},
                {"ranking": 5, "team__short_name": "MAN"},
            ],
            persist_fn=persist_fn,
            send_fn=send_fn,
            season_id=15,
        )
        persist_fn.assert_called_once()
        _match_id, user_id, defaults = persist_fn.call_args.args
        self.assertEqual(user_id, 3)
        self.assertEqual(defaults["tip"], "4:2")
        self.assertEqual(defaults["luser"], "Josi-Bot")
        send_fn.assert_called_once()
        self.assertEqual(send_fn.call_args.args[2], "+491723922673")
        self.assertIn("4:2 getippt", send_fn.call_args.args[3])
        self.assertIn("Platz 1", send_fn.call_args.args[3])

    def test_place_and_notify_uses_hendrik_away_tip(self):
        persist_fn = mock.Mock()
        send_fn = mock.Mock()
        tb.place_and_notify(
            tb.PROFILES["hendrik"],
            50,
            SETTINGS,
            next_match_fn=lambda _uts, _season: (9, 100, False),
            last_match_fn=lambda _uts, _season: (8, 90, 11),
            load_user_id_fn=lambda _name: 7,
            load_match_rows_fn=lambda _match_id: AWAY_MATCH,
            load_ranking_rows_fn=lambda _last_id: [],
            persist_fn=persist_fn,
            send_fn=send_fn,
            season_id=15,
        )
        self.assertEqual(persist_fn.call_args.args[2]["tip"], "2:3")
        self.assertEqual(send_fn.call_args.args[2], "+4917672607130")
        self.assertIn("2:3 getippt", send_fn.call_args.args[3])
        self.assertNotIn("PS:", send_fn.call_args.args[3])

    def test_place_and_notify_dry_run_skips_persist_and_send(self):
        persist_fn = mock.Mock()
        send_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            tb.place_and_notify(
                tb.PROFILES["josi"],
                50,
                SETTINGS,
                dry_run=True,
                next_match_fn=lambda _uts, _season: (9, 100, False),
                last_match_fn=lambda _uts, _season: (8, 90, 11),
                load_user_id_fn=lambda _name: 3,
                load_match_rows_fn=lambda _match_id: HOME_MATCH,
                load_ranking_rows_fn=lambda _last_id: [],
                persist_fn=persist_fn,
                send_fn=send_fn,
                season_id=15,
            )

        persist_fn.assert_not_called()
        send_fn.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run tip user=Josi match_id=9 tip=4:2", printed)
        self.assertIn("dry-run whatsapp +491723922673:", printed)

    def test_run_selects_profile_from_cli(self):
        with mock.patch.object(tb, "place_and_notify", return_value=tb.EXIT_SUCCESS) as place:
            rc = tb.run(
                argv=["--profile", "hendrik", "--dry-run"],
                now_uts=50,
                settings_obj=SETTINGS,
                season_id=15,
            )
        self.assertEqual(rc, tb.EXIT_SUCCESS)
        self.assertEqual(place.call_args.args[0], tb.PROFILES["hendrik"])
        self.assertTrue(place.call_args.kwargs["dry_run"])

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(tb, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = tb.main(["--profile", "josi"])
        self.assertEqual(rc, tb.EXIT_RUNTIME_ERROR)
        self.assertIn("tipp_bot failed: boom", output.getvalue())
