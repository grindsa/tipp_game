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

    def test_add_baseline_jobs_includes_match_import_with_season_args(self):
        jobs = []

        class FakeJob(object):
            def __init__(self, command, comment):
                self.command = command
                self.comment = comment
                self.hour = mock.Mock()
                self.minute = mock.Mock()

        def fake_create_job(_cron, command, comment):
            job = FakeJob(command, comment)
            jobs.append(job)
            return job

        with mock.patch.dict(os.environ, {"CRON_EXECUTION_PREFIX": ""}, clear=False):
            with mock.patch.object(cron_create, "create_job", side_effect=fake_create_job):
                cron_create.add_baseline_jobs(object(), "/app/tools")

        match_jobs = [job for job in jobs if job.comment == cron_create.COMMENT_MATCH_IMPORT]
        self.assertEqual(len(match_jobs), 1)
        self.assertEqual(
            match_jobs[0].command,
            "/app/tools/match_import.py --year 2026 --league-id 1",
        )
        match_jobs[0].hour.on.assert_called_once_with(5)
        match_jobs[0].minute.on.assert_called_once_with(15)

    def test_add_match_jobs_schedules_shared_tipp_bot_profiles(self):
        jobs = []

        class FakeJob(object):
            def __init__(self, command, comment):
                self.command = command
                self.comment = comment
                self.hour = mock.Mock()
                self.minute = mock.Mock()

        def fake_create_job(_cron, command, comment):
            job = FakeJob(command, comment)
            jobs.append(job)
            return job

        match_qs = mock.Mock()
        match_qs.filter.return_value = match_qs
        match_qs.order_by.return_value = match_qs
        match_qs.values_list.return_value = [False]

        with mock.patch.dict(os.environ, {"CRON_EXECUTION_PREFIX": ""}, clear=False):
            with mock.patch.object(cron_create.Match, "objects", match_qs):
                with mock.patch.object(cron_create, "create_job", side_effect=fake_create_job):
                    cron_create.add_match_jobs(object(), "/app/tools", 1700000000, 9, cron_create.TIMEZONE)

        josi = [job for job in jobs if job.comment == cron_create.COMMENT_JOSI_BOT]
        hendrik = [job for job in jobs if job.comment == cron_create.COMMENT_HENDRIK_BOT]
        self.assertEqual(len(josi), 1)
        self.assertEqual(len(hendrik), 1)
        self.assertEqual(josi[0].command, "/app/tools/tipp_bot.py --profile josi")
        self.assertEqual(hendrik[0].command, "/app/tools/tipp_bot.py --profile hendrik")

        pumpup = [job for job in jobs if job.comment == cron_create.COMMENT_MATCH_PUMPUP]
        self.assertEqual(len(pumpup), 1)
        self.assertEqual(pumpup[0].command, "/app/tools/match_pumpup.py")
        pumpup[0].hour.on.assert_called_once_with(9)
        pumpup[0].minute.on.assert_called_once_with(30)

    def test_resolve_delapphelper_run_opts_keeps_volume_flags(self):
        with mock.patch.dict(os.environ, {"CRON_DELAPPHELPER_VOLUME": "-v /cfg:/cfg:ro"}):
            self.assertEqual(cron_create.resolve_delapphelper_run_opts(), "-v /cfg:/cfg:ro")
        with mock.patch.dict(
            os.environ, {"CRON_DELAPPHELPER_VOLUME": "--volume /cfg:/cfg:ro"}
        ):
            self.assertEqual(
                cron_create.resolve_delapphelper_run_opts(), "--volume /cfg:/cfg:ro"
            )
        with mock.patch.dict(os.environ, {"CRON_DELAPPHELPER_VOLUME": "/cfg:/cfg:ro"}):
            self.assertEqual(cron_create.resolve_delapphelper_run_opts(), "-v /cfg:/cfg:ro")

    def test_insert_compose_run_opts_before_jobs_service(self):
        prefix = (
            "docker compose --project-directory /srv/stacks/tipp_game "
            "run --rm --no-deps jobs python"
        )
        self.assertEqual(
            cron_create.insert_compose_run_opts(prefix, "-v /cfg:/app/tools/delapphelper.cfg:ro"),
            "docker compose --project-directory /srv/stacks/tipp_game "
            "run --rm --no-deps -v /cfg:/app/tools/delapphelper.cfg:ro jobs python",
        )
        self.assertEqual(cron_create.insert_compose_run_opts("", "-v /cfg:/cfg"), "")

    def test_delapp_jobs_mount_cfg_when_execution_prefix_is_set(self):
        jobs = []

        class FakeJob(object):
            def __init__(self, command, comment):
                self.command = command
                self.comment = comment
                self.hour = mock.Mock()
                self.minute = mock.Mock()

        def fake_create_job(_cron, command, comment):
            job = FakeJob(command, comment)
            jobs.append(job)
            return job

        prefix = (
            "docker compose --project-directory /srv/stacks/tipp_game "
            "run --rm --no-deps jobs python"
        )
        volume = "-v /srv/data/tipp_game/delapphelper.cfg:/app/tools/delapphelper.cfg:ro"
        match_qs = mock.Mock()
        match_qs.filter.return_value = match_qs
        match_qs.order_by.return_value = match_qs
        match_qs.values_list.return_value = [False]

        with mock.patch.dict(os.environ, {"CRON_EXECUTION_PREFIX": prefix}, clear=False):
            with mock.patch.object(cron_create, "create_job", side_effect=fake_create_job):
                cron_create.add_baseline_jobs(object(), "/app/tools")
            with mock.patch.object(cron_create.Match, "objects", match_qs):
                with mock.patch.object(cron_create, "create_job", side_effect=fake_create_job):
                    cron_create.add_match_jobs(
                        object(), "/app/tools", 1700000000, 9, cron_create.TIMEZONE
                    )

        prefix_with_cfg = (
            "docker compose --project-directory /srv/stacks/tipp_game "
            "run --rm --no-deps {0} jobs python".format(volume)
        )
        commands = {job.comment: job.command for job in jobs}
        self.assertEqual(
            commands[cron_create.COMMENT_MATCH_IMPORT],
            prefix_with_cfg + " /app/tools/match_import.py --year 2026 --league-id 1",
        )
        self.assertEqual(
            commands[cron_create.COMMENT_MATCH_PUMPUP],
            prefix_with_cfg + " /app/tools/match_pumpup.py",
        )
        self.assertEqual(
            commands[cron_create.COMMENT_JOSI_BOT],
            prefix + " /app/tools/tipp_bot.py --profile josi",
        )
        self.assertNotIn(volume, commands["create input for tag cloud"])

    def test_add_match_jobs_schedules_pumpup_for_no_bet_matches(self):
        jobs = []

        class FakeJob(object):
            def __init__(self, command, comment):
                self.command = command
                self.comment = comment
                self.hour = mock.Mock()
                self.minute = mock.Mock()

        def fake_create_job(_cron, command, comment):
            job = FakeJob(command, comment)
            jobs.append(job)
            return job

        match_qs = mock.Mock()
        match_qs.filter.return_value = match_qs
        match_qs.order_by.return_value = match_qs
        match_qs.values_list.return_value = [True]

        with mock.patch.dict(os.environ, {"CRON_EXECUTION_PREFIX": ""}, clear=False):
            with mock.patch.object(cron_create.Match, "objects", match_qs):
                with mock.patch.object(cron_create, "create_job", side_effect=fake_create_job):
                    no_bet = cron_create.add_match_jobs(
                        object(), "/app/tools", 1700000000, 9, cron_create.TIMEZONE
                    )

        self.assertTrue(no_bet)
        comments = [job.comment for job in jobs]
        self.assertIn(cron_create.COMMENT_MATCH_PUMPUP, comments)
        self.assertNotIn(cron_create.COMMENT_JOSI_BOT, comments)
        self.assertNotIn(cron_create.COMMENT_HENDRIK_BOT, comments)

    def test_acquire_script_lock_non_blocking(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = os.path.join(tmp_dir, 'cron.lock')
            handle_one = cron_create.acquire_script_lock(lock_path, blocking=False)
            try:
                with self.assertRaises(BlockingIOError):
                    cron_create.acquire_script_lock(lock_path, blocking=False)
            finally:
                handle_one.close()
