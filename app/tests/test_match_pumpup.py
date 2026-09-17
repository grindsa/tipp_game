import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import match_pumpup as mp


SETTINGS = SimpleNamespace(
    ALLOWED_HOSTS=["tippspiel.example"],
    WA_SRV="wa.local",
    WA_PORT=9009,
    TR_ID="*ABCD",
    TR_SECRET="secret",
    TR_SK="private:key",
)

HOME_DETAILS = mp.MatchDetails(
    no_bet=False,
    matchday=3,
    home_id=1,
    home_name="Eisbären Berlin",
    home_short="EBB",
    guest_id=2,
    guest_name="Adler Mannheim",
    guest_short="MAN",
    tv=True,
    playoff=False,
    opponent_del_id=7,
)

EMPTY_RANKING = {
    "ht": {"ranking": None, "score": None, "match": None},
    "gt": {"ranking": None, "score": None, "match": None},
}


def ranking(home_rank, guest_rank, home_match=10, guest_match=10, home_score=20, guest_score=12):
    return {
        "ht": {"ranking": home_rank, "match": home_match, "score": home_score},
        "gt": {"ranking": guest_rank, "match": guest_match, "score": guest_score},
    }


class FakeQuery(object):
    def __init__(self, rows):
        self.rows = rows

    def values(self, *args):
        return self

    def __getitem__(self, key):
        return self.rows[key]


class FakeMatchModel(object):
    def __init__(self, rows):
        self.rows = rows

    class objects(object):
        pass

    def filter(self, **kwargs):
        return FakeQuery(self.rows)


