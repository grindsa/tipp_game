#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Create daily cron entries for tippspiel."""
from __future__ import absolute_import
import os
import sys
import time

from datetime import datetime
from crontab import CronTab
from pytz import timezone

import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")
django.setup()

from django.conf import settings
from game.models import Match, Season

try:
    from wa_hack_cli import simple_send
except ImportError:
    from game.wa_hack_cli import simple_send

TIMEZONE = timezone('Europe/Berlin')

SCRIPT_TIPP_REMINDER = 'tipp_reminder.py'
SCRIPT_LOAD_VIDEO_STREAMS = 'load_video_streams.py'
COMMENT_GRAB_VIDEO = 'grab video'


def resolve_cron_filename():
    """Resolve cron output file from environment settings."""
    target_path = os.environ.get('CRON_TARGET_PATH')
    if target_path:
        return target_path

    target_dir = os.environ.get('CRON_TARGET_DIR', '/etc/cron.d')
    target_file = os.environ.get('CRON_TARGET_FILE', 'tippgame')
    return os.path.join(target_dir, target_file)


def build_command(script_path, extra_args=''):
    """Build command string for generated cron entries."""
    prefix = os.environ.get('CRON_EXECUTION_PREFIX', '').strip()
    suffix = (' ' + extra_args.strip()) if extra_args else ''
    if prefix:
        return '{0} {1}{2}'.format(prefix, script_path, suffix)
    return '{0}{1}'.format(script_path, suffix)


def resolve_cron_user():
    """Resolve target user for generated cron entries."""
    return os.environ.get('CRON_RUN_AS_USER', 'root')


def create_job(cron, command, comment):
    """Create a new cron job and return it."""
    return cron.new(command=command, comment=comment, user=resolve_cron_user())


def create_script_job(cron, script_dir, script_name, comment, extra_args=''):
    """Create a cron job for a script in the tools directory."""
    script_path = os.path.join(script_dir, script_name)
    command = build_command(script_path, extra_args)
    return create_job(cron, command, comment)


def timestamp_to_hour_minute(timestamp_value, tzone):
    """Convert unix timestamp to local hour/minute integers."""
    hour, minute = datetime.fromtimestamp(int(timestamp_value), tz=tzone).strftime("%H:%M").split(':')
    return int(hour), int(minute)


def get_next_match(uts, season_id):
    """Get next match from database."""
    match_list = Match.objects.filter(season_id=season_id).order_by('date', 'matchday').values('id', 'date', 'matchday', 'tv')

    match_id = match_list[0]['id']
    mtv = False
    match_date = None
    for match in match_list:
        if uts <= match['date']:
            match_id = match['id']
            mtv = match['tv']
            match_date = int(match['date'])
            break

    if not match_date:
        mtv = 0
        (match_id, match_date, _match_day) = get_last_match(uts, season_id)

    return (match_id, match_date, mtv)


def get_last_match(uts, season_id):
    """Get last match from database."""
    match_list = Match.objects.filter(season_id=season_id).order_by('date', 'matchday').values('id', 'date', 'matchday', 'result')

    match_id = None
    match_day = None
    match_date = None
    for match in match_list:
        if int(match['date']) <= int(uts):
            match_id = match['id']
            match_day = match['matchday']
            match_date = match['date']

    return (match_id, match_date, match_day)


def add_baseline_jobs(cron, script_dir):
    """Add jobs that run independent of match windows."""
    wcount = create_script_job(cron, script_dir, 'word_counter.py', 'create input for tag cloud')
    wcount.hour.every(4)
    wcount.minute.on(1)

    psup = create_script_job(cron, script_dir, 'update_presseschau.py', 'update presseschau')
    psup.hour.during(6, 22).every(1)
    psup.minute.on(50)

    trchk = create_script_job(cron, script_dir, 'chk_presseschau.py', 'scan presseschau for updates')
    if datetime.today().isoweekday() > 5:
        trchk.hour.on(9, 21)
    else:
        trchk.hour.on(7, 19)
    trchk.minute.on(0)

    threema = create_script_job(cron, script_dir, 'threema_chk.py', 'check threema credits')
    threema.hour.on(23)
    threema.minute.on(1)

    trtchk = create_script_job(cron, script_dir, 'get_training_times.py', 'Check for new training times')
    trtchk.hour.on(18)
    trtchk.minute.on(10)

    backup = create_script_job(cron, script_dir, 'tipp_backup.sh', 'backup tippgame')
    backup.hour.on(1)
    backup.minute.on(5)

    rank = create_script_job(cron, script_dir, 'get_ranking.py', 'get del table')
    rank.hour.on(2, 23)
    rank.minute.on(0)


