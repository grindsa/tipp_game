from django.test import SimpleTestCase

from tipp_game.settings import parse_name_email_pairs


class AdminSettingsTests(SimpleTestCase):
    def test_parse_single_name_email_pair(self):
        self.assertEqual(
            parse_name_email_pairs('Admin,admin@example.com'),
            [('Admin', 'admin@example.com')],
        )

    def test_parse_multiple_pairs_separated_by_semicolon(self):
        self.assertEqual(
            parse_name_email_pairs('Admin,admin@example.com;Other,other@example.com'),
            [('Admin', 'admin@example.com'), ('Other', 'other@example.com')],
        )

    def test_parse_email_only_and_empty_values(self):
        self.assertEqual(
            parse_name_email_pairs('admin@example.com'),
            [('admin@example.com', 'admin@example.com')],
        )
        self.assertEqual(parse_name_email_pairs(''), [])
        self.assertEqual(parse_name_email_pairs(None), [])
        self.assertEqual(parse_name_email_pairs('Admin,'), [])
