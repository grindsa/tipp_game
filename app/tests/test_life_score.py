import io
import os
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import life_score as ls


SETTINGS = SimpleNamespace(
    WA_ADMIN_NUMBER="491700000000",
    WA_SRV="wa.local",
    WA_PORT=9009,
    TR_ID="*ABCD",
    TR_SECRET="secret",
    TR_SK="private:key",
)


def _state(**overrides):
    values = dict(
        match_id=9,
        match_date=1000,
        done=False,
        period_cnt=1,
        result="0:0",
        break_time=0,
        home_team="EBB",
        guest_team="MAN",
        home_match=True,
        ticker_id=5,
        no_bet=False,
    )
    values.update(overrides)
    return ls.MatchState(**values)


def _goal_event(event_id, game_time, berlin, opponent, player_name="Hager", player_id=None):
    entry = {
        "id": event_id,
        "updateType": "goal",
        "gameTime": game_time,
        "goals": {"berlin": berlin, "opponent": opponent},
    }
    if player_name is not None:
        entry["playerName"] = player_name
    if player_id is not None:
        entry["playerId"] = player_id
    return entry


def _period_event(event_id, period_name, game_time=1200):
    return {
        "id": event_id,
        "updateType": "periodend",
        "periodName": period_name,
        "gameTime": game_time,
    }


