import io
import os
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import get_lineup as gl


SETTINGS = SimpleNamespace(
    WA_ADMIN_NUMBER="491700000000",
    WA_SRV="wa.local",
    WA_PORT=9009,
    TR_ID="*ABCD",
    TR_SECRET="secret",
    TR_SK="private:key",
)


class FakeQuerySet(object):
    def __init__(self, rows, exists=None):
        self.rows = list(rows)
        self._exists = exists if exists is not None else bool(self.rows)

    def filter(self, **_kwargs):
        return self

    def values(self, *_args, **_kwargs):
        return self

    def values_list(self, *_args, **_kwargs):
        return list(self.rows)

    def exists(self):
        return self._exists

    def update_or_create(self, **kwargs):
        self.rows.append(kwargs)
        return (object(), True)

    def create(self, **kwargs):
        obj = SimpleNamespace(id=len(self.rows) + 1, **kwargs)
        self.rows.append(obj)
        return obj

    def __getitem__(self, key):
        return self.rows[key]

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)


class FakeModel(object):
    def __init__(self, rows=None, exists=None):
        self.objects = FakeQuerySet(rows or [], exists=exists)


class FakeDelAppHelper(object):
    def __init__(
        self,
        lineup="EBB lineup",
        guest_lineup="MAN lineup",
        raw_json=None,
        refs=None,
        ref_dic=None,
    ):
        self.lineup = lineup
        self.guest_lineup = guest_lineup
        self.raw_json = raw_json if raw_json is not None else [{"homePlayerMemberId": 1}]
        self.refs = refs if refs is not None else ["Rene Scholz", "Lukas Kohl"]
        self.ref_dic = ref_dic if ref_dic is not None else {
            "headReferee1": {"name": "Rene Scholz"},
            "headReferee2": {"name": "Lukas Kohl"},
        }
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def lineup_format(self, game_id, home_match):
        self.calls.append(("lineup_format", game_id, home_match))
        if home_match:
            return self.lineup, self.raw_json
        return self.guest_lineup, self.raw_json

    def reflist_get(self, game_id):
        self.calls.append(("reflist_get", game_id))
        return self.refs, self.ref_dic