def add_match_jobs(cron, script_dir, match_date, match_id, tzone):
    """Add jobs for the upcoming match window and return no_bet."""
    try:
        no_bet = Match.objects.filter(id=match_id).order_by('date', 'matchday').values_list('no_bet', flat=True)[0]
    except IndexError:
        no_bet = False

    summary_hour, summary_minute = timestamp_to_hour_minute(match_date + 60, tzone)

    if not no_bet:
        hour, minute = timestamp_to_hour_minute(match_date - 10800, tzone)
        rem1 = create_script_job(cron, script_dir, SCRIPT_TIPP_REMINDER, '1st reminder')
        rem1.hour.on(hour)
        rem1.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 10740, tzone)
        jbot = create_script_job(cron, script_dir, 'josi_bot.py', 'Josi-Bot')
        jbot.hour.on(hour)
        jbot.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 10740, tzone)
        hbot = create_script_job(cron, script_dir, 'hendrik_bot.py', 'Hendrik-Bot')
        hbot.hour.on(hour)
        hbot.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 7200, tzone)
        rem2 = create_script_job(cron, script_dir, SCRIPT_TIPP_REMINDER, '2nd reminder')
        rem2.hour.on(hour)
        rem2.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 3600, tzone)
        rem3 = create_script_job(cron, script_dir, SCRIPT_TIPP_REMINDER, '3rd reminder')
        rem3.hour.on(hour)
        rem3.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 1800, tzone)
        rem4 = create_script_job(cron, script_dir, SCRIPT_TIPP_REMINDER, 'last reminder')
        rem4.hour.on(hour)
        rem4.minute.on(minute)

        msum = create_script_job(cron, script_dir, SCRIPT_TIPP_REMINDER, 'summary', '-s')
        msum.hour.on(summary_hour)
        msum.minute.on(summary_minute)

        omatip = create_script_job(cron, script_dir, 'oma_tipp_reminder.py', 'oma tipp reminder')
        omatip.hour.on(9)
        omatip.minute.on(31)

        liverank = create_script_job(cron, script_dir, 'get_life_ranking.py', 'get blitztabelle')
        liverank.hour.during(13, 22)
        liverank.minute.every(5)

        lineup = create_script_job(cron, script_dir, 'get_lineup.py', 'get lineup')
        lineup.hour.on(summary_hour - 2)
        lineup.hour.during(summary_hour - 2, summary_hour + 1).every(1)
        lineup.minute.every(15)

        end = create_script_job(cron, script_dir, 'get_penalties_team.py', 'get penalty radio')
        end.hour.on(23)
        end.minute.on(2)

        rank = create_script_job(cron, script_dir, 'get_delgames.py', 'get del results')
        rank.hour.on(23)
        rank.minute.on(1)

        hour, minute = timestamp_to_hour_minute(match_date - 11460, tzone)
        csvc_st = create_job(cron, '/usr/bin/screen -dmS yowsupd-screen /var/www/tipp_game/tools/yowsup_dmn.py', 'start messenger')
        csvc_st.hour.on(hour)
        csvc_st.minute.on(minute)

        hour, minute = timestamp_to_hour_minute(match_date - 111160, tzone)
        csvc_end = create_job(cron, 'killall yowsup_dmn.py', 'stop messenger')
        csvc_end.hour.on(hour)
        csvc_end.minute.on(minute)

    live = create_script_job(cron, script_dir, 'life_score.py', 'get live-score')
    live.hour.on(summary_hour)
    live.hour.during(summary_hour, summary_hour + 3)
    live.minute.every(1)

    pumpup = create_script_job(cron, script_dir, 'match_pumpup.py', 'send match pumpup')
    pumpup.hour.on(9)
    pumpup.minute.on(30)

    return no_bet


def add_recent_match_jobs(cron, script_dir, uts_now, threshold, l_match_date, match_id):
    """Add jobs if there was a match in the last threshold window."""
    if not (l_match_date and uts_now - threshold <= l_match_date):
        return

    try:
        lno_bet = Match.objects.filter(id=match_id).order_by('date', 'matchday').values_list('no_bet', flat=True)[0]
    except IndexError:
        lno_bet = False

    if lno_bet:
        return

    vid1 = create_script_job(cron, script_dir, SCRIPT_LOAD_VIDEO_STREAMS, COMMENT_GRAB_VIDEO)
    vid1.hour.on(5)
    vid1.minute.on(0)

    vid2 = create_script_job(cron, script_dir, SCRIPT_LOAD_VIDEO_STREAMS, COMMENT_GRAB_VIDEO)
    vid2.hour.on(7)
    vid2.minute.on(0)

    vid3 = create_script_job(cron, script_dir, SCRIPT_LOAD_VIDEO_STREAMS, COMMENT_GRAB_VIDEO)
    vid3.hour.on(10)
    vid3.minute.on(0)


def notify_cron_update(no_bet):
    """Send optional status message to WA admin."""
    if not (hasattr(settings, 'WA_ADMIN_NUMBER') and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_PORT')):
        return

    ltime = time.strftime("%d.%m.%Y")
    message = ltime + ' tipp-game-tools: crontab entries created. no_bet:{0}'.format(str(no_bet))
    try:
        simple_send(settings.WA_SRV, settings.WA_PORT, settings.WA_ADMIN_NUMBER, message)
    except Exception:
        pass


def create_cron_entries(tzone):
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
    (match_id, match_date, _tvbc) = get_next_match(uts_now, season_id)
    (_l_match_id, l_match_date, _l_match_day) = get_last_match(uts_now, season_id)

    cron = CronTab(tabfile=filename, user=False)
    cron.remove_all()

    self_job = create_job(cron, build_command(me_script), 'daily check if we need to create contab entries')
    self_job.hour.on(2)
    self_job.minute.on(5)

    # add_baseline_jobs(cron, script_dir)

    no_bet = 'n/a'
    #if match_date and match_date <= uts_now + threshold and uts_now < match_date:
    #    no_bet = add_match_jobs(cron, script_dir, match_date, match_id, tzone)

    # only for poc - later please combine with the codeblock above
    notify_cron_update(no_bet)

    # add_recent_match_jobs(cron, script_dir, uts_now, threshold, l_match_date, match_id)
    cron.write()


if __name__ == "__main__":
    TIMEZONE = timezone('Europe/Berlin')
    create_cron_entries(TIMEZONE)
