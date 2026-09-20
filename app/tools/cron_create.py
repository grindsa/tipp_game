#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create daily cron entries for tippspiel."""

from __future__ import absolute_import
import os
import shutil
import sys
import tempfile
import time
import fcntl

from datetime import datetime
from crontab import CronTab
from pytz import timezone

import django

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")
django.setup()

from django.conf import settings
from game.models import Match, Season

try:
    from wa_hack_cli import simple_send
except ImportError:
    from game.wa_hack_cli import simple_send

TIMEZONE = timezone("Europe/Berlin")

SCRIPT_TIPP_REMINDER = "tipp_reminder.py"
SCRIPT_LOAD_VIDEO_STREAMS = "load_video_streams.py"
SCRIPT_MATCH_IMPORT = "match_import.py"
SCRIPT_TIPP_BOT = "tipp_bot.py"
SCRIPT_MATCH_PUMPUP = "match_pumpup.py"
SCRIPT_YOWSUP_DMN = "yowsup_dmn.py"
SCRIPT_LIFE_SCORE = "life_score.py"
SCRIPT_GET_LINEUP = "get_lineup.py"
SCRIPT_GET_RANKING = "get_ranking.py"
SCRIPT_GET_LIFE_RANKING = "get_life_ranking.py"
MATCH_IMPORT_ARGS = "--year 2026 --league-id 1"
GET_RANKING_ARGS = "--year 2026 --table-id 44"
COMMENT_GRAB_VIDEO = "grab video"
COMMENT_MATCH_IMPORT = "import upcoming del matches"
COMMENT_JOSI_BOT = "Josi-Bot"
COMMENT_HENDRIK_BOT = "Hendrik-Bot"
COMMENT_MATCH_PUMPUP = "send match pumpup"
COMMENT_LIVE_SCORE = "get live-score"
COMMENT_GET_LINEUP = "get lineup"
COMMENT_GET_RANKING = "get del results and table"
COMMENT_GET_LIFE_RANKING = "get blitztabelle"
COMMENT_START_MESSENGER = "start messenger"
COMMENT_STOP_MESSENGER = "stop messenger"
SCREEN_BIN = "/usr/bin/screen"
SCREEN_SESSION_YOWSUP = "yowsupd-screen"
MESSENGER_START_BEFORE_SECONDS = 11460
MESSENGER_STOP_AFTER_SECONDS = 16200
DEFAULT_DELAPPHELPER_VOLUME = (
    "/srv/data/tipp_game/delapphelper.cfg:/app/tools/delapphelper.cfg:ro"
)
DEFAULT_LIFE_SCORE_LOG = "/srv/data/tipp_game/logs/life_score.log"

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_LOCK_ACTIVE = 2


def resolve_cron_filename():
    """Resolve cron output file from environment settings."""
    target_path = os.environ.get("CRON_TARGET_PATH")
    if target_path:
        return target_path

    target_dir = os.environ.get("CRON_TARGET_DIR", "/etc/cron.d")
    target_file = os.environ.get("CRON_TARGET_FILE", "tipp_game")
    return os.path.join(target_dir, target_file)


def resolve_delapphelper_run_opts():
    """Return docker compose run options that mount delapphelper.cfg."""
    if "CRON_DELAPPHELPER_VOLUME" in os.environ:
        volume = os.environ.get("CRON_DELAPPHELPER_VOLUME", "").strip()
    else:
        volume = DEFAULT_DELAPPHELPER_VOLUME
    if not volume:
        return ""
    if volume.startswith(("-v ", "--volume ")):
        return volume
    return "-v {0}".format(volume)


def insert_compose_run_opts(prefix, run_opts):
    """Insert extra `docker compose run` options before the service name."""
    if not prefix or not run_opts:
        return prefix
    opts = run_opts.strip()
    parts = prefix.split()
    try:
        jobs_at = parts.index("jobs")
    except ValueError:
        return "{0} {1}".format(prefix.rstrip(), opts)
    parts.insert(jobs_at, opts)
    return " ".join(parts)


def build_command(script_path, extra_args="", mount_delapp_cfg=False, log_path=""):
    """Build command string for generated cron entries."""
    prefix = os.environ.get("CRON_EXECUTION_PREFIX", "").strip()
    suffix = (" " + extra_args.strip()) if extra_args else ""
    if mount_delapp_cfg:
        prefix = insert_compose_run_opts(prefix, resolve_delapphelper_run_opts())
    if prefix:
        command = "{0} {1}{2}".format(prefix, script_path, suffix)
    else:
        command = "{0}{1}".format(script_path, suffix)
    return append_stdout_redirect(command, log_path)


