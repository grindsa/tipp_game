import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import TestCase, mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools.old" / "threema_chk.py"


def load_module():
    spec = importlib.util.spec_from_file_location("threema_chk_old", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_runtime_modules(settings_obj=None, simple_send_mock=None, credit_class=None):
    settings_obj = settings_obj or SimpleNamespace()

    django_pkg = ModuleType("django")
    django_conf = ModuleType("django.conf")
    django_conf.settings = settings_obj

    game_pkg = ModuleType("game")
    game_wa = ModuleType("game.wa_hack_cli")
    game_wa.simple_send = simple_send_mock or mock.Mock()
    game_pkg.wa_hack_cli = game_wa

    trgw_pkg = ModuleType("trgw")
    trgw_models = ModuleType("trgw.models")
    trgw_models.Threemacredit = credit_class or object
    trgw_pkg.models = trgw_models

    return {
        "django": django_pkg,
        "django.conf": django_conf,
        "game": game_pkg,
        "game.wa_hack_cli": game_wa,
        "trgw": trgw_pkg,
        "trgw.models": trgw_models,
    }


class ThreemaChkOldTests(TestCase):
    def test_fetch_threema_credits_parses_integer_payload(self):
        mod = load_module()

        response = mock.Mock()
        response.read.return_value = b"42\n"
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)

        with mock.patch.object(mod, "urlopen", return_value=response) as urlopen_mock:
            credits = mod.fetch_threema_credits("ID", "SECRET")

        self.assertEqual(credits, 42)
        urlopen_mock.assert_called_once_with(
            "https://msgapi.threema.ch/credits?from=ID&secret=SECRET",
            timeout=mod.REQUEST_TIMEOUT_SECONDS,
        )

    def test_store_credit_snapshot_persists_model_instance(self):
        mod = load_module()
        captured = {}

        class FakeThreemaCredit:
            def __init__(self, date, credit):
                captured["date"] = date
                captured["credit"] = credit

            def save(self):
                captured["saved"] = True

        fake_modules = install_runtime_modules(credit_class=FakeThreemaCredit)

        with (
            mock.patch.dict(sys.modules, fake_modules, clear=False),
            mock.patch.object(mod.time, "time", return_value=1_700_000_000),
        ):
            mod.store_credit_snapshot(7)

        self.assertEqual(captured["date"], 1_700_000_000)
        self.assertEqual(captured["credit"], 7)
        self.assertTrue(captured["saved"])

    def test_notify_low_credit_sends_whatsapp_when_config_is_present(self):
        mod = load_module()
        simple_send_mock = mock.Mock()

        settings_obj = SimpleNamespace(
            WA_ADMIN_NUMBER="49123",
            WA_SRV="127.0.0.1",
            WA_PORT=9009,
        )
        fake_modules = install_runtime_modules(settings_obj=settings_obj, simple_send_mock=simple_send_mock)

        with mock.patch.dict(sys.modules, fake_modules, clear=False):
            mod.notify_low_credit(credits=5, threshold=10)

        simple_send_mock.assert_called_once()
        args = simple_send_mock.call_args.args
        self.assertEqual(args[0], "127.0.0.1")
        self.assertEqual(args[1], 9009)
        self.assertEqual(args[2], "49123")
        self.assertIn("5 Threema-Credits", args[3])

    def test_notify_low_credit_skips_when_whatsapp_config_missing(self):
        mod = load_module()
        simple_send_mock = mock.Mock()

        settings_obj = SimpleNamespace(
            WA_ADMIN_NUMBER="",
            WA_SRV="127.0.0.1",
            WA_PORT=9009,
        )
        fake_modules = install_runtime_modules(settings_obj=settings_obj, simple_send_mock=simple_send_mock)

        with mock.patch.dict(sys.modules, fake_modules, clear=False):
            mod.notify_low_credit(credits=5, threshold=10)

        simple_send_mock.assert_not_called()

    @mock.patch.dict(os.environ, {"THREEMA_CREDIT_THRESHOLD": "12"}, clear=False)
    def test_main_returns_zero_and_notifies_when_below_threshold(self):
        mod = load_module()
        settings_obj = SimpleNamespace(TR_ID="ID", TR_SECRET="SECRET")
        fake_modules = install_runtime_modules(settings_obj=settings_obj)

        with (
            mock.patch.dict(sys.modules, fake_modules, clear=False),
            mock.patch.object(mod, "setup_django", return_value=None),
            mock.patch.object(mod, "fetch_threema_credits", return_value=8),
            mock.patch.object(mod, "store_credit_snapshot") as store_snapshot_mock,
            mock.patch.object(mod, "notify_low_credit") as notify_mock,
        ):
            rc = mod.main()

        self.assertEqual(rc, 0)
        store_snapshot_mock.assert_called_once_with(8)
        notify_mock.assert_called_once_with(8, 12)

    @mock.patch.dict(os.environ, {}, clear=False)
    def test_main_returns_zero_without_notification_when_above_threshold(self):
        mod = load_module()
        settings_obj = SimpleNamespace(TR_ID="ID", TR_SECRET="SECRET")
        fake_modules = install_runtime_modules(settings_obj=settings_obj)

        with (
            mock.patch.dict(sys.modules, fake_modules, clear=False),
            mock.patch.object(mod, "setup_django", return_value=None),
            mock.patch.object(mod, "fetch_threema_credits", return_value=50),
            mock.patch.object(mod, "store_credit_snapshot") as store_snapshot_mock,
            mock.patch.object(mod, "notify_low_credit") as notify_mock,
        ):
            rc = mod.main()

        self.assertEqual(rc, 0)
        store_snapshot_mock.assert_called_once_with(50)
        notify_mock.assert_not_called()

    def test_main_returns_one_on_exception(self):
        mod = load_module()

        with mock.patch.object(mod, "setup_django", side_effect=RuntimeError("boom")):
            rc = mod.main()

        self.assertEqual(rc, 1)
