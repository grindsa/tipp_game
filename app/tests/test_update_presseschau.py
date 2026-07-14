import logging
import time
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tools import update_presseschau as up


class _FakeManager:
    def __init__(self, links):
        self._links = links

    def order_by(self, *args, **kwargs):
        return self

    def values_list(self, *args, **kwargs):
        return self._links


class UpdatePresseschauTests(SimpleTestCase):
    def setUp(self):
        self.logger = logging.getLogger('tests.update_presseschau')

    def test_is_wallabag_configured_true(self):
        with mock.patch.multiple(
            up,
            WALLABAG_URL='https://example.local',
            WALLABAG_USER='user',
            WALLABAG_PASSWORD='secret',
            WALLABAG_CLIENTID='client',
            WALLABAG_SECRET='oauth-secret',
        ):
            self.assertTrue(up.is_wallabag_configured())

    def test_is_wallabag_configured_false(self):
        with mock.patch.multiple(
            up,
            WALLABAG_URL='https://example.local',
            WALLABAG_USER='user',
            WALLABAG_PASSWORD='',
            WALLABAG_CLIENTID='client',
            WALLABAG_SECRET='oauth-secret',
        ):
            self.assertFalse(up.is_wallabag_configured())

    def test_append_error_skips_empty_reason(self):
        errors = []
        up._append_error(errors, 'a', 'b', None)
        self.assertEqual(errors, [])

    def test_append_error_adds_error_dict(self):
        errors = []
        up._append_error(errors, 'candidate', 'resolved', 'invalid_link')
        self.assertEqual(
            errors,
            [{'candidate_url': 'candidate', 'resolved_url': 'resolved', 'reason': 'invalid_link'}],
        )

    def test_check_url_existing_returns_no_error(self):
        rc, resolved_url, reason = up.check_url(['https://known.local'], 'https://known.local', self.logger)
        self.assertFalse(rc)
        self.assertIsNone(resolved_url)
        self.assertIsNone(reason)

    @mock.patch('tools.update_presseschau.verify_link', return_value=None)
    def test_check_url_invalid_link(self, _verify_link):
        rc, resolved_url, reason = up.check_url([], 'https://invalid.local/path', self.logger)
        self.assertFalse(rc)
        self.assertIsNone(resolved_url)
        self.assertEqual(reason, 'invalid_link')

    @mock.patch.object(up.Feedlink.objects, 'get_or_create', return_value=(object(), True))
    @mock.patch('tools.update_presseschau.store_link')
    @mock.patch('tools.update_presseschau.verify_link', return_value='https://valid.local/path')
    def test_check_url_ignore_pattern_returns_success_without_store(self, _verify_link, store_link, _get_or_create):
        rc, resolved_url, reason = up.check_url(
            [],
            'https://news.feed-reader.net/nocrawl/target.php?id=123',
            self.logger,
            ignore_pattern='news.feed-reader.net/nocrawl/target.php?id=',
        )
        self.assertTrue(rc)
        self.assertEqual(resolved_url, 'https://valid.local/path')
        self.assertIsNone(reason)
        store_link.assert_not_called()

    @mock.patch.object(up.Feedlink.objects, 'get_or_create', return_value=(object(), True))
    @mock.patch('tools.update_presseschau.store_link', side_effect=RuntimeError('boom'))
    @mock.patch('tools.update_presseschau.is_wallabag_configured', return_value=True)
    @mock.patch('tools.update_presseschau.verify_link', return_value='https://valid.local/path')
    def test_check_url_wallabag_failure_is_reported(self, _verify_link, _configured, _store_link, _get_or_create):
        with self.assertLogs(self.logger.name, level='ERROR') as captured_logs:
            rc, resolved_url, reason = up.check_url([], 'https://fresh.local/path', self.logger)

        self.assertFalse(rc)
        self.assertEqual(resolved_url, 'https://valid.local/path')
        self.assertIn('wallabag_store_failed:', reason)
        self.assertTrue(
            any('wallabag_store_failed url=https://valid.local/path' in row for row in captured_logs.output)
        )

    @mock.patch('tools.update_presseschau.curl_cffi.requests.Session')
    @mock.patch('tools.update_presseschau.check_url')
    def test_parse_feedreader_net_adds_error_when_candidate_fails(self, check_url, session_cls):
        html = '<html><body><div id="results"><a href="#A123">x</a></div></body></html>'
        session = mock.Mock()
        session.get.side_effect = [
            SimpleNamespace(status_code=200, text=html),
        ]
        session_cls.return_value = session
        check_url.return_value = (False, None, 'invalid_link')

        feedreader_links, real_links, error_link_list = up.parse_feedreader_net([], self.logger)

        self.assertEqual(feedreader_links, [])
        self.assertEqual(real_links, [])
        self.assertEqual(len(error_link_list), 1)
        self.assertEqual(error_link_list[0]['reason'], 'invalid_link')
        self.assertIn('news.feed-reader.net/nocrawl/target.php?id=', error_link_list[0]['candidate_url'])

    @mock.patch('tools.update_presseschau.curl_cffi.requests.Session')
    @mock.patch('tools.update_presseschau.check_url')
    def test_parse_feedreader_net_collects_redirect_error(self, check_url, session_cls):
        html = '<html><body><div id="results"><a href="#A123">x</a></div></body></html>'
        session = mock.Mock()
        session.get.side_effect = [
            SimpleNamespace(status_code=200, text=html),
            SimpleNamespace(status_code=200, url='https://redirected.local/article'),
        ]
        session_cls.return_value = session
        check_url.side_effect = [
            (True, 'https://candidate.local/ok', None),
            (False, 'https://redirected.local/article', 'wallabag_store_failed: boom'),
        ]

        feedreader_links, real_links, error_link_list = up.parse_feedreader_net([], self.logger)

        self.assertEqual(len(feedreader_links), 1)
        self.assertEqual(real_links, [])
        self.assertEqual(len(error_link_list), 1)
        self.assertEqual(error_link_list[0]['candidate_url'], 'https://redirected.local/article')
        self.assertIn('wallabag_store_failed:', error_link_list[0]['reason'])

    @mock.patch('tools.update_presseschau.gnewsdecoder')
    @mock.patch('tools.update_presseschau.feedparser.parse')
    @mock.patch('tools.update_presseschau.check_url')
    def test_parse_google_page_blacklisted_decoded_domain_goes_to_error_list(self, check_url, feed_parse, decode):
        feed_parse.return_value = SimpleNamespace(
            entries=[
                SimpleNamespace(
                    link='https://news.google.com/a',
                    published_parsed=time.gmtime(time.time() - 3600),
                )
            ]
        )
        decode.return_value = {'status': True, 'decoded_url': 'https://www.penny-del.org/statistik/news'}
        check_url.return_value = (True, 'https://news.google.com/a', None)

        new_links, error_links = up.parse_google_page([], self.logger)

        self.assertEqual(new_links, [])
        self.assertEqual(len(error_links), 1)
        self.assertEqual(error_links[0]['candidate_url'], 'https://www.penny-del.org/statistik/news')
        self.assertEqual(error_links[0]['reason'], 'google_excluded')
        self.assertEqual(check_url.call_count, 1)

    def test_is_excluded_domain_matches_domain_and_path(self):
        blacklist = ['www.penny-del.org/statistik/', 'spiegel.de']
        self.assertTrue(up._is_excluded_domain('https://www.penny-del.org/statistik/news', blacklist))
        self.assertTrue(up._is_excluded_domain('https://www.spiegel.de/sport', blacklist))
        self.assertFalse(up._is_excluded_domain('https://www.penny-del.org/news', blacklist))

    @mock.patch('tools.update_presseschau.gnewsdecoder')
    @mock.patch('tools.update_presseschau.feedparser.parse')
    @mock.patch('tools.update_presseschau.check_url')
    def test_parse_google_page_non_blacklisted_decoded_domain_goes_to_new_list(self, check_url, feed_parse, decode):
        feed_parse.return_value = SimpleNamespace(
            entries=[
                SimpleNamespace(
                    link='https://news.google.com/b',
                    published_parsed=time.gmtime(time.time() - 3600),
                )
            ]
        )
        decode.return_value = {'status': True, 'decoded_url': 'https://tagesspiegel.de/sport'}
        check_url.side_effect = [
            (True, 'https://news.google.com/b', None),
            (True, 'https://tagesspiegel.de/sport', None),
        ]

        new_links, error_links = up.parse_google_page([], self.logger)

        self.assertEqual(new_links, ['https://tagesspiegel.de/sport'])
        self.assertEqual(error_links, [])

    @mock.patch('tools.update_presseschau.time.time', return_value=1_000_000)
    def test_google_entry_too_old_true_for_entries_older_than_48h(self, _time_now):
        entry = SimpleNamespace(published_parsed=time.gmtime(1_000_000 - (49 * 3600)))
        self.assertTrue(up._is_google_entry_too_old(entry, max_age_hours=48))

    @mock.patch('tools.update_presseschau.time.time', return_value=1_000_000)
    def test_google_entry_too_old_false_for_recent_entries(self, _time_now):
        entry = SimpleNamespace(published_parsed=time.gmtime(1_000_000 - (2 * 3600)))
        self.assertFalse(up._is_google_entry_too_old(entry, max_age_hours=48))

    def test_google_entry_too_old_true_when_publish_time_missing(self):
        entry = SimpleNamespace()
        self.assertTrue(up._is_google_entry_too_old(entry, max_age_hours=48))

    @mock.patch('tools.update_presseschau._process_google_entry')
    @mock.patch('tools.update_presseschau._is_google_entry_too_old')
    @mock.patch('tools.update_presseschau._parse_google_feed')
    def test_parse_google_page_skips_old_entries_before_processing(
        self,
        parse_google_feed,
        is_google_entry_too_old,
        process_google_entry,
    ):
        old_entry = SimpleNamespace(link='https://news.google.com/old', published='old')
        new_entry = SimpleNamespace(link='https://news.google.com/new', published='new')
        parse_google_feed.return_value = SimpleNamespace(entries=[old_entry, new_entry])
        is_google_entry_too_old.side_effect = [True, False]

        new_links, error_links = up.parse_google_page([], self.logger)

        self.assertEqual(new_links, [])
        self.assertEqual(error_links, [])
        process_google_entry.assert_called_once_with(
            [],
            'https://news.google.com/new',
            up.GOOGLE_EXCLUDELIST,
            self.logger,
            new_links,
            error_links,
        )

    @mock.patch('tools.update_presseschau.simple_send')
    def test_send_whatsapp_summary_invalid_port_skips_send(self, simple_send):
        with self.assertLogs(self.logger.name, level='WARNING') as captured_logs, mock.patch.multiple(
            up,
            WA_ADMIN_NUMBER='4912345',
            WA_SRV='127.0.0.1',
            WA_PORT='not-a-number',
        ):
            up._send_whatsapp_summary(['https://new.local/article'], [], self.logger)

        simple_send.assert_not_called()
        self.assertTrue(any('invalid_whatsapp_port' in row for row in captured_logs.output))

    @mock.patch('tools.update_presseschau.simple_send')
    @mock.patch('tools.update_presseschau.parse_google_page', return_value=([], []))
    @mock.patch('tools.update_presseschau.parse_feedreader_net', return_value=([], [], []))
    @mock.patch('tools.update_presseschau.parse_rss_feeds', return_value=(['https://new.local/article'], []))
    def test_main_sends_whatsapp_message_when_env_is_set(
        self,
        _parse_rss_feeds,
        _parse_feedreader_net,
        _parse_google_page,
        simple_send,
    ):
        manager = _FakeManager([])
        with mock.patch.object(up.Feedlink, 'objects', manager), mock.patch.multiple(
            up,
            WA_ADMIN_NUMBER='4912345',
            WA_SRV='127.0.0.1',
            WA_PORT='9009',
        ):
            up.main(self.logger)

        simple_send.assert_called_once()