class MatchPumpupTests(SimpleTestCase):
    def test_parse_args_defaults_and_dry_run(self):
        defaults = mp.parse_args([])
        self.assertFalse(defaults.dry_run)

        args = mp.parse_args(["--dry-run"])
        self.assertTrue(args.dry_run)

    def test_build_tip_url(self):
        self.assertEqual(
            mp.build_tip_url(["tippspiel.example", "other"]),
            "http://tippspiel.example/game/tip",
        )

    def test_format_match_date_uses_utc(self):
        self.assertEqual(mp.format_match_date(0), "01.01.70")
        self.assertEqual(mp.format_match_date(86400), "02.01.70")

    def test_match_is_within_window(self):
        self.assertTrue(mp.match_is_within_window(100, 50, threshold=60))
        self.assertFalse(mp.match_is_within_window(100, 100, threshold=60))
        self.assertFalse(mp.match_is_within_window(200, 50, threshold=60))
        self.assertFalse(mp.match_is_within_window(None, 50, threshold=60))

    def test_shorten_player_name(self):
        self.assertEqual(mp.shorten_player_name("Alexander Sulzer"), "Alexander Sulzer")
        self.assertEqual(
            mp.shorten_player_name("Maximilian Hellmuth"), "M. Hellmuth"
        )
        self.assertEqual(mp.shorten_player_name("OneName"), "OneName")
        self.assertEqual(mp.shorten_player_name(None), None)

    def test_format_top_scorers_handles_empty_and_zero_goals(self):
        self.assertIsNone(mp.format_top_scorers([], "Eisbären Berlin"))
        self.assertIsNone(
            mp.format_top_scorers(
                [{"name": "A", "number": 1, "goals": 0}], "Eisbären Berlin"
            )
        )

    def test_format_top_scorers_keeps_top_five_with_goals(self):
        players = [
            {"name": "Maximilian Hellmuth", "number": 17, "goals": 8},
            {"name": "Bob", "number": 9, "goals": 5},
            {"name": "Cara", "number": 8, "goals": 4},
            {"name": "Dan", "number": 7, "goals": 3},
            {"name": "Eve", "number": 6, "goals": 2},
            {"name": "Fay", "number": 5, "goals": 1},
            {"name": "Gus", "number": 4, "goals": 0},
        ]
        body = mp.format_top_scorers(players, "Eisbären Berlin")
        self.assertEqual(
            body,
            '\n*Topscorer "Eisbären Berlin" nach Toren:*\n'
            "M. Hellmuth (17) - 8\n"
            "Bob (9) - 5\n"
            "Cara (8) - 4\n"
            "Dan (7) - 3\n"
            "Eve (6) - 2\n",
        )
        self.assertNotIn("Fay", body)

    def test_load_match_details_returns_empty_when_missing(self):
        model = FakeMatchModel([])
        model.objects.filter = lambda **kwargs: FakeQuery([])
        details = mp.load_match_details(99, match_model=model)
        self.assertEqual(details, mp.EMPTY_MATCH)

    def test_load_match_details_picks_opponent_del_id(self):
        rows = [
            {
                "matchday": 3,
                "home_team__team_id": 1,
                "guest_team__team_id": 2,
                "home_team__short_name": "EBB",
                "guest_team__short_name": "MAN",
                "home_team__team_name": "Eisbären Berlin",
                "guest_team__team_name": "Adler Mannheim",
                "home_team__del_teamid": 3,
                "guest_team__del_teamid": 7,
                "no_bet": False,
                "tv": True,
                "playoff": False,
            }
        ]
        model = FakeMatchModel(rows)
        model.objects.filter = lambda **kwargs: FakeQuery(rows)
        details = mp.load_match_details(11, match_model=model)
        self.assertEqual(details.opponent_del_id, 7)
        self.assertEqual(details.home_short, "EBB")

        rows[0]["home_team__del_teamid"] = 7
        rows[0]["guest_team__del_teamid"] = 3
        details = mp.load_match_details(11, match_model=model)
        self.assertEqual(details.opponent_del_id, 7)

    def test_resolve_sides_home_and_away(self):
        home = mp.resolve_sides(1, "Eisbären Berlin", "EBB", 2, "Adler Mannheim", "MAN")
        self.assertTrue(home.ebb_is_home)
        self.assertEqual(home.match_type, "zu Hause")
        self.assertEqual(home.opponent_name, "Adler Mannheim")
        self.assertEqual(home.ebb_table_label, "Heimtabelle")

        away = mp.resolve_sides(2, "Adler Mannheim", "MAN", 1, "Eisbären Berlin", "EBB")
        self.assertFalse(away.ebb_is_home)
        self.assertEqual(away.match_type, "auswärts")
        self.assertEqual(away.opponent_name, "Adler Mannheim")
        self.assertEqual(away.ebb_table_label, "Auswärtstabelle")

    def test_format_del_table_inserts_separator_when_ranks_differ(self):
        close = mp.format_del_table(
            ranking(1, 2), "Eisbären Berlin", "Adler Mannheim"
        )
        self.assertEqual(
            close,
            "*DEL-Tabelle*\n"
            "#1 - Eisbären Berlin (10) - 20 Pkt\n"
            "#2 - Adler Mannheim (10) - 12 Pkt\n\n",
        )

        spread = mp.format_del_table(
            ranking(1, 5), "Eisbären Berlin", "Adler Mannheim"
        )
        self.assertIn("...\n#5 - Adler Mannheim", spread)
        self.assertEqual(mp.format_del_table(EMPTY_RANKING, "A", "B"), "")

    def test_format_h2h_and_recent_matches(self):
        h2h = mp.format_h2h_section(12, 7, 5, 2, 1, 1, 0)
        self.assertEqual(
            h2h,
            "Die beiden Mannschaften haben bisher 12 mal gegeneinander gespielt.\n"
            "\n*Ergebnisse aus Eisbärensicht:*\n  7 Siege\n"
            "  - 2 in OT\n"
            "  - 1 nach PS\n"
            "  5 Niederlagen\n"
            "  - 1 in OT\n",
        )

        matches = {
            10: {
                "date": 0,
                "home_team__short_name": "EBB",
                "guest_team__short_name": "MAN",
                "result": "4:2",
            },
            11: {
                "date": 86400,
                "home_team__short_name": "MAN",
                "guest_team__short_name": "EBB",
                "result": "1:3",
            },
        }
        recent = mp.format_recent_h2h_matches(matches)
        self.assertTrue(recent.startswith("\n*Ergebnisse der letzen 2 Spiele gegeneinander:*\n"))
        self.assertIn("MAN - EBB 1:3", recent)
        self.assertIn("EBB - MAN 4:2", recent)

    def test_format_opponent_recent_skips_other_seasons(self):
        sort_list = [5, 6]
        match_dic = {
            5: {
                "date": 0,
                "season_id": 14,
                "home_team__short_name": "MAN",
                "guest_team__short_name": "KEC",
                "result": "3:1",
            },
            6: {
                "date": 86400,
                "season_id": 15,
                "home_team__short_name": "STR",
                "guest_team__short_name": "MAN",
                "result": "2:2",
            },
        }
        body = mp.format_opponent_recent_matches(
            sort_list, match_dic, 15, "der", "Adler Mannheim"
        )
        self.assertIn('Ergebnisse der letzen Spiele der "Adler Mannheim"', body)
        self.assertIn("STR - MAN 2:2", body)
        self.assertNotIn("KEC", body)

        self.assertEqual(
            mp.format_opponent_recent_matches([], {}, 15, "der", "Adler Mannheim"),
            "",
        )
        other_season_only = mp.format_opponent_recent_matches(
            [5], match_dic, 15, "der", "Adler Mannheim"
        )
        self.assertEqual(other_season_only, "")

    def test_append_signature_uses_sailboat(self):
        self.assertEqual(mp.BOOT_SIGNATURE, "\N{SAILBOAT}")
        self.assertEqual(mp.append_signature("Hallo"), "Hallo\n\nEuer ⛵")

    def test_build_intro_and_no_bet_messages(self):
        no_bet = mp.build_no_bet_message("Adler Mannheim", "19:30")
        self.assertIn('gegen "Adler Mannheim"', no_bet)
        self.assertIn("kein Ligaspiel", no_bet)

        playoff = mp.build_intro_message(
            True, 1, "die", "Adler Mannheim", "19:30", "http://x/game/tip", "zu Hause", True
        )
        self.assertIn("Hurra, hurra die Playoffs sind da", playoff)
        self.assertIn("FreeTv", playoff)
        self.assertNotIn("Spieltag", playoff)

        regular = mp.build_intro_message(
            False, 3, "die", "Adler Mannheim", "19:30", "http://x/game/tip", "auswärts", False
        )
        self.assertIn("Am 3. Spieltag", regular)
        self.assertIn("auswärts", regular)
        self.assertNotIn("FreeTv", regular)

    def test_dispatch_whatsapp_and_threema_dry_run_skip_send(self):
        send_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            mp.dispatch_whatsapp(SETTINGS, "49123,49124", "hello", dry_run=True, send_fn=send_fn)
            mp.dispatch_threema(SETTINGS, "ABCDEFGH", "hello", dry_run=True, send_fn=send_fn)
        send_fn.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp 49123,49124:", printed)
        self.assertIn("dry-run threema ABCDEFGH:", printed)

        mp.dispatch_whatsapp(SETTINGS, "49123", "hello", dry_run=False, send_fn=send_fn)
        send_fn.assert_called_once_with("wa.local", 9009, "49123", "hello")

    def test_notify_recipients_live_sends_both_channels(self):
        wa_send = mock.Mock()
        tr_send = mock.Mock()
        mp.notify_recipients(
            "body",
            SETTINGS,
            dry_run=False,
            groups=["49123", "49124"],
            threema_users=["ABCDEFGH"],
            wa_send_fn=wa_send,
            threema_send_fn=tr_send,
        )
        wa_send.assert_called_once_with("wa.local", 9009, "49123,49124", "body")
        tr_send.assert_called_once_with("*ABCD", "secret", "private:key", "ABCDEFGH", "body")

    def test_notify_recipients_dry_run_prints_and_skips_send(self):
        wa_send = mock.Mock()
        tr_send = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            mp.notify_recipients(
                "body",
                SETTINGS,
                dry_run=True,
                groups=["49123"],
                threema_users=["ABCDEFGH"],
                wa_send_fn=wa_send,
                threema_send_fn=tr_send,
            )
        wa_send.assert_not_called()
        tr_send.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp 49123:", printed)
        self.assertIn("dry-run threema ABCDEFGH:", printed)
        self.assertIn("body", printed)

    def test_notify_recipients_prints_body_when_whatsapp_is_not_configured(self):
        output = io.StringIO()
        with redirect_stdout(output):
            mp.notify_recipients(
                "body",
                SimpleNamespace(),
                dry_run=False,
                groups=["49123"],
                threema_users=[],
            )
        self.assertEqual(output.getvalue(), "body\n")

    def test_build_pumpup_message_no_bet_skips_stats(self):
        details = HOME_DETAILS._replace(no_bet=True)
        collect_stats = mock.Mock()
        message = mp.build_pumpup_message(
            details,
            match_date=1758123000,
            now_uts=1758100000,
            season_id=15,
            last_match_id=10,
            url="http://x/game/tip",
            collect_stats_fn=collect_stats,
        )
        collect_stats.assert_not_called()
        self.assertIn("kein Ligaspiel", message)
        self.assertTrue(message.endswith("Euer {0}".format(mp.BOOT_SIGNATURE)))

    def test_build_pumpup_message_playoff_skips_league_table(self):
        details = HOME_DETAILS._replace(playoff=True)
        collect_stats = mock.Mock(return_value=([], {}, "der", "die"))
        ranking_fn = mock.Mock()
        message = mp.build_pumpup_message(
            details,
            match_date=1758123000,
            now_uts=1758100000,
            season_id=15,
            last_match_id=10,
            url="http://x/game/tip",
            collect_stats_fn=collect_stats,
            ranking_fn=ranking_fn,
            h2h_fn=mock.Mock(),
            last_matches_fn=mock.Mock(),
            topscorers_fn=mock.Mock(return_value=None),
        )
        ranking_fn.assert_not_called()
        self.assertIn("Playoffs", message)
        self.assertNotIn("DEL-Tabelle", message)

    def test_build_pumpup_message_regular_includes_sections(self):
        collect_stats = mock.Mock(
            return_value=(
                [20],
                {
                    20: {
                        "date": 0,
                        "season_id": 15,
                        "home_team__short_name": "MAN",
                        "guest_team__short_name": "KEC",
                        "result": "3:1",
                    }
                },
                "der",
                "die",
            )
        )
        h2h_fn = mock.Mock(return_value=(4, 3, 1, 0, 0, 0, 0))
        ranking_fn = mock.Mock(
            side_effect=[
                ranking(1, 5),
                ranking(2, None),
                ranking(None, 4),
            ]
        )
        last_matches_fn = mock.Mock(
            return_value={
                9: {
                    "date": 0,
                    "home_team__short_name": "EBB",
                    "guest_team__short_name": "MAN",
                    "result": "4:2",
                }
            }
        )
        topscorers_fn = mock.Mock(side_effect=["\n*Topscorer EBB*\n", "\n*Topscorer MAN*\n"])

        message = mp.build_pumpup_message(
            HOME_DETAILS,
            match_date=1758123000,
            now_uts=1758100000,
            season_id=15,
            last_match_id=10,
            url="http://x/game/tip",
            collect_stats_fn=collect_stats,
            h2h_fn=h2h_fn,
            ranking_fn=ranking_fn,
            last_matches_fn=last_matches_fn,
            topscorers_fn=topscorers_fn,
        )
        self.assertIn("Am 3. Spieltag", message)
        self.assertIn("DEL-Tabelle", message)
        self.assertIn("Heimtabelle", message)
        self.assertIn("Auswärtstabelle", message)
        self.assertIn("4 mal gegeneinander", message)
        self.assertIn("gegeneinander", message)
        self.assertIn("MAN - KEC 3:1", message)
        self.assertIn("Topscorer EBB", message)
        self.assertIn("Topscorer MAN", message)
        self.assertEqual(
            [call.args for call in topscorers_fn.call_args_list],
            [
                (
                    mp.EBB_TOPSCORER_YEAR,
                    mp.DEL_LEAGUE_ID,
                    mp.EBB_DEL_TEAM_ID,
                    mp.EBB_DISPLAY_NAME,
                ),
                (
                    mp.OPPONENT_TOPSCORER_YEAR,
                    mp.DEL_LEAGUE_ID,
                    7,
                    "Adler Mannheim",
                ),
            ],
        )

    def test_run_skips_send_when_match_is_outside_window(self):
        wa_send = mock.Mock()
        rc = mp.run(
            argv=[],
            now_uts=50,
            settings_obj=SETTINGS,
            next_match_fn=lambda uts, season_id: (11, 50 + mp.THRESHOLD_SECONDS + 1, False),
            last_match_fn=lambda uts, season_id: (10, 10, 2),
            simple_send_fn=wa_send,
            season_id=15,
            groups=["49123"],
            threema_users=[],
        )
        self.assertEqual(rc, mp.EXIT_SUCCESS)
        wa_send.assert_not_called()

    def test_run_dry_run_prints_and_skips_send(self):
        wa_send = mock.Mock()
        tr_send = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            rc = mp.run(
                argv=["--dry-run"],
                now_uts=50,
                settings_obj=SETTINGS,
                next_match_fn=lambda uts, season_id: (11, 80, False),
                last_match_fn=lambda uts, season_id: (10, 10, 2),
                simple_send_fn=wa_send,
                send_threema_fn=tr_send,
                season_id=15,
                match_details=HOME_DETAILS,
                groups=["49123"],
                threema_users=["ABCDEFGH"],
                collect_stats_fn=mock.Mock(return_value=([], {}, "der", "die")),
                h2h_fn=mock.Mock(return_value=(0, 0, 0, 0, 0, 0, 0)),
                ranking_fn=mock.Mock(return_value=EMPTY_RANKING),
                last_matches_fn=mock.Mock(return_value={}),
                topscorers_fn=mock.Mock(return_value=None),
            )
        self.assertEqual(rc, mp.EXIT_SUCCESS)
        wa_send.assert_not_called()
        tr_send.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp 49123:", printed)
        self.assertIn("dry-run threema ABCDEFGH:", printed)
        self.assertIn("Tippjemeinde", printed)

    def test_run_live_sends_generated_message(self):
        wa_send = mock.Mock()
        tr_send = mock.Mock()
        rc = mp.run(
            argv=[],
            now_uts=50,
            settings_obj=SETTINGS,
            next_match_fn=lambda uts, season_id: (11, 80, False),
            last_match_fn=lambda uts, season_id: (10, 10, 2),
            simple_send_fn=wa_send,
            send_threema_fn=tr_send,
            season_id=15,
            match_details=HOME_DETAILS._replace(no_bet=True),
            groups=["49123"],
            threema_users=["ABCDEFGH"],
        )
        self.assertEqual(rc, mp.EXIT_SUCCESS)
        wa_send.assert_called_once()
        self.assertEqual(wa_send.call_args[0][:3], ("wa.local", 9009, "49123"))
        self.assertIn("kein Ligaspiel", wa_send.call_args[0][3])
        tr_send.assert_called_once()

    def test_run_aborts_when_team_names_are_missing(self):
        output = io.StringIO()
        with redirect_stdout(output):
            rc = mp.run(
                argv=[],
                now_uts=50,
                settings_obj=SETTINGS,
                next_match_fn=lambda uts, season_id: (11, 80, False),
                last_match_fn=lambda uts, season_id: (10, 10, 2),
                season_id=15,
                match_details=mp.EMPTY_MATCH,
                groups=["49123"],
                threema_users=[],
            )
        self.assertEqual(rc, mp.EXIT_SUCCESS)
        self.assertIn(mp.MISSING_TEAMS_MESSAGE, output.getvalue())
