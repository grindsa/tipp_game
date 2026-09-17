import io
import os
from contextlib import redirect_stdout
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from tools import match_import as mi


class FakeDelAppHelper(object):
    def __init__(self, schedule, year=None, league_id=None, team_id=None):
        self.schedule = schedule
        self.year = year
        self.league_id = league_id
        self.team_id = team_id
        self.called_with = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def gameschedule_get(self, year, league_id, team_id):
        self.called_with = (year, league_id, team_id)
        return self.schedule


class FakeMatchManager(object):
    def __init__(self):
        self.calls = []

    def update_or_create(self, **kwargs):
        self.calls.append(kwargs)
        return (SimpleNamespace(pk=len(self.calls)), True)


class FakeMatch(object):
    def __init__(self):
        self.objects = FakeMatchManager()


def _team(team_id, team_name, short_name, del_team=True):
    return {
        "team_id": team_id,
        "team_name": team_name,
        "short_name": short_name,
        "del_team": del_team,
    }


TEAM_LIST = [
    _team(1, "Eisbaeren Berlin", "EBB"),
    _team(2, "Adler Mannheim", "MAN"),
    _team(3, "Koelner Haie", "KEC"),
]


def _match(game_id, home, guest, start_date):
    return {
        "id": game_id,
        "home": {"shortcut": home},
        "guest": {"shortcut": guest},
        "start_date": start_date,
    }