def append_stdout_redirect(command, log_path):
    """Append a host-side stdout/stderr redirect for cron troubleshooting."""
    if not log_path:
        return command
    return "{0} >> {1} 2>&1".format(command, log_path)


def resolve_dry_run(cli_args):
    """Resolve dry-run mode from CLI or environment."""
    if "--dry-run" in cli_args:
        return True
    return os.environ.get("CRON_DRY_RUN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def resolve_backup_enabled():
    """Resolve whether to write a .bak backup before replacing cron file."""
    value = os.environ.get("CRON_WRITE_BACKUP", "true").strip().lower()
    return value in ("1", "true", "yes", "on")


def resolve_lock_file():
    """Resolve file path for overlap protection lock."""
    return os.environ.get("CRON_LOCK_FILE", "/tmp/tipp_game_cron_create.lock")


def resolve_lock_blocking():
    """Resolve lock behavior. Default is non-blocking (skip when busy)."""
    value = os.environ.get("CRON_LOCK_BLOCKING", "false").strip().lower()
    return value in ("1", "true", "yes", "on")


def _env_flag(name):
    """Return True when an environment flag is enabled."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def resolve_life_score_log_path():
    """Return the host log file for life_score.py, or empty to disable."""
    if "CRON_LIFE_SCORE_LOG" in os.environ:
        return os.environ.get("CRON_LIFE_SCORE_LOG", "").strip()
    return DEFAULT_LIFE_SCORE_LOG


def resolve_life_score_args():
    """Build optional life_score.py flags from environment."""
    args = []
    if _env_flag("CRON_LIFE_SCORE_DEBUG") or resolve_life_score_log_path():
        args.append("--debug")
    if _env_flag("CRON_LIFE_SCORE_FAKE_BREAKTR"):
        args.append("--fake-breaktr")
    if _env_flag("CRON_LIFE_SCORE_DRY_RUN"):
        args.append("--dry-run")
    return " ".join(args)


def resolve_lineup_args():
    """Build optional get_lineup.py flags from environment."""
    args = []
    if _env_flag("CRON_LINEUP_DEBUG"):
        args.append("--debug")
    if _env_flag("CRON_LINEUP_DRY_RUN"):
        args.append("--dry-run")
    return " ".join(args)


def resolve_ranking_args():
    """Build get_ranking.py flags from defaults and environment."""
    args = [GET_RANKING_ARGS]
    if _env_flag("CRON_RANKING_DEBUG"):
        args.append("--debug")
    if _env_flag("CRON_RANKING_DRY_RUN"):
        args.append("--dry-run")
    return " ".join(args)


def resolve_life_ranking_args():
    """Build optional get_life_ranking.py flags from environment."""
    args = []
    if _env_flag("CRON_LIFE_RANKING_DEBUG"):
        args.append("--debug")
    if _env_flag("CRON_LIFE_RANKING_DRY_RUN"):
        args.append("--dry-run")
    return " ".join(args)


def acquire_script_lock(lock_file, blocking=False):
    """Acquire advisory file lock and return an open handle that must stay alive."""
    lock_handle = open(lock_file, "a+")
    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(lock_handle.fileno(), flags)
        return lock_handle
    except BlockingIOError:
        lock_handle.close()
        raise


def current_timestamp():
    """Return current local timestamp for cron metadata."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_cron_file(
    cron, filename, dry_run=False, backup_enabled=True, created_at=None
):
    """Write cron file atomically, optionally creating a backup."""
    created_at = created_at or current_timestamp()
    cron_text = "# created: {0}\n{1}".format(created_at, str(cron))

    if dry_run:
        print("# dry-run: cron output for {0}".format(filename))
        print(cron_text)
        return

    target_dir = os.path.dirname(filename) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".cron_tmp_", dir=target_dir, text=True)
    try:
        with os.fdopen(fd, "w") as fha:
            fha.write(cron_text)

        if backup_enabled and os.path.exists(filename):
            shutil.copy2(filename, filename + ".bak")

        os.replace(temp_path, filename)
        os.chmod(filename, 0o644)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def create_job(cron, command, comment):
    """Create a new cron job and return it."""
    return cron.new(command=command, comment=comment)


