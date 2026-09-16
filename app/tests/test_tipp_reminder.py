import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import tipp_reminder as tr


SETTINGS = SimpleNamespace(
    ALLOWED_HOSTS=["tippspiel.example"],
    WA_SRV="wa.local",
    WA_PORT=9009,
    TR_ID="*ABCD",
    TR_SECRET="secret",
    TR_SK="private:key",
)


class TippReminderTests(SimpleTestCase):
    def test_parse_args_defaults_and_flags(self):
        defaults = tr.parse_args([])
        self.assertFalse(defaults.summary)
        self.assertFalse(defaults.dry_run)

        args = tr.parse_args(["-s", "--dry-run"])
        self.assertTrue(args.summary)
        self.assertTrue(args.dry_run)

    def test_build_tip_url(self):
        self.assertEqual(tr.build_tip_url(["tippspiel.example", "other"]), "http://tippspiel.example/game/tip")

    def test_build_group_summary_message_matches_original_format(self):
        user_dic = {2: "bob", 1: "alice"}
        tip_dic = {1: "3:1"}
        message = tr.build_group_summary_message("Eisbaeren", user_dic, tip_dic)
        self.assertEqual(
            message,
            'Hallo,\nHier die Zusammenfassung der Tipps des heutigen Spieltages der Gruppe "Eisbaeren" :\n'
            "alice:  3:1\n"
            "bob:  --\n",
        )

    def test_build_group_reminder_message_lists_missing_tips_or_returns_none(self):
        user_dic = {1: "alice", 2: "bob"}
        self.assertIsNone(tr.build_group_reminder_message("Eisbaeren", user_dic, {1: "1:0", 2: "2:1"}, "http://x/game/tip"))

        message = tr.build_group_reminder_message("Eisbaeren", user_dic, {1: "1:0"}, "http://x/game/tip")
        self.assertEqual(
            message,
            "Hallo,\nDas ist ein Erinnermich der Gruppe Eisbaeren:\n"
            " - bob \n"
            "Tippen nicht vergessen http://x/game/tip ...",
        )

    def test_build_threema_reminder_and_summary_messages(self):
        reminder = tr.build_threema_reminder_message("alice", "http://x/game/tip")
        self.assertEqual(
            reminder,
            "Hallo alice. Das ist ein Erinnermich vom Dynamop-Tippspiel. Tippen nicht vergessen... http://x/game/tip",
        )

        summary = tr.build_threema_summary_message(
            "alice",
            [
                ("Eisbaeren", {"bob": 2, "alice": 1}, {"alice": "4:1"}),
            ],
        )
        self.assertEqual(
            summary,
            "Hallo alice. Hier die Zusamenfassung der Tips des heutigen Spieltages:\n"
            '\nGruppe "Eisbaeren":\n'
            "bob:  -\n"
            "alice: 4:1\n",
        )

    def test_resolve_match_id_uses_next_or_last_match(self):
        next_match = mock.Mock(return_value=(11, 100, False))
        last_match = mock.Mock(return_value=(22, 90, 5))
        self.assertEqual(
            tr.resolve_match_id(50, 15, summary=False, next_match_fn=next_match, last_match_fn=last_match),
            11,
        )
        last_match.assert_not_called()
        self.assertEqual(
            tr.resolve_match_id(50, 15, summary=True, next_match_fn=next_match, last_match_fn=last_match),
            22,
        )

    def test_dispatch_whatsapp_dry_run_prints_and_skips_send(self):
        send_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            tr.dispatch_whatsapp(SETTINGS, "+49123", "hello", dry_run=True, send_fn=send_fn)
        send_fn.assert_not_called()
        self.assertIn("dry-run whatsapp 49123:", output.getvalue())
        self.assertIn("hello", output.getvalue())

    def test_dispatch_whatsapp_strips_plus_and_sends(self):
        send_fn = mock.Mock()
        tr.dispatch_whatsapp(SETTINGS, "+49123", "hello", dry_run=False, send_fn=send_fn)
        send_fn.assert_called_once_with("wa.local", 9009, "49123", "hello")

    def test_dispatch_threema_dry_run_prints_and_skips_send(self):
        send_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            tr.dispatch_threema(SETTINGS, "ABCDEFGH", "hello", dry_run=True, send_fn=send_fn)
        send_fn.assert_not_called()
        self.assertIn("dry-run threema ABCDEFGH:", output.getvalue())

    def test_notify_whatsapp_groups_skips_empty_number_and_sleeps_on_send_path(self):
        send_fn = mock.Mock()
        sleep_fn = mock.Mock()
        groups = [
            {"number": None, "group_id": 1, "group__name": "skip"},
            {"number": "+49123", "group_id": 2, "group__name": "Eisbaeren"},
        ]

        tr.notify_whatsapp_groups(
            groups,
            match_id=9,
            url="http://x/game/tip",
            summary=False,
            settings_obj=SETTINGS,
            dry_run=False,
            load_users_fn=lambda _name: [{"id": 1, "username": "alice"}, {"id": 2, "username": "bob"}],
            load_tips_fn=lambda _match_id, _ids: [{"user_id": 1, "user__username": "alice", "tip": "1:0"}],
            send_fn=send_fn,
            sleep_fn=sleep_fn,
        )

        send_fn.assert_called_once()
        self.assertEqual(send_fn.call_args.args[2], "49123")
        self.assertIn(" - bob \n", send_fn.call_args.args[3])
        sleep_fn.assert_called_once_with(tr.WHATSAPP_SLEEP_SECONDS)

    def test_notify_whatsapp_groups_dry_run_does_not_send_or_sleep(self):
        send_fn = mock.Mock()
        sleep_fn = mock.Mock()
        groups = [{"number": "+49123", "group_id": 2, "group__name": "Eisbaeren"}]

        output = io.StringIO()
        with redirect_stdout(output):
            tr.notify_whatsapp_groups(
                groups,
                match_id=9,
                url="http://x/game/tip",
                summary=True,
                settings_obj=SETTINGS,
                dry_run=True,
                load_users_fn=lambda _name: [{"id": 1, "username": "alice"}],
                load_tips_fn=lambda _match_id, _ids: [{"user_id": 1, "user__username": "alice", "tip": "2:1"}],
                send_fn=send_fn,
                sleep_fn=sleep_fn,
            )

        send_fn.assert_not_called()
        sleep_fn.assert_not_called()
        self.assertIn("dry-run whatsapp 49123:", output.getvalue())
        self.assertIn('Gruppe "Eisbaeren"', output.getvalue())

    def test_notify_threema_users_skips_reminder_when_user_already_tipped(self):
        send_fn = mock.Mock()
        tr.notify_threema_users(
            [{"user__username": "alice", "user_id": 1, "threema": "ABCDEFGH"}],
            match_id=9,
            url="http://x/game/tip",
            summary=False,
            settings_obj=SETTINGS,
            dry_run=False,
            has_tip_fn=lambda _match_id, _user_id: True,
            send_fn=send_fn,
        )
        send_fn.assert_not_called()

    def test_notify_threema_users_sends_reminder_when_missing_tip(self):
        send_fn = mock.Mock()
        tr.notify_threema_users(
            [{"user__username": "alice", "user_id": 1, "threema": "ABCDEFGH"}],
            match_id=9,
            url="http://x/game/tip",
            summary=False,
            settings_obj=SETTINGS,
            dry_run=False,
            has_tip_fn=lambda _match_id, _user_id: False,
            send_fn=send_fn,
        )
        send_fn.assert_called_once()
        self.assertEqual(send_fn.call_args.args[3], "ABCDEFGH")
        self.assertIn("Erinnermich vom Dynamop-Tippspiel", send_fn.call_args.args[4])

    def test_notify_threema_users_summary_dry_run_prints_group_tips(self):
        send_fn = mock.Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            tr.notify_threema_users(
                [{"user__username": "alice", "user_id": 1, "threema": "ABCDEFGH"}],
                match_id=9,
                url="http://x/game/tip",
                summary=True,
                settings_obj=SETTINGS,
                dry_run=True,
                load_groups_fn=lambda _user_id: ["Eisbaeren"],
                load_users_fn=lambda _name: [{"id": 1, "username": "alice"}, {"id": 2, "username": "bob"}],
                load_tips_fn=lambda _match_id, _ids: [
                    {"user_id": 1, "user__username": "alice", "tip": "3:2"}
                ],
                send_fn=send_fn,
            )

        send_fn.assert_not_called()
        printed = output.getvalue()
        self.assertIn("dry-run threema ABCDEFGH:", printed)
        self.assertIn("alice: 3:2", printed)
        self.assertIn("bob:  -", printed)

    def test_notify_whatsapp_groups_sleeps_even_when_there_is_no_message(self):
        send_fn = mock.Mock()
        sleep_fn = mock.Mock()
        tr.notify_whatsapp_groups(
            [{"number": "+49123", "group_id": 2, "group__name": "Eisbaeren"}],
            match_id=9,
            url="http://x/game/tip",
            summary=False,
            settings_obj=SETTINGS,
            dry_run=False,
            load_users_fn=lambda _name: [{"id": 1, "username": "alice"}],
            load_tips_fn=lambda _match_id, _ids: [
                {"user_id": 1, "user__username": "alice", "tip": "1:0"}
            ],
            send_fn=send_fn,
            sleep_fn=sleep_fn,
        )
        send_fn.assert_not_called()
        sleep_fn.assert_called_once_with(tr.WHATSAPP_SLEEP_SECONDS)

    def test_run_uses_last_match_for_summary_and_passes_dry_run(self):
        next_match = mock.Mock(return_value=(11, 100, False))
        last_match = mock.Mock(return_value=(22, 90, 5))

        with mock.patch.object(tr, "notify_whatsapp_groups") as notify_wa:
            with mock.patch.object(tr, "notify_threema_users") as notify_tr:
                rc = tr.run(
                    argv=["--summary", "--dry-run"],
                    now_uts=50,
                    settings_obj=SETTINGS,
                    next_match_fn=next_match,
                    last_match_fn=last_match,
                    groups=[],
                    threema_users=[],
                    season_id=15,
                )

        self.assertEqual(rc, tr.EXIT_SUCCESS)
        last_match.assert_called_once_with(50, 15)
        self.assertEqual(notify_wa.call_args.args[1], 22)
        self.assertTrue(notify_wa.call_args.args[3])
        self.assertTrue(notify_wa.call_args.kwargs["dry_run"])
        self.assertTrue(notify_tr.call_args.kwargs["dry_run"])
        self.assertTrue(notify_tr.call_args.args[3])

    def test_main_returns_runtime_error_on_failure(self):
        with mock.patch.object(tr, "run", side_effect=RuntimeError("boom")):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = tr.main([])
        self.assertEqual(rc, tr.EXIT_RUNTIME_ERROR)
        self.assertIn("tipp_reminder failed: boom", output.getvalue())
