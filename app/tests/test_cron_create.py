import io
import os
import tempfile
from contextlib import redirect_stdout
from unittest import mock

from django.test import SimpleTestCase

from tools import cron_create


class FakeCron(object):
    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


class CronCreateTests(SimpleTestCase):
    def test_resolve_dry_run_from_cli(self):
        self.assertTrue(cron_create.resolve_dry_run(['--dry-run']))

    @mock.patch.dict(os.environ, {'CRON_DRY_RUN': 'true'}, clear=False)
    def test_resolve_dry_run_from_env(self):
        self.assertTrue(cron_create.resolve_dry_run([]))

    def test_write_cron_file_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, 'tipp_game')
            fake_cron = FakeCron('5 * * * * joern echo test')

            output = io.StringIO()
            with redirect_stdout(output):
                cron_create.write_cron_file(fake_cron, out_file, dry_run=True, backup_enabled=True)

            self.assertFalse(os.path.exists(out_file))
            self.assertIn('dry-run', output.getvalue())

    def test_write_cron_file_atomic_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, 'tipp_game')
            with open(out_file, 'w') as fha:
                fha.write('old-content')

            fake_cron = FakeCron('new-content')
            cron_create.write_cron_file(fake_cron, out_file, dry_run=False, backup_enabled=True)

            with open(out_file, 'r') as fha:
                self.assertEqual(fha.read(), 'new-content')

            with open(out_file + '.bak', 'r') as fha:
                self.assertEqual(fha.read(), 'old-content')

    def test_acquire_script_lock_non_blocking(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = os.path.join(tmp_dir, 'cron.lock')
            handle_one = cron_create.acquire_script_lock(lock_path, blocking=False)
            try:
                with self.assertRaises(BlockingIOError):
                    cron_create.acquire_script_lock(lock_path, blocking=False)
            finally:
                handle_one.close()