def create_script_job(
    cron, script_dir, script_name, comment, extra_args="", mount_delapp_cfg=False, log_path=""
):
    """Create a cron job for a script in the tools directory."""
    script_path = os.path.join(script_dir, script_name)
    command = build_command(
        script_path,
        extra_args,
        mount_delapp_cfg=mount_delapp_cfg,
        log_path=log_path,
    )
    return create_job(cron, command, comment)


def timestamp_to_hour_minute(timestamp_value, tzone):
    """Convert unix timestamp to local hour/minute integers."""
    hour, minute = (
        datetime.fromtimestamp(int(timestamp_value), tz=tzone)
        .strftime("%H:%M")
        .split(":")
    )
    return int(hour), int(minute)


def schedule_job_at_timestamp(job, timestamp_value, tzone):
    """Set a cron job to a single hour:minute derived from a unix timestamp."""
    hour, minute = timestamp_to_hour_minute(timestamp_value, tzone)
    job.hour.on(hour)
    job.minute.on(minute)
    return hour, minute


def build_messenger_start_command(script_dir):
    """Build a detached screen command that starts the WhatsApp daemon."""
    script_path = os.path.join(script_dir, SCRIPT_YOWSUP_DMN)
    inner = build_command(script_path)
    return "{0} -dmS {1} {2}".format(SCREEN_BIN, SCREEN_SESSION_YOWSUP, inner)


def build_messenger_stop_command():
    """Build a command that stops the WhatsApp daemon screen session."""
    return "{0} -S {1} -X quit".format(SCREEN_BIN, SCREEN_SESSION_YOWSUP)


def add_messenger_jobs(cron, script_dir, match_date, tzone):
    """Start the WhatsApp daemon before kickoff and stop it after the match."""
    start_job = create_job(
        cron, build_messenger_start_command(script_dir), COMMENT_START_MESSENGER
    )
    schedule_job_at_timestamp(
        start_job, match_date - MESSENGER_START_BEFORE_SECONDS, tzone
    )

    stop_job = create_job(cron, build_messenger_stop_command(), COMMENT_STOP_MESSENGER)
    schedule_job_at_timestamp(
        stop_job, match_date + MESSENGER_STOP_AFTER_SECONDS, tzone
    )


def get_next_match(uts, season_id):
    """Get next match from database."""
    match_list = (
        Match.objects.filter(season_id=season_id)
        .order_by("date", "matchday")
        .values("id", "date", "matchday", "tv")
    )

    first_match = match_list.first()
    if not first_match:
        return (None, None, False)

    match_id = first_match["id"]
    mtv = False
    match_date = None
    for match in match_list:
        if uts <= match["date"]:
            match_id = match["id"]
            mtv = match["tv"]
            match_date = int(match["date"])
            break

    if not match_date:
        mtv = 0
        match_id, match_date, _match_day = get_last_match(uts, season_id)

    return (match_id, match_date, mtv)


def get_last_match(uts, season_id):
    """Get last match from database."""
    match_list = (
        Match.objects.filter(season_id=season_id)
        .order_by("date", "matchday")
        .values("id", "date", "matchday", "result")
    )

    match_id = None
    match_day = None
    match_date = None
    for match in match_list:
        if int(match["date"]) <= int(uts):
            match_id = match["id"]
            match_day = match["matchday"]
            match_date = match["date"]

    return (match_id, match_date, match_day)


def add_baseline_jobs(cron, script_dir):
    """Add jobs that run independent of match windows."""
    wcount = create_script_job(
        cron, script_dir, "word_counter.py", "create input for tag cloud"
    )
    wcount.hour.every(4)
    wcount.minute.on(1)

    psup = create_script_job(
        cron, script_dir, "update_presseschau.py", "update presseschau"
    )
    psup.hour.during(6, 22).every(3)
    psup.minute.on(30)

    psntf = create_script_job(
        cron, script_dir, "notify_presseschau.py", "scan presseschau for updates"
    )
    if datetime.today().isoweekday() > 5:
        psntf.hour.on(9, 21)
    else:
        psntf.hour.on(7, 19)
    psntf.minute.on(0)

    threema = create_script_job(
        cron, script_dir, "threema_chk.py", "check threema credits"
    )
    threema.hour.on(23)
    threema.minute.on(1)

    mimport = create_script_job(
        cron,
        script_dir,
        SCRIPT_MATCH_IMPORT,
        COMMENT_MATCH_IMPORT,
        MATCH_IMPORT_ARGS,
        mount_delapp_cfg=True,
    )
    mimport.hour.on(5)
    mimport.minute.on(15)

    rank = create_script_job(
        cron,
        script_dir,
        SCRIPT_GET_RANKING,
        COMMENT_GET_RANKING,
        extra_args=resolve_ranking_args(),
        mount_delapp_cfg=True,
    )
    rank.hour.on(2, 23)
    rank.minute.on(0)

    #trtchk = create_script_job(
    #    cron, script_dir, "get_training_times.py", "Check for new training times"
    #)
    #trtchk.hour.on(18)
    #trtchk.minute.on(10)

    #backup = create_script_job(cron, script_dir, "tipp_backup.sh", "backup tippgame")
    #backup.hour.on(1)
    #backup.minute.on(5)


