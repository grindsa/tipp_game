import os
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import notify_presseschau as np


class NotifyPresseschauTests(SimpleTestCase):
    def test_normalize_source_handles_prefixes_and_missing_host(self):
        self.assertEqual(np._normalize_source("https://www.example.org/a"), "example.org")
        self.assertEqual(np._normalize_source("https://mobil.tagesspiegel.de/x"), "tagesspiegel.de")
        self.assertEqual(np._normalize_source("not-a-valid-url"), "unknown-source")

    def test_normalize_recipients_filters_empty_values(self):
        recipients = np._normalize_recipients([None, "", "  ", 123, "49123"])
        self.assertEqual(recipients, ["123", "49123"])

    def test_build_message_renders_fallback_title_and_source(self):
        message = np._build_message(
            [
                {"id": 7, "title": "", "url": None},
                {"id": 8, "title": "Titel", "url": "https://www.example.org/news"},
            ],
            "https://tippspiel.local/article?id=",
        )

        self.assertIn("(ohne Titel)", message)
        self.assertIn("unknown-source", message)
        self.assertIn("example.org", message)
        self.assertIn("https://tippspiel.local/article?id=8", message)

    @mock.patch.dict(os.environ, {"PRESSSCHAU_ALERT_INTERVAL_SECONDS": "120"}, clear=False)
    def test_get_interval_seconds_prefers_env(self):
        settings_obj = SimpleNamespace(PRESSSCHAU_ALERT_INTERVAL_SECONDS=999)
        self.assertEqual(np._get_interval_seconds(settings_obj=settings_obj), 120)

    @mock.patch.dict(os.environ, {"PRESSSCHAU_ALERT_INTERVAL_SECONDS": "invalid"}, clear=False)
    def test_get_interval_seconds_falls_back_on_invalid(self):
        self.assertEqual(np._get_interval_seconds(default_seconds=30), 30)

    @mock.patch.dict(os.environ, {"PRESSSCHAU_ARTICLE_URL_BASE": "https://env.local/?id="}, clear=False)
    def test_get_article_url_base_prefers_env(self):
        settings_obj = SimpleNamespace(PRESSSCHAU_ARTICLE_URL_BASE="https://settings.local/?id=")
        self.assertEqual(
            np._get_article_url_base("https://default.local/?id=", settings_obj=settings_obj),
            "https://env.local/?id=",
        )

    def _install_fake_runtime_modules(self, entries, groups, simple_send_mock):
        entries_qs = mock.Mock()
        entries_qs.filter.return_value = entries_qs
        entries_qs.order_by.return_value = entries_qs
        entries_qs.values.return_value = entries

        entries_objects = mock.Mock()
        entries_objects.using.return_value = entries_qs
        entries_cls = SimpleNamespace(objects=entries_objects)

        groups_qs = mock.Mock()
        groups_qs.values_list.return_value = groups

        groups_objects = mock.Mock()
        groups_objects.filter.return_value = groups_qs
        groupsetting_cls = SimpleNamespace(objects=groups_objects)

        article_models = ModuleType("article.models")
        article_models.Entries = entries_cls

        game_models = ModuleType("game.models")
        game_models.Groupsetting = groupsetting_cls

        wa_module = ModuleType("wa_hack_cli")
        wa_module.simple_send = simple_send_mock

        return {
            "article.models": article_models,
            "game.models": game_models,
            "wa_hack_cli": wa_module,
        }

    def test_main_dry_run_prints_message_and_skips_send(self):
        simple_send_mock = mock.Mock()
        fake_modules = self._install_fake_runtime_modules(
            entries=[
                {
                    "id": 99,
                    "title": "Dry Run Titel",
                    "url": "https://www.example.org/news",
                    "created_at": datetime.now(timezone.utc),
                }
            ],
            groups=["49123"],
            simple_send_mock=simple_send_mock,
        )

        with (
            mock.patch.object(np.django, "setup", return_value=None),
            mock.patch.dict(sys.modules, fake_modules, clear=False),
            mock.patch("builtins.print") as print_mock,
        ):
            rc = np.main(["--dry-run"])

        self.assertEqual(rc, 0)
        simple_send_mock.assert_not_called()
        print_mock.assert_called_once()
        printed = print_mock.call_args.args[0]
        self.assertIn("Dry Run Titel", printed)
        self.assertIn("example.org", printed)

    def test_main_calls_simple_send_on_normal_run(self):
        simple_send_mock = mock.Mock()
        fake_modules = self._install_fake_runtime_modules(
            entries=[
                {
                    "id": 7,
                    "title": "Titel",
                    "url": "https://www.example.org/news",
                    "created_at": datetime.now(timezone.utc),
                }
            ],
            groups=["49123", "49234"],
            simple_send_mock=simple_send_mock,
        )

        with (
            mock.patch.object(np.django, "setup", return_value=None),
            mock.patch.dict(sys.modules, fake_modules, clear=False),
        ):
            rc = np.main([])

        self.assertEqual(rc, 0)
        simple_send_mock.assert_called_once()
        call_args = simple_send_mock.call_args.args
        self.assertEqual(call_args[2], "49123,49234")
        self.assertIn("Titel", call_args[3])

    def test_main_returns_zero_when_no_new_entries(self):
        simple_send_mock = mock.Mock()
        fake_modules = self._install_fake_runtime_modules(
            entries=[],
            groups=["49123"],
            simple_send_mock=simple_send_mock,
        )

        with (
            mock.patch.object(np.django, "setup", return_value=None),
            mock.patch.dict(sys.modules, fake_modules, clear=False),
        ):
            rc = np.main([])

        self.assertEqual(rc, 0)
        simple_send_mock.assert_not_called()