class GetLineupTests(SimpleTestCase):
    def test_parse_args_defaults_and_debug(self):
        defaults = gl.parse_args([])
        self.assertFalse(defaults.debug)
        self.assertFalse(defaults.dry_run)
        self.assertFalse(defaults.reroute)
        self.assertFalse(defaults.ignore_existing)
        self.assertTrue(gl.parse_args(["-d"]).debug)
        self.assertTrue(gl.parse_args(["--debug"]).debug)
        self.assertTrue(gl.parse_args(["--dry-run"]).dry_run)
        self.assertTrue(gl.parse_args(["-r"]).reroute)
        self.assertTrue(gl.parse_args(["--reroute"]).reroute)
        self.assertTrue(gl.parse_args(["-i"]).ignore_existing)
        self.assertTrue(gl.parse_args(["--ignore-existing"]).ignore_existing)

    def test_select_current_match_prefers_closer_kickoff(self):
        now_uts = 1000
        next_match = (2, 1300, False)
        last_match = (1, 900, 3)
        match_id, match_date = gl.select_current_match(
            now_uts, next_match, last_match, debug=False
        )
        self.assertEqual((match_id, match_date), (1, 900))

        match_id, match_date = gl.select_current_match(
            now_uts, (2, 1100, False), last_match, debug=False
        )
        self.assertEqual((match_id, match_date), (2, 1100))

    def test_load_match_game_detects_home_and_missing(self):
        model = FakeModel(
            [{"delapp_game_id": "77", "home_team__short_name": "EBB"}]
        )
        self.assertEqual(gl.load_match_game(9, match_model=model), (77, True))

        away = FakeModel(
            [{"delapp_game_id": 12, "home_team__short_name": "MAN"}]
        )
        self.assertEqual(gl.load_match_game(9, match_model=away), (12, False))
        self.assertEqual(gl.load_match_game(None), (0, False))
        self.assertEqual(gl.load_match_game(9, match_model=FakeModel([])), (0, False))
        missing_id = FakeModel(
            [{"delapp_game_id": None, "home_team__short_name": "EBB"}]
        )
        self.assertEqual(gl.load_match_game(9, match_model=missing_id), (0, False))

    def test_referee_name_matching_and_create(self):
        self.assertEqual(gl.referee_search_name("Rene Scholz"), "Scholz")
        self.assertEqual(gl.referee_search_name("Scholz"), "Scholz")
        self.assertEqual(gl.referee_search_name(""), "")
        rows = [{"id": 4, "name": "Andre Schrader"}]
        self.assertEqual(gl.match_existing_referee("Rene Schrader", rows), 4)
        self.assertIsNone(gl.match_existing_referee("Lukas Kohl", rows))

        created = []

        def create_fn(name):
            created.append(name)
            return 99

        ids = gl.resolve_referee_ids(
            ["Rene Schrader", "Lukas Kohl"], rows, create_fn=create_fn
        )
        self.assertEqual(ids, [4, 99])
        self.assertEqual(created, ["Lukas Kohl"])

    def test_head_referee_names_uses_both_officials(self):
        self.assertEqual(
            gl.head_referee_names(
                {
                    "headReferee1": {"name": "Rene Scholz"},
                    "headReferee2": {"name": "Lukas Kohl"},
                }
            ),
            ["Rene Scholz", "Lukas Kohl"],
        )
        self.assertIsNone(gl.head_referee_names({"headReferee1": {"name": "A"}}))
        self.assertIsNone(gl.head_referee_names(None))

    def test_format_and_merge_announcement(self):
        refs = gl.format_referee_message(["Rene Scholz", "Lukas Kohl"])
        self.assertTrue(refs.startswith(gl.REFEREE_INTRO))
        self.assertIn("Rene Scholz\n", refs)
        self.assertIsNone(gl.format_referee_message([]))

        self.assertEqual(gl.merge_announcement("L", "R"), "L\nR")
        self.assertEqual(gl.merge_announcement(None, "R"), "R")
        self.assertEqual(gl.merge_announcement("L", None), "L")
        self.assertEqual(gl.merge_announcement("", "R"), "R")
        self.assertEqual(
            gl.format_outgoing_message("body"),
            "Liebe Tippjemeinde\n\nbody",
        )

    def test_fetch_lineup_message_skips_when_stored(self):
        helper = FakeDelAppHelper()
        stored = FakeModel(exists=True)
        self.assertIsNone(
            gl.fetch_lineup_message(False, helper, 77, True, 9, lineup_model=stored)
        )
        self.assertEqual(helper.calls, [])

    def test_fetch_lineup_message_ignore_existing_fetches_when_stored(self):
        helper = FakeDelAppHelper(lineup="EBB XI", guest_lineup="MAN XI")
        stored = FakeModel(exists=True)
        message = gl.fetch_lineup_message(
            False,
            helper,
            77,
            True,
            9,
            lineup_model=stored,
            ignore_existing=True,
        )
        self.assertIn("EBB XI", message)
        self.assertIn("MAN XI", message)
        self.assertEqual(
            helper.calls,
            [("lineup_format", 77, True), ("lineup_format", 77, False)],
        )

    def test_fetch_lineup_message_stores_home_and_guest(self):
        helper = FakeDelAppHelper(lineup="EBB XI", guest_lineup="MAN XI")
        lineup_model = FakeModel(exists=False)
        message = gl.fetch_lineup_message(
            False, helper, 77, True, 9, lineup_model=lineup_model
        )
        self.assertIn(gl.LINEUP_INTRO, message)
        self.assertIn("EBB XI", message)
        self.assertIn(gl.GUEST_LINEUP_INTRO, message)
        self.assertIn("MAN XI", message)
        self.assertEqual(
            helper.calls,
            [("lineup_format", 77, True), ("lineup_format", 77, False)],
        )
        self.assertEqual(lineup_model.objects.rows[0]["match_id"], 9)
        self.assertEqual(lineup_model.objects.rows[0]["defaults"]["lineup"], "EBB XI")

    def test_fetch_lineup_message_keeps_home_when_guest_fails(self):
        helper = FakeDelAppHelper(lineup="EBB XI", guest_lineup="MAN XI")
        original_format = helper.lineup_format

        def failing_guest(game_id, home_match):
            if not home_match:
                raise TypeError(
                    "lineup_format() takes from 1 to 3 positional arguments but 4 were given"
                )
            return original_format(game_id, home_match)

        helper.lineup_format = failing_guest
        message = gl.fetch_lineup_message(
            False, helper, 77, True, 9, lineup_model=FakeModel(exists=False)
        )
        self.assertIn("EBB XI", message)
        self.assertNotIn(gl.GUEST_LINEUP_INTRO, message)
        self.assertNotIn("MAN XI", message)

    def test_fetch_lineup_message_returns_empty_when_del_has_none(self):
        helper = FakeDelAppHelper(lineup="", guest_lineup="")
        lineup_model = FakeModel(exists=False)
        self.assertEqual(
            gl.fetch_lineup_message(False, helper, 77, True, 9, lineup_model=lineup_model),
            "",
        )
        self.assertEqual(lineup_model.objects.rows, [])

    def test_fetch_referee_message_stores_both_head_refs(self):
        helper = FakeDelAppHelper()
        referee_model = FakeModel([{"id": 1, "name": "Andre Scholz"}])
        refpermatch_model = FakeModel(exists=False)
        message = gl.fetch_referee_message(
            False,
            helper,
            77,
            9,
            referee_model=referee_model,
            refpermatch_model=refpermatch_model,
        )
        self.assertIn("Rene Scholz", message)
        saved = refpermatch_model.objects.rows[0]
        self.assertEqual(saved["match_id"], 9)
        self.assertEqual(saved["defaults"]["r1_id"], 1)
        self.assertEqual(saved["defaults"]["r2_id"], 2)

    def test_fetch_referee_message_skips_when_stored(self):
        helper = FakeDelAppHelper()
        self.assertIsNone(
            gl.fetch_referee_message(
                False,
                helper,
                77,
                9,
                refpermatch_model=FakeModel(exists=True),
            )
        )
        self.assertEqual(helper.calls, [])

    def test_fetch_referee_message_ignore_existing_fetches_when_stored(self):
        helper = FakeDelAppHelper()
        referee_model = FakeModel([{"id": 1, "name": "Andre Scholz"}])
        refpermatch_model = FakeModel(exists=True)
        message = gl.fetch_referee_message(
            False,
            helper,
            77,
            9,
            referee_model=referee_model,
            refpermatch_model=refpermatch_model,
            ignore_existing=True,
        )
        self.assertIn("Rene Scholz", message)
        self.assertEqual(helper.calls, [("reflist_get", 77)])

    def test_notify_recipients_reroute_sends_to_admin_number(self):
        wa_calls = []
        threema_calls = []
        with mock.patch.dict(os.environ, {"WA_ADMIN_NUMBER": ""}, clear=False):
            sent = gl.notify_recipients(
                "Aufstellung",
                SETTINGS,
                groups=["111", "222"],
                threema_users=["DBUF47V8"],
                wa_send_fn=lambda *args: wa_calls.append(args),
                threema_send_fn=lambda *args: threema_calls.append(args),
                reroute=True,
            )
        self.assertTrue(sent)
        self.assertEqual(wa_calls[0][2], SETTINGS.WA_ADMIN_NUMBER)
        self.assertEqual(threema_calls[0][3], "DBUF47V8")

    @mock.patch.dict(os.environ, {"WA_ADMIN_NUMBER": "499988877766"}, clear=False)
    def test_notify_recipients_reroute_prefers_env_admin_number(self):
        wa_calls = []
        sent = gl.notify_recipients(
            "Aufstellung",
            SETTINGS,
            groups=["111"],
            threema_users=[],
            wa_send_fn=lambda *args: wa_calls.append(args),
            reroute=True,
        )
        self.assertTrue(sent)
        self.assertEqual(wa_calls[0][2], "499988877766")

    def test_notify_recipients_reroute_requires_admin_number(self):
        incomplete = SimpleNamespace(WA_SRV="wa.local", WA_PORT=9009)
        with mock.patch.dict(os.environ, {"WA_ADMIN_NUMBER": ""}, clear=False):
            with self.assertRaises(RuntimeError) as raised:
                gl.notify_recipients(
                    "body",
                    incomplete,
                    dry_run=True,
                    groups=["111"],
                    threema_users=[],
                    reroute=True,
                )
        self.assertIn("WA_ADMIN_NUMBER", str(raised.exception))

    def test_notify_recipients_sends_whatsapp_and_threema(self):
        wa_calls = []
        threema_calls = []
        sent = gl.notify_recipients(
            "Aufstellung",
            SETTINGS,
            groups=["111", "222"],
            threema_users=["DBUF47V8"],
            wa_send_fn=lambda *args: wa_calls.append(args),
            threema_send_fn=lambda *args: threema_calls.append(args),
        )
        self.assertTrue(sent)
        self.assertEqual(wa_calls[0][0], "wa.local")
        self.assertEqual(wa_calls[0][2], "111,222")
        self.assertIn("Liebe Tippjemeinde", wa_calls[0][3])
        self.assertEqual(threema_calls[0][3], "DBUF47V8")

    def test_notify_recipients_dry_run_prints_and_skips_send(self):
        wa_calls = []
        threema_calls = []
        output = io.StringIO()
        with redirect_stdout(output):
            sent = gl.notify_recipients(
                "Aufstellung",
                SETTINGS,
                dry_run=True,
                groups=["111"],
                threema_users=["DBUF47V8"],
                wa_send_fn=lambda *args: wa_calls.append(args),
                threema_send_fn=lambda *args: threema_calls.append(args),
            )
        self.assertTrue(sent)
        self.assertEqual(wa_calls, [])
        self.assertEqual(threema_calls, [])
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp 111:", printed)
        self.assertIn("dry-run threema DBUF47V8:", printed)
        self.assertIn("Liebe Tippjemeinde", printed)

    def test_notify_recipients_requires_admin_gate_and_body(self):
        wa_calls = []
        incomplete = SimpleNamespace(WA_SRV="wa.local", WA_PORT=9009)
        self.assertFalse(
            gl.notify_recipients(
                "body", incomplete, groups=["111"], wa_send_fn=lambda *args: wa_calls.append(args)
            )
        )
        self.assertFalse(
            gl.notify_recipients("", SETTINGS, groups=["111"], wa_send_fn=lambda *args: wa_calls.append(args))
        )
        self.assertEqual(wa_calls, [])

    def test_run_skips_when_game_id_missing(self):
        notify = mock.Mock()
        rc = gl.run(
            now_uts=1000,
            season_id=1,
            next_match_fn=lambda *_args: (9, 1100, False),
            last_match_fn=lambda *_args: (8, 900, 1),
            load_game_fn=lambda *_args: (0, False),
            notify_fn=notify,
        )
        self.assertEqual(rc, gl.EXIT_SUCCESS)
        notify.assert_not_called()

    def test_run_fetches_and_notifies(self):
        helper = FakeDelAppHelper()
        notify = mock.Mock()
        fetch_lineup = mock.Mock(return_value="LINEUP")
        fetch_refs = mock.Mock(return_value="REFS")
        rc = gl.run(
            debug=False,
            now_uts=1000,
            season_id=1,
            next_match_fn=lambda *_args: (9, 1100, False),
            last_match_fn=lambda *_args: (8, 400, 1),
            load_game_fn=lambda *_args: (77, True),
            helper_factory=lambda debug: helper,
            fetch_lineup_fn=fetch_lineup,
            fetch_refs_fn=fetch_refs,
            notify_fn=notify,
            settings_obj=SETTINGS,
            groups=["111"],
        )
        self.assertEqual(rc, gl.EXIT_SUCCESS)
        fetch_lineup.assert_called_once_with(
            False, helper, 77, True, 9, ignore_existing=False
        )
        fetch_refs.assert_called_once_with(
            False, helper, 77, 9, ignore_existing=False
        )
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], "LINEUP\nREFS")

    def test_run_continues_when_lineup_fetch_fails(self):
        helper = FakeDelAppHelper()
        notify = mock.Mock()
        rc = gl.run(
            now_uts=1000,
            season_id=1,
            next_match_fn=lambda *_args: (9, 1100, False),
            last_match_fn=lambda *_args: (None, None, None),
            load_game_fn=lambda *_args: (77, False),
            helper_factory=lambda debug: helper,
            fetch_lineup_fn=mock.Mock(side_effect=RuntimeError("boom")),
            fetch_refs_fn=mock.Mock(return_value="REFS"),
            notify_fn=notify,
        )
        self.assertEqual(rc, gl.EXIT_SUCCESS)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], "REFS")

    def test_run_skips_notify_when_both_already_stored(self):
        helper = FakeDelAppHelper()
        notify = mock.Mock()
        rc = gl.run(
            now_uts=1000,
            season_id=1,
            next_match_fn=lambda *_args: (9, 1100, False),
            last_match_fn=lambda *_args: (None, None, None),
            load_game_fn=lambda *_args: (77, True),
            helper_factory=lambda debug: helper,
            fetch_lineup_fn=mock.Mock(return_value=None),
            fetch_refs_fn=mock.Mock(return_value=None),
            notify_fn=notify,
        )
        self.assertEqual(rc, gl.EXIT_SUCCESS)
        notify.assert_not_called()

    def test_run_dry_run_prints_and_skips_send(self):
        helper = FakeDelAppHelper()
        wa_send = mock.Mock()
        tr_send = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            rc = gl.run(
                dry_run=True,
                now_uts=1000,
                season_id=1,
                next_match_fn=lambda *_args: (9, 1100, False),
                last_match_fn=lambda *_args: (None, None, None),
                load_game_fn=lambda *_args: (77, True),
                helper_factory=lambda debug: helper,
                fetch_lineup_fn=mock.Mock(return_value="LINEUP"),
                fetch_refs_fn=mock.Mock(return_value="REFS"),
                settings_obj=SETTINGS,
                groups=["111"],
                threema_users=["DBUF47V8"],
                wa_send_fn=wa_send,
                threema_send_fn=tr_send,
            )
        self.assertEqual(rc, gl.EXIT_SUCCESS)
        wa_send.assert_not_called()
        tr_send.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run whatsapp 111:", printed)
        self.assertIn("dry-run threema DBUF47V8:", printed)
        self.assertIn("LINEUP", printed)

    def test_run_ignore_existing_and_reroute_are_forwarded(self):
        helper = FakeDelAppHelper()
        notify = mock.Mock()
        fetch_lineup = mock.Mock(return_value="LINEUP")
        fetch_refs = mock.Mock(return_value="REFS")
        rc = gl.run(
            reroute=True,
            ignore_existing=True,
            now_uts=1000,
            season_id=1,
            next_match_fn=lambda *_args: (9, 1100, False),
            last_match_fn=lambda *_args: (8, 400, 1),
            load_game_fn=lambda *_args: (77, True),
            helper_factory=lambda debug: helper,
            fetch_lineup_fn=fetch_lineup,
            fetch_refs_fn=fetch_refs,
            notify_fn=notify,
            settings_obj=SETTINGS,
            groups=["111"],
        )
        self.assertEqual(rc, gl.EXIT_SUCCESS)
        fetch_lineup.assert_called_once_with(
            False, helper, 77, True, 9, ignore_existing=True
        )
        fetch_refs.assert_called_once_with(
            False, helper, 77, 9, ignore_existing=True
        )
        self.assertTrue(notify.call_args.kwargs["reroute"])

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(gl, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = gl.main(["--debug"])
        self.assertEqual(rc, gl.EXIT_RUNTIME_ERROR)
        self.assertIn("get_lineup failed: boom", output.getvalue())

    def test_main_passes_debug_flag(self):
        with mock.patch.object(gl, "run", return_value=gl.EXIT_SUCCESS) as run_fn:
            self.assertEqual(gl.main([]), gl.EXIT_SUCCESS)
            run_fn.assert_called_once_with(
                debug=False, dry_run=False, reroute=False, ignore_existing=False
            )
        with mock.patch.object(gl, "run", return_value=gl.EXIT_SUCCESS) as run_fn:
            self.assertEqual(gl.main(["-d"]), gl.EXIT_SUCCESS)
            run_fn.assert_called_once_with(
                debug=True, dry_run=False, reroute=False, ignore_existing=False
            )
        with mock.patch.object(gl, "run", return_value=gl.EXIT_SUCCESS) as run_fn:
            self.assertEqual(gl.main(["--dry-run"]), gl.EXIT_SUCCESS)
            run_fn.assert_called_once_with(
                debug=False, dry_run=True, reroute=False, ignore_existing=False
            )
        with mock.patch.object(gl, "run", return_value=gl.EXIT_SUCCESS) as run_fn:
            self.assertEqual(gl.main(["-r", "-i"]), gl.EXIT_SUCCESS)
            run_fn.assert_called_once_with(
                debug=False, dry_run=False, reroute=True, ignore_existing=True
            )

    def test_default_config_path_uses_script_directory(self):
        path = gl.default_config_path("/tmp/tools/get_lineup.py")
        self.assertEqual(path, "/tmp/tools/delapphelper.cfg")

    @mock.patch.dict(os.environ, {"DELAPPHELPER_CFG": "/secret/delapphelper.cfg"}, clear=False)
    def test_default_config_path_prefers_env(self):
        self.assertEqual(
            gl.default_config_path("/tmp/tools/get_lineup.py"),
            "/secret/delapphelper.cfg",
        )

    def test_create_del_app_helper_requires_config_file(self):
        with mock.patch.dict("sys.modules", {"delapphelper": mock.Mock(DelAppHelper=mock.Mock())}):
            with self.assertRaises(RuntimeError) as raised:
                gl.create_del_app_helper(False, cfg_file="/missing/delapphelper.cfg")
        self.assertIn("delapphelper config not found", str(raised.exception))