def add_match_jobs(cron, script_dir, match_date, match_id, tzone):
    """Add jobs for the upcoming match window and return no_bet."""
    try:
        no_bet = (
            Match.objects.filter(id=match_id)
            .order_by("date", "matchday")
            .values_list("no_bet", flat=True)[0]
        )
    except IndexError:
        no_bet = False

    summary_hour, summary_minute = timestamp_to_hour_minute(match_date + 60, tzone)

    if not no_bet:
        hour, minute = timestamp_to_hour_minute(match_date - 10800, tzone)
        rem1 = create_script_job(cron, script_dir, SCRIPT_TIPP_REMINDER, "1st reminder")
        rem1.hour.on(hour)
        rem1.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 10740, tzone)
        jbot = create_script_job(
            cron, script_dir, SCRIPT_TIPP_BOT, COMMENT_JOSI_BOT, "--profile josi"
        )
        jbot.hour.on(hour)
        jbot.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 10740, tzone)
        hbot = create_script_job(
            cron,
            script_dir,
            SCRIPT_TIPP_BOT,
            COMMENT_HENDRIK_BOT,
            "--profile hendrik",
        )
        hbot.hour.on(hour)
        hbot.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 7200, tzone)
        rem2 = create_script_job(cron, script_dir, SCRIPT_TIPP_REMINDER, "2nd reminder")
        rem2.hour.on(hour)
        rem2.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 3600, tzone)
        rem3 = create_script_job(cron, script_dir, SCRIPT_TIPP_REMINDER, "3rd reminder")
        rem3.hour.on(hour)
        rem3.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 1800, tzone)
        rem4 = create_script_job(
            cron, script_dir, SCRIPT_TIPP_REMINDER, "last reminder"
        )
        rem4.hour.on(hour)
        rem4.minute.on(minute)

        msum = create_script_job(
            cron, script_dir, SCRIPT_TIPP_REMINDER, "summary", "-s"
        )
        msum.hour.on(summary_hour)
        msum.minute.on(summary_minute)

        omatip = create_script_job(
            cron, script_dir, "oma_tipp_reminder.py", "oma tipp reminder"
        )
        omatip.hour.on(9)
        omatip.minute.on(31)

        liverank = create_script_job(
            cron,
            script_dir,
            SCRIPT_GET_LIFE_RANKING,
            COMMENT_GET_LIFE_RANKING,
            extra_args=resolve_life_ranking_args(),
        )
        liverank.hour.during(13, 22)
        liverank.minute.every(5)

        lineup = create_script_job(
            cron,
            script_dir,
            SCRIPT_GET_LINEUP,
            COMMENT_GET_LINEUP,
            extra_args=resolve_lineup_args(),
            mount_delapp_cfg=True,
        )
        lineup.hour.on(summary_hour - 2)
        lineup.hour.during(summary_hour - 2, summary_hour + 1).every(1)
        lineup.minute.every(15)

        end = create_script_job(
            cron, script_dir, "get_penalties_team.py", "get penalty radio"
        )
        end.hour.on(23)
        end.minute.on(2)

        add_messenger_jobs(cron, script_dir, match_date, tzone)

    live = create_script_job(
        cron,
        script_dir,
        SCRIPT_LIFE_SCORE,
        COMMENT_LIVE_SCORE,
        extra_args=resolve_life_score_args(),
        log_path=resolve_life_score_log_path(),
    )
    live.hour.on(summary_hour)
    live.hour.during(summary_hour, summary_hour + 3)
    live.minute.every(2)

    pumpup = create_script_job(
        cron,
        script_dir,
        SCRIPT_MATCH_PUMPUP,
        COMMENT_MATCH_PUMPUP,
        mount_delapp_cfg=True,
    )
    pumpup.hour.on(9)
    pumpup.minute.on(30)

    return no_bet