class LifeScoreTests(SimpleTestCase):
    def test_parse_args_defaults_and_flags(self):
        defaults = ls.parse_args([])
        self.assertFalse(defaults.debug)
        self.assertFalse(defaults.fake_breaktr)

        args = ls.parse_args(["-d", "--fake-breaktr"])
        self.assertTrue(args.debug)
        self.assertTrue(args.fake_breaktr)
        self.assertTrue(ls.parse_args(["-f"]).fake_breaktr)
        self.assertFalse(defaults.dry_run)
        self.assertFalse(defaults.reroute)
        self.assertTrue(ls.parse_args(["--dry-run"]).dry_run)
        self.assertTrue(ls.parse_args(["-r"]).reroute)
        self.assertTrue(ls.parse_args(["--reroute"]).reroute)

    def test_resolve_thresholds_for_normal_and_fake_breaktr(self):
        self.assertEqual(
            ls.resolve_thresholds(False),
            (ls.MATCH_MAX_AGE_SECONDS, ls.BREAK_DURATION_SECONDS),
        )
        self.assertEqual(
            ls.resolve_thresholds(True),
            (ls.FAKE_BREAKTR_MATCH_MAX_AGE_SECONDS, ls.FAKE_BREAKTR_BREAK_SECONDS),
        )

    def test_match_is_too_old(self):
        self.assertTrue(ls.match_is_too_old(2000, 1000, 500))
        self.assertFalse(ls.match_is_too_old(2000, 1000, 2000))
        self.assertTrue(ls.match_is_too_old(100, None, 10))

    def test_format_match_datetime(self):
        self.assertIsNone(ls.format_match_datetime(None))
        self.assertEqual(
            ls.format_match_datetime(1726644720),
            "2024-09-18 09:32",
        )

    def test_fetch_json_uses_requests(self):
        payload = {"events": []}
        response = mock.Mock()
        response.json.return_value = payload
        get_fn = mock.Mock(return_value=response)
        result = ls.fetch_json("https://example.test/ticker", get_fn=get_fn)
        get_fn.assert_called_once_with(
            "https://example.test/ticker", timeout=ls.HTTP_TIMEOUT_SECONDS
        )
        response.raise_for_status.assert_called_once()
        self.assertEqual(result, payload)

    def test_is_home_match_and_first_run_and_break(self):
        self.assertTrue(ls.is_home_match("EBB"))
        self.assertTrue(ls.is_home_match("Eisbaeren Berlin"))
        self.assertFalse(ls.is_home_match("MAN"))
        self.assertFalse(ls.is_home_match(None))
        self.assertTrue(ls.is_first_run(_state(period_cnt=0)))
        self.assertFalse(ls.is_first_run(_state(period_cnt=1)))
        self.assertTrue(ls.is_break(2))
        self.assertTrue(ls.is_break(4))
        self.assertFalse(ls.is_break(1))

    def test_split_and_format_score(self):
        self.assertEqual(ls.split_score("3:1"), (3, 1))
        self.assertEqual(ls.split_score(None), (0, 0))
        self.assertEqual(ls.split_score("bad"), (0, 0))
        self.assertEqual(ls.format_score(2, 4), "2:4")

    def test_is_single_goal_increment(self):
        self.assertTrue(ls.is_single_goal_increment("0:0", "1:0"))
        self.assertTrue(ls.is_single_goal_increment("1:0", "1:1"))
        self.assertFalse(ls.is_single_goal_increment("0:0", "2:0"))
        self.assertFalse(ls.is_single_goal_increment("1:0", "1:0"))
        self.assertFalse(ls.is_single_goal_increment("2:1", "1:1"))

    def test_period_label_from_clock(self):
        self.assertEqual(ls.period_label_from_clock("05:12"), "1. Drittel")
        self.assertEqual(ls.period_label_from_clock("20:00"), "1. Drittel")
        self.assertEqual(ls.period_label_from_clock("21:00"), "2. Drittel")
        self.assertEqual(ls.period_label_from_clock("41:00"), "3. Drittel")
        self.assertEqual(ls.period_label_from_clock("61:01"), "OT")

    def test_parse_period_number(self):
        self.assertEqual(ls.parse_period_number("1."), 1)
        self.assertEqual(ls.parse_period_number(3), 3)
        self.assertIsNone(ls.parse_period_number(None))
        self.assertIsNone(ls.parse_period_number(""))

    def test_scores_from_goal_entry_home_and_away(self):
        entry = _goal_event(1, 90, berlin=2, opponent=1)
        self.assertEqual(ls.scores_from_goal_entry(entry, True), (2, 1))
        self.assertEqual(ls.scores_from_goal_entry(entry, False), (1, 2))

    def test_clock_from_game_time(self):
        self.assertEqual(ls.clock_from_game_time(125), ("02:05", 2))
        self.assertEqual(ls.clock_from_game_time(None), ("00:00", 0))

    def test_period_from_entry(self):
        self.assertEqual(
            ls.period_from_entry(_period_event(1, "1. Drittel")),
            ("1.", "0:00"),
        )
        self.assertEqual(
            ls.period_from_entry(_period_event(1, "OT 5min")),
            ("3.", "0:00"),
        )
        self.assertEqual(
            ls.period_from_entry({"headline": "Spielende"}),
            ("3.", "0:00"),
        )
        self.assertEqual(ls.period_from_entry({"updateType": "shot"}), (None, None))

    def test_sort_ticker_events(self):
        events = [{"id": 3}, {"id": 1}, {"id": 2}]
        self.assertEqual([item["id"] for item in ls.sort_ticker_events(events)], [1, 2, 3])
        self.assertEqual(ls.sort_ticker_events(None), [])

    def test_how_to_smile_home_and_away(self):
        home_goal = ls.how_to_smile(1, 0, "0:0", True)
        self.assertIn("\U0001f604", home_goal)
        away_goal_against = ls.how_to_smile(0, 1, "0:0", True)
        self.assertIn("\U0001f4a9", away_goal_against)
        road_ebb_goal = ls.how_to_smile(0, 1, "0:0", False)
        self.assertIn("\U0001f604", road_ebb_goal)
        self.assertIsNone(ls.how_to_smile(1, 1, "1:1", True))

    def test_classify_user_tips(self):
        tips = [
            {"user__username": "alice", "tip": "3:1"},
            {"user__username": "bob", "tip": "0:0"},
            {"user__username": "cara", "tip": "bad"},
        ]
        yao, yai = ls.classify_user_tips(tips, 1, 0)
        self.assertEqual(yao, {"bob": "0:0"})
        self.assertEqual(yai, {"alice": "3:1"})

    def test_append_yao_whatsapp_variants(self):
        header = "Tor: 2:0\n"
        self.assertIn("Alle sind raus", ls.append_yao_whatsapp(header, "G", {"a": "1:0"}, {}))
        both_out = ls.append_yao_whatsapp(header, "G", {"a": "0:0", "b": "1:0"}, {"c": "3:0"})
        self.assertIn("Alle sind raus bis auf", both_out)
        self.assertIn("c: 3:0", both_out)
        listed = ls.append_yao_whatsapp(header, "G", {"a": "0:0"}, {"b": "3:0", "c": "2:1"})
        self.assertIn('Gruppe "G"', listed)
        self.assertIn("a: 0:0", listed)

    def test_period_transition_covers_period_and_game_end(self):
        defaults, message, stats = ls.period_transition(1, "1.", "0:00", 1, 0, 0, 2000, 1000)
        self.assertEqual(defaults["period_cnt"], 2)
        self.assertEqual(defaults["break_time"], 2000)
        self.assertIn("1. Drittel beendet", message)
        self.assertTrue(stats)

        defaults, message, stats = ls.period_transition(2, None, None, 1, 0, 900, 2000, 1000)
        self.assertEqual(defaults, {"period_cnt": 3})
        self.assertEqual(message, "2. Drittel beginnt")
        self.assertFalse(stats)

        defaults, message, _stats = ls.period_transition(5, "3.", "0:00", 2, 2, 0, 0, 1000)
        self.assertEqual(defaults, {"period_cnt": 6})
        self.assertIn("3. Drittel beendet", message)

        defaults, message, _stats = ls.period_transition(5, "3.", "0:00", 3, 2, 0, 0, 1000)
        self.assertTrue(defaults["done"])
        self.assertEqual(defaults["period_cnt"], 8)
        self.assertIn("Spielende", message)

        defaults, message, _stats = ls.period_transition(1, "1.", "05:00", 1, 0, 0, 0, 1000)
        self.assertIsNone(defaults)
        self.assertIsNone(message)

    def test_get_score_from_json_reads_new_goal_and_updates_cursor(self):
        payload = {
            "events": [
                _goal_event(4, 80, 0, 0, player_name="Old"),
                _goal_event(6, 125, 1, 0, player_name="Hager"),
            ]
        }
        updates = []

        def update_match(_match_id, **defaults):
            updates.append(defaults)

        result = ls.get_score_from_json(
            False,
            9,
            5,
            True,
            "0:0",
            fetch_json_fn=lambda _url: payload,
            update_match_fn=update_match,
        )
        self.assertEqual(result.score, "1:0")
        self.assertEqual(result.scorer_name, "Hager")
        self.assertEqual(result.score_time, "02:05")
        self.assertEqual(updates[-1]["last_ebbticker_id"], 6)

    def test_get_score_from_json_reads_period_end(self):
        payload = {"events": [_period_event(8, "1. Drittel", 1200)]}
        result = ls.get_score_from_json(
            False,
            9,
            5,
            True,
            "1:0",
            fetch_json_fn=lambda _url: payload,
            update_match_fn=mock.Mock(),
        )
        self.assertEqual(result.period_num, "1.")
        self.assertEqual(result.remaining_time, "0:00")
        self.assertEqual(result.score, "1:0")

    def test_store_goal_normalizes_clock_and_returns_text(self):
        saved = {}

        class FakeGoal(object):
            class objects(object):
                @staticmethod
                def update_or_create(**kwargs):
                    saved.update(kwargs)
                    return (object(), True)

        text = ls.store_goal(9, "1:0", "Hager", "12", "1. Drittel", goal_model=FakeGoal)
        self.assertEqual(text, "Hager 12:00\n")
        self.assertEqual(saved["defaults"]["time"], "12:00")
        self.assertEqual(saved["defaults"]["period"], "1. Drittel")

    def test_apply_goal_update_sends_for_single_goal(self):
        send_yao = mock.Mock()
        update_match = mock.Mock()
        update = ls.TickerUpdate(1, 0, "Hager", "05:00", "1:0", None, None)
        with mock.patch.object(ls, "store_goal", return_value="Hager 05:00\n") as store:
            sent = ls.apply_goal_update(
                False, _state(), update, send_yao_fn=send_yao, update_match_fn=update_match
            )
        self.assertTrue(sent)
        store.assert_called_once()
        update_match.assert_called_once_with(9, result="1:0")
        send_yao.assert_called_once()
        self.assertIn("\U0001f604", send_yao.call_args.args[4])

    def test_apply_goal_update_ignores_impossible_jump(self):
        send_yao = mock.Mock()
        update = ls.TickerUpdate(3, 0, "Hager", "05:00", "3:0", None, None)
        sent = ls.apply_goal_update(
            False, _state(), update, send_yao_fn=send_yao, update_match_fn=mock.Mock()
        )
        self.assertFalse(sent)
        send_yao.assert_not_called()

    def test_check_report_period_updates_and_alerts(self):
        update_match = mock.Mock()
        send_alert = mock.Mock()
        ls.check_report_period(
            False,
            1,
            9,
            "1.",
            "0:00",
            1,
            0,
            0,
            2000,
            1000,
            update_match_fn=update_match,
            send_alert_fn=send_alert,
            stats_fn=lambda *_args: None,
        )
        update_match.assert_called_once_with(9, period_cnt=2, break_time=2000)
        send_alert.assert_called_once()
        self.assertIn("1. Drittel beendet", send_alert.call_args.args[1])

    def test_get_gamestat_text_formats_stats_and_handles_missing_helper(self):
        stats = {
            "homeTeam": "EBB",
            "guestTeam": "MAN",
            "homeSog": 10,
            "guestSog": 8,
            "homeBully": 12,
            "guestBully": 9,
            "homePim": 4,
            "guestPim": 6,
        }
        text = ls.get_gamestat_text(9, stats_fn=lambda *_args: stats)
        self.assertIn("Torschüsse: 10 / 8", text)
        self.assertIsNone(ls.get_gamestat_text(9, stats_fn=lambda *_args: None))
        self.assertIsNone(ls.get_gamestat_text(9))

    def test_run_skips_old_and_finished_matches(self):
        rc = ls.run(
            now_uts=1000 + ls.MATCH_MAX_AGE_SECONDS + 10,
            season_id=1,
            last_match_fn=lambda *_args: (9, 1000, 1),
            load_state_fn=mock.Mock(side_effect=AssertionError("should not load")),
        )
        self.assertEqual(rc, ls.EXIT_SUCCESS)

        rc = ls.run(
            now_uts=1100,
            season_id=1,
            last_match_fn=lambda *_args: (9, 1000, 1),
            load_state_fn=lambda *_args: _state(done=True),
            fetch_ticker_fn=mock.Mock(side_effect=AssertionError("should not fetch")),
        )
        self.assertEqual(rc, ls.EXIT_SUCCESS)

    def test_run_initializes_first_poll_and_notifies_no_bet(self):
        send_yao = mock.Mock()
        update_match = mock.Mock()
        fetch_players = mock.Mock()
        rc = ls.run(
            now_uts=1100,
            season_id=1,
            last_match_fn=lambda *_args: (9, 1000, 1),
            load_state_fn=lambda *_args: _state(period_cnt=0, ticker_id=0, no_bet=True),
            fetch_players_fn=fetch_players,
            update_match_fn=update_match,
            send_yao_fn=send_yao,
            check_period_fn=mock.Mock(),
        )
        self.assertEqual(rc, ls.EXIT_SUCCESS)
        fetch_players.assert_called_once()
        update_match.assert_called_once_with(9, result="0:0", period_cnt=1)
        send_yao.assert_called_once()
        self.assertTrue(send_yao.call_args.kwargs.get("match_start") or send_yao.call_args.args[5])

    def test_run_fetches_json_score_outside_break(self):
        send_yao = mock.Mock()
        update_match = mock.Mock()
        check_period = mock.Mock()
        ticker = ls.TickerUpdate(1, 0, "Hager", "05:00", "1:0", None, None)
        fetch_ticker = mock.Mock(return_value=ticker)
        with mock.patch.object(ls, "store_goal", return_value="Hager 05:00\n"):
            ls.run(
                now_uts=1100,
                season_id=1,
                last_match_fn=lambda *_args: (9, 1000, 1),
                load_state_fn=lambda *_args: _state(period_cnt=1, result="0:0"),
                fetch_ticker_fn=fetch_ticker,
                update_match_fn=update_match,
                send_yao_fn=send_yao,
                check_period_fn=check_period,
            )
        fetch_ticker.assert_called_once()
        update_match.assert_called_with(9, result="1:0")
        send_yao.assert_called_once()
        check_period.assert_called_once()

    def test_run_skips_json_fetch_during_break(self):
        fetch_ticker = mock.Mock()
        check_period = mock.Mock()
        ls.run(
            fake_breaktr=True,
            now_uts=1100,
            season_id=1,
            last_match_fn=lambda *_args: (9, 1000, 1),
            load_state_fn=lambda *_args: _state(period_cnt=2, result="1:0", break_time=2000),
            fetch_ticker_fn=fetch_ticker,
            update_match_fn=mock.Mock(),
            send_yao_fn=mock.Mock(),
            check_period_fn=check_period,
        )
        fetch_ticker.assert_not_called()
        args = check_period.call_args.args
        self.assertEqual(args[5], 1)
        self.assertEqual(args[6], 0)

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(ls, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = ls.main(["--debug"])
        self.assertEqual(rc, ls.EXIT_RUNTIME_ERROR)
        self.assertIn("life_score failed: boom", output.getvalue())

    def test_main_passes_flags(self):
        with mock.patch.object(ls, "run", return_value=ls.EXIT_SUCCESS) as run_fn:
            self.assertEqual(ls.main([]), ls.EXIT_SUCCESS)
            run_fn.assert_called_once_with(
                debug=False, fake_breaktr=False, dry_run=False, reroute=False
            )
        with mock.patch.object(ls, "run", return_value=ls.EXIT_SUCCESS) as run_fn:
            self.assertEqual(ls.main(["-d", "--dry-run", "-f"]), ls.EXIT_SUCCESS)
            run_fn.assert_called_once_with(
                debug=True, fake_breaktr=True, dry_run=True, reroute=False
            )
        with mock.patch.object(ls, "run", return_value=ls.EXIT_SUCCESS) as run_fn:
            self.assertEqual(ls.main(["-r"]), ls.EXIT_SUCCESS)
            run_fn.assert_called_once_with(
                debug=False, fake_breaktr=False, dry_run=False, reroute=True
            )

    def test_dispatch_whatsapp_and_threema_dry_run_skip_send(self):
        send_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            ls.dispatch_whatsapp(SETTINGS, "111", "hello", dry_run=True, send_fn=send_fn)
            ls.dispatch_threema(SETTINGS, "DBUF47V8", "hello", dry_run=True, send_fn=send_fn)
        send_fn.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp 111:", printed)
        self.assertIn("dry-run threema DBUF47V8:", printed)

        ls.dispatch_whatsapp(SETTINGS, "111", "hello", dry_run=False, send_fn=send_fn)
        send_fn.assert_called_once_with("wa.local", 9009, "111", "hello")

    def test_send_yao_dry_run_prints_and_skips_send(self):
        class FakeQuerySet(object):
            def __init__(self, rows):
                self.rows = list(rows)

            def filter(self, **_kwargs):
                return self

            def values(self, *_args, **_kwargs):
                return list(self.rows)

            def values_list(self, *_args, **_kwargs):
                if _args:
                    key = _args[0]
                    return [
                        row[key] if isinstance(row, dict) else row for row in self.rows
                    ]
                return list(self.rows)

        class FakeModel(object):
            def __init__(self, rows):
                self.objects = FakeQuerySet(rows)

        wa_send = mock.Mock()
        tr_send = mock.Mock()
        sleep_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            ls.send_yao(
                None,
                0,
                0,
                9,
                None,
                match_start=True,
                settings_obj=SETTINGS,
                group_model=FakeModel(
                    [
                        {
                            "number": "111",
                            "group_id": 1,
                            "group__name": "tipp",
                            "yao_message": False,
                            "alert": True,
                        }
                    ]
                ),
                user_model=FakeModel([{"username": "alice", "id": 1}]),
                usersetting_model=FakeModel(["DBUF47V8"]),
                tip_model=FakeModel([]),
                wa_send_fn=wa_send,
                threema_send_fn=tr_send,
                sleep_fn=sleep_fn,
                dry_run=True,
            )
        wa_send.assert_not_called()
        tr_send.assert_not_called()
        sleep_fn.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp 111:", printed)
        self.assertIn("Das Spiel hat begonnen", printed)
        self.assertIn("dry-run threema DBUF47V8:", printed)

    def test_send_yao_reroute_sends_to_admin_number(self):
        class FakeQuerySet(object):
            def __init__(self, rows):
                self.rows = list(rows)

            def filter(self, **_kwargs):
                return self

            def values(self, *_args, **_kwargs):
                return list(self.rows)

            def values_list(self, *_args, **_kwargs):
                if _args:
                    key = _args[0]
                    return [
                        row[key] if isinstance(row, dict) else row for row in self.rows
                    ]
                return list(self.rows)

        class FakeModel(object):
            def __init__(self, rows):
                self.objects = FakeQuerySet(rows)

        wa_send = mock.Mock()
        tr_send = mock.Mock()
        with mock.patch.dict(os.environ, {"WA_ADMIN_NUMBER": ""}, clear=False):
            ls.send_yao(
                None,
                0,
                0,
                9,
                None,
                match_start=True,
                settings_obj=SETTINGS,
                group_model=FakeModel(
                    [
                        {
                            "number": "111",
                            "group_id": 1,
                            "group__name": "tipp",
                            "yao_message": False,
                            "alert": True,
                        }
                    ]
                ),
                user_model=FakeModel([{"username": "alice", "id": 1}]),
                usersetting_model=FakeModel(["DBUF47V8"]),
                tip_model=FakeModel([]),
                wa_send_fn=wa_send,
                threema_send_fn=tr_send,
                sleep_fn=mock.Mock(),
                reroute=True,
            )
        wa_send.assert_called_once_with("wa.local", 9009, SETTINGS.WA_ADMIN_NUMBER, mock.ANY)
        tr_send.assert_called_once()

    def test_send_alert_dry_run_prints_and_skips_send(self):
        class FakeQuerySet(object):
            def __init__(self, rows):
                self.rows = list(rows)

            def filter(self, **_kwargs):
                return self

            def values(self, *_args, **_kwargs):
                return list(self.rows)

            def values_list(self, *_args, **_kwargs):
                if _args:
                    key = _args[0]
                    return [
                        row[key] if isinstance(row, dict) else row for row in self.rows
                    ]
                return list(self.rows)

            def __getitem__(self, key):
                return self.rows[key]

        class FakeModel(object):
            def __init__(self, rows):
                self.objects = FakeQuerySet(rows)

        wa_send = mock.Mock()
        tr_send = mock.Mock()
        sleep_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            ls.send_alert(
                9,
                "1. Drittel beendet. Zwischenstand: 1:0",
                "1:0",
                settings_obj=SETTINGS,
                group_model=FakeModel(
                    [
                        {
                            "number": "111",
                            "group_id": 1,
                            "group__name": "tipp",
                            "alert": True,
                        }
                    ]
                ),
                user_model=FakeModel([{"username": "alice", "id": 1}]),
                usersetting_model=FakeModel(["DBUF47V8"]),
                tip_model=FakeModel([]),
                match_model=FakeModel([{"no_bet": False}]),
                wa_send_fn=wa_send,
                threema_send_fn=tr_send,
                sleep_fn=sleep_fn,
                dry_run=True,
            )
        wa_send.assert_not_called()
        tr_send.assert_not_called()
        sleep_fn.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp 111:", printed)
        self.assertIn("1. Drittel beendet", printed)
        self.assertIn("dry-run threema DBUF47V8:", printed)

    def test_send_alert_reroute_sends_to_admin_number(self):
        class FakeQuerySet(object):
            def __init__(self, rows):
                self.rows = list(rows)

            def filter(self, **_kwargs):
                return self

            def values(self, *_args, **_kwargs):
                return list(self.rows)

            def values_list(self, *_args, **_kwargs):
                if _args:
                    key = _args[0]
                    return [
                        row[key] if isinstance(row, dict) else row for row in self.rows
                    ]
                return list(self.rows)

            def __getitem__(self, key):
                return self.rows[key]

        class FakeModel(object):
            def __init__(self, rows):
                self.objects = FakeQuerySet(rows)

        wa_send = mock.Mock()
        tr_send = mock.Mock()
        with mock.patch.dict(os.environ, {"WA_ADMIN_NUMBER": "499988877766"}, clear=False):
            ls.send_alert(
                9,
                "1. Drittel beendet. Zwischenstand: 1:0",
                "1:0",
                settings_obj=SETTINGS,
                group_model=FakeModel(
                    [
                        {
                            "number": "111",
                            "group_id": 1,
                            "group__name": "tipp",
                            "alert": True,
                        }
                    ]
                ),
                user_model=FakeModel([{"username": "alice", "id": 1}]),
                usersetting_model=FakeModel(["DBUF47V8"]),
                tip_model=FakeModel([]),
                match_model=FakeModel([{"no_bet": False}]),
                wa_send_fn=wa_send,
                threema_send_fn=tr_send,
                sleep_fn=mock.Mock(),
                reroute=True,
            )
        wa_send.assert_called_once_with("wa.local", 9009, "499988877766", mock.ANY)
        tr_send.assert_called_once()

    def test_resolve_whatsapp_recipient_requires_admin_number(self):
        incomplete = SimpleNamespace(WA_SRV="wa.local", WA_PORT=9009)
        with mock.patch.dict(os.environ, {"WA_ADMIN_NUMBER": ""}, clear=False):
            with self.assertRaises(RuntimeError) as raised:
                ls.resolve_whatsapp_recipient(incomplete, "111", reroute=True)
        self.assertIn("WA_ADMIN_NUMBER", str(raised.exception))
        self.assertEqual(
            ls.resolve_whatsapp_recipient(SETTINGS, "+111", reroute=False),
            "111",
        )

    def test_build_endgame_ranking_appends_points(self):
        users = [{"username": "alice"}, {"username": "bob"}]
        tip_dic = {"alice": "1:0"}
        score_list = [{"p_winloss": 1, "p_diff": 2, "p_tipp": 4, "p_7vs2": 7, "p_notip": 0}]
        message = ls.build_endgame_ranking(
            "Spielende. Endstand: 1:0", users, tip_dic, "1:0", score_list, False
        )
        self.assertIn("*Punktevergabe:*", message)
        self.assertIn("alice:", message)
        self.assertIn("bob: 0 (-)", message)
        skipped = ls.build_endgame_ranking(
            "Spielende. Endstand: 1:0", users, tip_dic, "1:0", score_list, True
        )
        self.assertNotIn("Punktevergabe", skipped)