class MatchImportTests(SimpleTestCase):
    def test_parse_args_defaults(self):
        args = mi.parse_args([])
        self.assertFalse(args.debug)
        self.assertIsNone(args.season)
        self.assertIsNone(args.tournament)
        self.assertEqual(args.year, mi.DEFAULT_SEASON_YEAR)
        self.assertEqual(args.league_id, mi.DEFAULT_LEAGUE_ID)
        self.assertEqual(args.team_id, mi.DEFAULT_TEAM_ID)
        self.assertEqual(args.start_matchday, mi.DEFAULT_START_MATCHDAY)

    def test_parse_args_reads_flags(self):
        args = mi.parse_args(
            ["-d", "-s", "4", "--year", "2026", "--league-id", "1", "--team-id", "9", "--start-matchday", "10"]
        )
        self.assertTrue(args.debug)
        self.assertEqual(args.season, 4)
        self.assertEqual(args.year, 2026)
        self.assertEqual(args.league_id, 1)
        self.assertEqual(args.team_id, 9)
        self.assertEqual(args.start_matchday, 10)

    def test_parse_args_rejects_season_and_tournament_together(self):
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit):
                mi.parse_args(["-s", "1", "-t", "2"])

    def test_start_date_to_uts_handles_placeholders(self):
        self.assertIsNone(mi.start_date_to_uts(None))
        self.assertIsNone(mi.start_date_to_uts(""))
        self.assertIsNone(mi.start_date_to_uts(mi.INVALID_START_DATE))

    def test_start_date_to_uts_interprets_api_times_in_berlin(self):
        berlin = ZoneInfo("Europe/Berlin")
        naive = datetime(2025, 1, 1, 0, 0, 0)
        expected = int(naive.replace(tzinfo=berlin).timestamp())
        self.assertEqual(mi.start_date_to_uts("2025-01-01 00:00:00"), expected)
        self.assertEqual(mi.start_date_to_uts(naive), expected)

    def test_start_date_to_uts_applies_cet_and_cest(self):
        # 19:30 CEST (UTC+2) -> 17:30 UTC; 19:30 CET (UTC+1) -> 18:30 UTC.
        summer = mi.start_date_to_uts("2025-07-01 19:30:00")
        winter = mi.start_date_to_uts("2026-01-15 19:30:00")
        summer_utc = datetime.fromtimestamp(summer, tz=timezone.utc)
        winter_utc = datetime.fromtimestamp(winter, tz=timezone.utc)
        self.assertEqual((summer_utc.hour, summer_utc.minute), (17, 30))
        self.assertEqual((winter_utc.hour, winter_utc.minute), (18, 30))

        # Last Sunday of October 2025 is the 26th; last Sunday of March 2026 is the 29th.
        before_fall_back = mi.start_date_to_uts("2025-10-25 19:30:00")
        after_fall_back = mi.start_date_to_uts("2025-10-26 19:30:00")
        self.assertEqual(datetime.fromtimestamp(before_fall_back, tz=timezone.utc).hour, 17)
        self.assertEqual(datetime.fromtimestamp(after_fall_back, tz=timezone.utc).hour, 18)

        before_spring_forward = mi.start_date_to_uts("2026-03-28 19:30:00")
        after_spring_forward = mi.start_date_to_uts("2026-03-29 19:30:00")
        self.assertEqual(datetime.fromtimestamp(before_spring_forward, tz=timezone.utc).hour, 18)
        self.assertEqual(datetime.fromtimestamp(after_spring_forward, tz=timezone.utc).hour, 17)

    def test_start_date_to_uts_rejects_invalid_string(self):
        with self.assertRaises(ValueError):
            mi.start_date_to_uts("not-a-date")

    def test_lookup_team_by_short_name_and_full_name(self):
        by_short = mi.lookup_team(TEAM_LIST, "EBB")
        self.assertEqual(by_short.team_id, 1)
        self.assertEqual(by_short.short_name, "EBB")

        by_name = mi.lookup_team(TEAM_LIST, "Adler Mannheim")
        self.assertEqual(by_name.team_id, 2)
        self.assertEqual(by_name.team_name, "Adler Mannheim")

    def test_lookup_team_fuzzy_and_unresolved(self):
        fuzzy = mi.lookup_team(TEAM_LIST, "Eisbaeren")
        self.assertEqual(fuzzy.team_id, 1)

        self.assertEqual(mi.lookup_team(TEAM_LIST, "XYZ"), mi.UNRESOLVED_TEAM)
        self.assertEqual(mi.lookup_team(TEAM_LIST, None), mi.UNRESOLVED_TEAM)
        self.assertEqual(mi.lookup_team(TEAM_LIST, ""), mi.UNRESOLVED_TEAM)

    def test_lookup_team_ignores_empty_name_tokens(self):
        teams = [_team(4, "   ", "BLN")]
        self.assertEqual(mi.lookup_team(teams, "Berlin"), mi.UNRESOLVED_TEAM)

    def test_lookup_team_prefers_short_name_over_later_fuzzy_match(self):
        teams = [
            _team(10, "Berliner SC", "BSC"),
            _team(11, "Eisbaeren Berlin", "EBB"),
        ]
        self.assertEqual(mi.lookup_team(teams, "BSC").team_id, 10)

    def test_resolve_season_defaults_and_explicit_values(self):
        seasons = [{"id": 1, "tournament_id": 100}, {"id": 2, "tournament_id": 200}]
        self.assertEqual(mi.resolve_season(None, None, seasons), (2, 200))
        self.assertEqual(mi.resolve_season(1, None, seasons), (1, 100))
        self.assertEqual(mi.resolve_season(None, 999, seasons), (2, 999))

    def test_resolve_season_rejects_empty_or_out_of_range(self):
        with self.assertRaises(ValueError):
            mi.resolve_season(None, None, [])
        with self.assertRaises(ValueError):
            mi.resolve_season(9, None, [{"tournament_id": 1}])

    def test_build_match_defaults_stores_uts_as_date(self):
        defaults = mi.build_match_defaults(53, 1000, 1, 2, 7, 99)
        self.assertEqual(
            defaults,
            {
                "matchday": 53,
                "date": 1000,
                "home_team_id": 1,
                "guest_team_id": 2,
                "season_id": 7,
                "no_bet": False,
                "playoff": False,
                "delapp_game_id": 99,
            },
        )

    def test_extract_matches_handles_missing_payload(self):
        self.assertEqual(mi.extract_matches(None), [])
        self.assertEqual(mi.extract_matches({}), [])
        self.assertEqual(mi.extract_matches({"matches": [{"id": 1}]}), [{"id": 1}])

    def test_team_shortcut_reads_nested_side(self):
        match = _match(1, "EBB", "MAN", "2025-01-01 00:00:00")
        self.assertEqual(mi.team_shortcut(match, "home"), "EBB")
        self.assertEqual(mi.team_shortcut(match, "guest"), "MAN")
        self.assertIsNone(mi.team_shortcut({}, "home"))

    def test_fetch_gameschedule_forwards_helper_args(self):
        helper = FakeDelAppHelper({"matches": [{"id": 7}]})
        matches = mi.fetch_gameschedule(helper, 2026, 3, 12)
        self.assertEqual(matches, [{"id": 7}])
        self.assertEqual(helper.called_with, (2026, 3, 12))

    def test_load_seasons_and_teams_use_model_querysets(self):
        class SeasonModel(object):
            class objects(object):
                @staticmethod
                def order_by(field):
                    return SimpleNamespace(values=lambda: [{"id": 1, "sorted_by": field}])

        class TeamModel(object):
            class objects(object):
                @staticmethod
                def values(*fields):
                    return [{"fields": fields}]

        self.assertEqual(mi.load_seasons(season_model=SeasonModel), [{"id": 1, "sorted_by": "id"}])
        self.assertEqual(
            mi.load_teams(team_model=TeamModel),
            [{"fields": ("team_id", "team_name", "short_name", "del_team")}],
        )

    def test_build_upcoming_match_updates_skips_unknown_and_past_matches(self):
        now_uts = mi.start_date_to_uts("2025-09-16 19:00:00")
        matches = [
            _match(1, "UNK", "MAN", "2025-10-01 19:00:00"),
            _match(2, "EBB", "MAN", "2025-08-01 19:00:00"),
            _match(3, "EBB", "KEC", mi.INVALID_START_DATE),
            _match(4, "EBB", "MAN", "2025-10-01 19:00:00"),
        ]

        output = io.StringIO()
        with redirect_stdout(output):
            updates = mi.build_upcoming_match_updates(
                matches,
                TEAM_LIST,
                season_id=5,
                now_uts=now_uts,
                start_matchday=52,
            )

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["matchday"], 55)
        self.assertEqual(updates[0]["home_name"], "Eisbaeren Berlin")
        self.assertEqual(updates[0]["guest_name"], "Adler Mannheim")
        self.assertEqual(updates[0]["defaults"]["delapp_game_id"], 4)
        self.assertEqual(updates[0]["defaults"]["season_id"], 5)
        self.assertIn("None Adler Mannheim", output.getvalue())

    def test_build_upcoming_match_updates_includes_match_at_now(self):
        start_date = "2025-09-16 19:00:00"
        now_uts = mi.start_date_to_uts(start_date)
        matches = [_match(8, "EBB", "MAN", start_date)]

        output = io.StringIO()
        with redirect_stdout(output):
            updates = mi.build_upcoming_match_updates(matches, TEAM_LIST, season_id=1, now_uts=now_uts)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["matchday"], mi.DEFAULT_START_MATCHDAY + 1)

    def test_persist_matches_calls_update_or_create(self):
        fake_match = FakeMatch()
        updates = [
            {
                "home_name": "Eisbaeren Berlin",
                "guest_name": "Adler Mannheim",
                "matchday": 53,
                "defaults": mi.build_match_defaults(53, 1000, 1, 2, 5, 44),
            }
        ]

        output = io.StringIO()
        with redirect_stdout(output):
            saved = mi.persist_matches(updates, match_model=fake_match)

        self.assertEqual(len(saved), 1)
        self.assertEqual(len(fake_match.objects.calls), 1)
        call = fake_match.objects.calls[0]
        self.assertEqual(call["matchday"], 53)
        self.assertEqual(call["season_id"], 5)
        self.assertEqual(call["defaults"]["delapp_game_id"], 44)
        self.assertIn("update_db: Eisbaeren Berlin: Adler Mannheim", output.getvalue())

    def test_run_imports_future_matches_through_injected_dependencies(self):
        seasons = [{"id": 1, "tournament_id": 11}, {"id": 2, "tournament_id": 22}]
        helper = FakeDelAppHelper(
            {
                "matches": [
                    _match(10, "EBB", "MAN", "2025-10-01 19:00:00"),
                    _match(11, "EBB", "KEC", "2025-08-01 19:00:00"),
                ]
            }
        )
        fake_match = FakeMatch()
        now_uts = mi.start_date_to_uts("2025-09-16 19:00:00")

        output = io.StringIO()
        with redirect_stdout(output):
            imported = mi.run(
                argv=["--year", "2026", "--league-id", "8", "--team-id", "12", "--start-matchday", "40"],
                now_uts=now_uts,
                seasons=seasons,
                teams=TEAM_LIST,
                helper_factory=lambda debug, cfg_file=None: helper,
                match_model=fake_match,
            )

        self.assertEqual(imported, 1)
        self.assertEqual(helper.called_with, (2026, 8, 12))
        self.assertEqual(fake_match.objects.calls[0]["matchday"], 41)
        self.assertEqual(fake_match.objects.calls[0]["season_id"], 2)

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(mi, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = mi.main([])
        self.assertEqual(rc, mi.EXIT_RUNTIME_ERROR)
        self.assertIn("match_import failed: boom", output.getvalue())

    def test_main_reports_imported_count(self):
        with mock.patch.object(mi, "run", return_value=3):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = mi.main([])
        self.assertEqual(rc, mi.EXIT_SUCCESS)
        self.assertIn("imported 3 upcoming matches", output.getvalue())

    def test_default_config_path_uses_script_directory(self):
        path = mi.default_config_path("/tmp/tools/match_import.py")
        self.assertEqual(path, "/tmp/tools/delapphelper.cfg")

    @mock.patch.dict(os.environ, {"DELAPPHELPER_CFG": "/secret/delapphelper.cfg"}, clear=False)
    def test_default_config_path_prefers_env(self):
        self.assertEqual(mi.default_config_path("/tmp/tools/match_import.py"), "/secret/delapphelper.cfg")

    def test_create_del_app_helper_requires_config_file(self):
        with mock.patch.dict("sys.modules", {"delapphelper": mock.Mock(DelAppHelper=mock.Mock())}):
            with self.assertRaises(RuntimeError) as raised:
                mi.create_del_app_helper(False, cfg_file="/missing/delapphelper.cfg")
        self.assertIn("delapphelper config not found", str(raised.exception))

    def test_uts_now_uses_utc_timestamp(self):
        fixed = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

        class FakeDateTime(object):
            @staticmethod
            def now(tz=None):
                FakeDateTime.called_tz = tz
                return fixed

        with mock.patch.object(mi, "datetime", FakeDateTime):
            self.assertEqual(mi.uts_now(), int(fixed.timestamp()))
        self.assertEqual(FakeDateTime.called_tz, timezone.utc)