def add_recent_match_jobs(cron, script_dir, uts_now, threshold, l_match_date, match_id):
    """Add jobs if there was a match in the last threshold window."""
    if not (l_match_date and uts_now - threshold <= l_match_date):
        return

    try:
        lno_bet = (
            Match.objects.filter(id=match_id)
            .order_by("date", "matchday")
            .values_list("no_bet", flat=True)[0]
        )
    except IndexError:
        lno_bet = False

    if lno_bet:
        return

    vid1 = create_script_job(
        cron, script_dir, SCRIPT_LOAD_VIDEO_STREAMS, COMMENT_GRAB_VIDEO
    )
    vid1.hour.on(5)
    vid1.minute.on(0)

    vid2 = create_script_job(
        cron, script_dir, SCRIPT_LOAD_VIDEO_STREAMS, COMMENT_GRAB_VIDEO
    )
    vid2.hour.on(7)
    vid2.minute.on(0)

    vid3 = create_script_job(
        cron, script_dir, SCRIPT_LOAD_VIDEO_STREAMS, COMMENT_GRAB_VIDEO
    )
    vid3.hour.on(10)
    vid3.minute.on(0)


def notify_cron_update(no_bet):
    """Send optional status message to WA admin."""
    if not (
        hasattr(settings, "WA_ADMIN_NUMBER")
        and hasattr(settings, "WA_SRV")
        and hasattr(settings, "WA_PORT")
    ):
        return

    ltime = time.strftime("%d.%m.%Y")
    message = ltime + " tipp-game-tools: crontab entries created. no_bet:{0}".format(
        str(no_bet)
    )
    try:
        simple_send(
            settings.WA_SRV, settings.WA_PORT, settings.WA_ADMIN_NUMBER, message
        )
    except Exception:
        pass


def create_cron_entries(tzone, dry_run=False):
    """Create all cron entries."""
    threshold = 86400
    filename = resolve_cron_filename()

    script_dir = os.path.dirname(os.path.realpath(__file__))
    me_script = os.path.realpath(__file__)

    target_dir = os.path.dirname(filename)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    uts_now = int(time.time())
    season_id = len(list(Season.objects.values()))
    match_id, match_date, _tvbc = get_next_match(uts_now, season_id)
    _l_match_id, _l_match_date, _l_match_day = get_last_match(uts_now, season_id)

    # Build a fresh in-memory crontab so legacy comments from existing files
    # are not carried over into new output.
    cron = CronTab()

    created_at = current_timestamp()

    self_job = create_job(
        cron,
        build_command(me_script),
        "daily check if we need to create contab entries ({0})".format(created_at),
    )
    self_job.hour.on(2)
    self_job.minute.on(5)

    add_baseline_jobs(cron, script_dir)

    no_bet = "n/a"
    if match_date and match_date <= uts_now + threshold and uts_now < match_date:
        no_bet = add_match_jobs(cron, script_dir, match_date, match_id, tzone)

        # Keep cron generation independent from optional notification delivery.
        try:
            notify_cron_update(no_bet)
        except Exception as exc:
            print("notify_cron_update failed: {0}".format(exc))

    # add_recent_match_jobs(cron, script_dir, uts_now, threshold, l_match_date, match_id)
    write_cron_file(
        cron,
        filename,
        dry_run=dry_run,
        backup_enabled=resolve_backup_enabled(),
        created_at=created_at,
    )


def run(cli_args):
    """Run script with lock protection."""
    dry_run = resolve_dry_run(cli_args)
    target_file = resolve_cron_filename()
    lock_file = resolve_lock_file()
    lock_blocking = resolve_lock_blocking()
    print(
        "cron_create start: target={0} dry_run={1} lock_file={2} lock_blocking={3}".format(
            target_file, dry_run, lock_file, lock_blocking
        )
    )
    lock_handle = None
    try:
        lock_handle = acquire_script_lock(lock_file, blocking=lock_blocking)
    except BlockingIOError:
        print("lock active, skipping run: {0}".format(lock_file))
        return EXIT_LOCK_ACTIVE

    try:
        create_cron_entries(TIMEZONE, dry_run=dry_run)
    except Exception as exc:
        print("cron_create failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR
    finally:
        if lock_handle:
            lock_handle.close()

    return EXIT_SUCCESS


if __name__ == "__main__":
    TIMEZONE = timezone("Europe/Berlin")
    sys.exit(run(sys.argv[1:]))
