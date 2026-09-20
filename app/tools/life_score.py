#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Eisbären live-score ticker based on the DEL period-events JSON feed."""

from __future__ import absolute_import
from __future__ import print_function

import argparse
import datetime
import os
import sys
import time
from collections import namedtuple
from functools import partial

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth.models import User
from pytz import timezone
from game.models import Goal, Groupsetting, Match, Playerstatebb, Season, Tip, Usersetting
from game.myfunctions import get_last_match, get_score, print_debug, send_threema, sort_dic

try:
    from wa_hack_cli import simple_send
except ImportError:
    from game.wa_hack_cli import simple_send

TICKER_URL = (
    "https://s3.eu-west-1.amazonaws.com/de.hokejovyzapis.cz/matches/{0}/period-events.json"
)
PLAYER_URL = "https://app.eisbaeren.de/index.php?r=output%2Fplayer"
GAMESTATS_URL = "http://tippspiel.dynamop.de/game/gamestats"
EBB_SHORT_NAME = "EBB"
MATCH_TZ = timezone("Europe/Berlin")
PERIOD_KEYS = ("1", "2", "3", "overtime", "shootout")
PERIOD_LABELS = {
    "1": "1. Drittel",
    "2": "2. Drittel",
    "3": "3. Drittel",
    "overtime": "OT",
    "shootout": "SO",
}
# periodStart in this key means the previous period just ended.
PERIOD_START_ENDS = {
    "2": "1.",
    "3": "2.",
    "overtime": "3.",
    "shootout": "3.",
}

MATCH_MAX_AGE_SECONDS = 43200
FAKE_BREAKTR_MATCH_MAX_AGE_SECONDS = 1443200
BREAK_DURATION_SECONDS = 960
FAKE_BREAKTR_BREAK_SECONDS = 20
WHATSAPP_SLEEP_SECONDS = 2
HTTP_TIMEOUT_SECONDS = 20

HAPPY_SMILEY = b" \xF0\x9F\x98\x84"
POOP_SMILEY = b" \xF0\x9F\x92\xA9"
ALL_OUT_EMOJI = b"\xF0\x9F\x98\x92".decode()

BREAK_PERIODS = (2, 4)
EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1

MatchState = namedtuple(
    "MatchState",
    (
        "match_id match_date done period_cnt result break_time "
        "home_team guest_team home_match ticker_id no_bet delapp_game_id"
    ),
)
EMPTY_MATCH = MatchState(
    None, None, True, 0, "0:0", 0, None, None, False, 0, False, 0
)

TickerUpdate = namedtuple(
    "TickerUpdate",
    "home_score guest_score scorer_name score_time score period_num remaining_time period_label",
    defaults=(None,),
)


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Poll the DEL period-events feed and notify groups about goals and periods."
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable extra logging.",
    )
    parser.add_argument(
        "-f",
        "--fake-breaktr",
        action="store_true",
        help="Use shortened match-age and break thresholds for testing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated messages instead of sending WhatsApp/Threema.",
    )
    parser.add_argument(
        "-r",
        "--reroute",
        action="store_true",
        help="Send WhatsApp messages to WA_ADMIN_NUMBER instead of configured groups.",
    )
    return parser.parse_args(argv)


def resolve_thresholds(fake_breaktr):
    """Return match-age and break-duration thresholds."""
    if fake_breaktr:
        return FAKE_BREAKTR_MATCH_MAX_AGE_SECONDS, FAKE_BREAKTR_BREAK_SECONDS
    return MATCH_MAX_AGE_SECONDS, BREAK_DURATION_SECONDS


def load_season_id(season_model=None):
    """Return the current season id."""
    model = season_model or Season
    return len(list(model.objects.values()))


def match_is_too_old(now_uts, match_date, max_age_seconds):
    """Return True if the last match started too long ago."""
    if match_date is None:
        return True
    return max_age_seconds < int(now_uts) - int(match_date)


def format_match_datetime(match_date, tz=None):
    """Format a unix timestamp as YYYY-MM-DD HH:MM in match local time."""
    if match_date is None:
        return None
    tz = tz or MATCH_TZ
    return datetime.datetime.fromtimestamp(int(match_date), tz=tz).strftime(
        "%Y-%m-%d %H:%M"
    )


def is_home_match(home_team):
    """Return True when Eisbären Berlin is the home team."""
    if not home_team:
        return False
    return home_team == EBB_SHORT_NAME or "Berlin" in home_team


def is_first_run(state):
    """Return True for the first poll after kickoff."""
    return int(state.period_cnt or 0) == 0


def is_break(period_cnt):
    """Return True while the match is in an intermission."""
    return int(period_cnt or 0) in BREAK_PERIODS


def split_score(score):
    """Split `h:g` into integers, defaulting to 0:0."""
    try:
        home, guest = str(score).split(":", 1)
        return int(home), int(guest)
    except (AttributeError, TypeError, ValueError):
        return 0, 0


def format_score(home_score, guest_score):
    """Format a score pair as `h:g`."""
    return "{0}:{1}".format(home_score, guest_score)


def score_change(old_score, new_score):
    """Return (home_delta, guest_delta) between two `h:g` scores."""
    old_home, old_guest = split_score(old_score)
    new_home, new_guest = split_score(new_score)
    return new_home - old_home, new_guest - old_guest


def is_single_goal_increment(old_score, new_score):
    """Return True when exactly one side scored exactly one goal."""
    return score_change(old_score, new_score) in ((1, 0), (0, 1))


def is_single_goal_decrement(old_score, new_score):
    """Return True when exactly one side lost exactly one goal."""
    return score_change(old_score, new_score) in ((-1, 0), (0, -1))


def is_single_goal_change(old_score, new_score):
    """Return True when the score moved by exactly one goal on one side."""
    return is_single_goal_increment(old_score, new_score) or is_single_goal_decrement(
        old_score, new_score
    )


def period_label_from_clock(score_time):
    """Map game-clock minutes to a period label."""
    minutes, _seconds = split_score(score_time)
    if minutes < 21:
        return "1. Drittel"
    if minutes < 41:
        return "2. Drittel"
    if minutes < 61:
        return "3. Drittel"
    return "OT"


def parse_period_number(num):
    """Normalize a period marker such as `1.` to an integer."""
    if num is None or num == "":
        return None
    if isinstance(num, int):
        return num
    return int(str(num).rstrip("."))


def fetch_json(url, timeout=HTTP_TIMEOUT_SECONDS, get_fn=None):
    """Fetch and decode a JSON payload."""
    getter = get_fn or requests.get
    response = getter(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def period_events_url(game_id, debug=False):
    """Build the S3 period-events URL for a DEL match id."""
    print_debug(debug, "period_events_url game_id={0}".format(game_id))
    if not game_id:
        print_debug(debug, "period_events_url -> None")
        return None
    url = TICKER_URL.format(int(game_id))
    print_debug(debug, "period_events_url -> {0}".format(url))
    return url


def flatten_period_events(payload, debug=False):
    """Flatten period-keyed events into chronological sequence numbers."""
    print_debug(debug, "flatten_period_events()")
    events = []
    seq = 0
    source = payload if isinstance(payload, dict) else {}
    for period_key in PERIOD_KEYS:
        for entry in source.get(period_key) or []:
            if not isinstance(entry, dict):
                continue
            seq += 1
            events.append(
                {
                    "seq": seq,
                    "period_key": period_key,
                    "time": entry.get("time") or 0,
                    "type": entry.get("type"),
                    "data": entry.get("data") or {},
                }
            )
    print_debug(debug, "flatten_period_events -> {0}".format(len(events)))
    return events


def scores_from_current_score(current_score, debug=False):
    """Parse a `h:g` currentScore from a period-events goal."""
    print_debug(debug, "scores_from_current_score current_score={0}".format(current_score))
    if current_score in (None, ""):
        return None
    home, guest = split_score(current_score)
    return home, guest


def scorer_from_event(data, debug=False):
    """Return `Surname, Name` from a period-events goal payload."""
    scorer = (data or {}).get("scorer") or {}
    surname = (scorer.get("surname") or "").strip()
    name = (scorer.get("name") or "").strip()
    if surname and name:
        label = "{0}, {1}".format(surname, name)
    else:
        label = surname or name or None
    print_debug(debug, "scorer_from_event -> {0}".format(label))
    return label


def period_label_from_key(period_key, debug=False):
    """Map a period-events key to a German period label."""
    label = PERIOD_LABELS.get(str(period_key) if period_key is not None else "")
    print_debug(debug, "period_label_from_key {0} -> {1}".format(period_key, label))
    return label


def period_end_from_event(event, debug=False):
    """Return (period_num, remaining_time) when a period just ended."""
    event_type = (event or {}).get("type")
    period_key = (event or {}).get("period_key")
    if event_type in ("periodEnd", "periodend"):
        marker = "{0}.".format(period_key) if str(period_key).isdigit() else "3."
        print_debug(debug, "period_end_from_event periodEnd -> {0}".format(marker))
        return marker, "0:00"
    if event_type == "periodStart":
        marker = PERIOD_START_ENDS.get(str(period_key))
        if marker:
            print_debug(debug, "period_end_from_event periodStart {0} -> {1}".format(period_key, marker))
            return marker, "0:00"
    print_debug(debug, "period_end_from_event -> None")
    return None, None


def clock_from_game_time(game_time):
    """Format game-clock seconds as `mm:ss`."""
    minutes, seconds = divmod(int(float(game_time or 0)), 60)
    return "{0}:{1}".format(str(minutes).zfill(2), str(seconds).zfill(2)), minutes


def remaining_from_event(event, debug=False):
    """Build the Match.remaining text from a period-events item."""
    period_key = (event or {}).get("period_key")
    label = period_label_from_key(period_key, debug=debug) or period_key or "Spiel"
    clock, minutes = clock_from_game_time((event or {}).get("time"))
    remaining = "wir sind im {0} ({1})...".format(label, clock)
    print_debug(debug, "remaining_from_event -> {0}".format(remaining))
    return remaining, minutes


def update_match(match_id, match_model=None, **defaults):
    """Create or update a Match row."""
    model = match_model or Match
    obj, _created = model.objects.update_or_create(id=match_id, defaults=defaults)
    return obj


def load_match_state(match_id, match_date, match_model=None):
    """Load live-score fields for a match."""
    model = match_model or Match
    try:
        row = model.objects.filter(id=match_id).values(
            "done",
            "period_cnt",
            "result",
            "break_time",
            "home_team__short_name",
            "guest_team__short_name",
            "last_ebbticker_id",
            "no_bet",
            "delapp_game_id",
        )[0]
    except IndexError:
        return None

    home_team = row["home_team__short_name"]
    return MatchState(
        match_id=match_id,
        match_date=match_date,
        done=bool(row["done"]),
        period_cnt=int(row["period_cnt"] or 0),
        result=row["result"] or "0:0",
        break_time=int(row["break_time"] or 0),
        home_team=home_team,
        guest_team=row["guest_team__short_name"],
        home_match=is_home_match(home_team),
        ticker_id=int(row["last_ebbticker_id"] or 0),
        no_bet=bool(row["no_bet"]),
        delapp_game_id=int(row["delapp_game_id"] or 0),
    )


def fetch_and_store_players(debug, fetch_json_fn=None, player_model=None):
    """Refresh Playerstatebb from the EBB player JSON."""
    print_debug(debug, "fetch playerstats from ebb ticker")
    fetch_json_fn = fetch_json_fn or fetch_json
    model = player_model or Playerstatebb
    payload = fetch_json_fn(PLAYER_URL)
    for player in payload.get("players") or []:
        try:
            model.objects.update_or_create(id=player["id"], defaults=player)
        except Exception as err:
            print(err)


def get_score_from_json(
    debug,
    match_id,
    game_id,
    ticker_id,
    result,
    fetch_json_fn=None,
    update_match_fn=None,
):
    """Read new period-events and return the latest score/period update."""
    fetch_json_fn = fetch_json_fn or fetch_json
    update_match_fn = update_match_fn or update_match
    home_score, guest_score = split_score(result)
    score = format_score(home_score, guest_score)
    update = TickerUpdate(home_score, guest_score, None, None, score, None, None)

    url = period_events_url(game_id, debug=debug)
    if not url:
        print_debug(debug, "json skip: missing delapp_game_id")
        return update

    payload = fetch_json_fn(url)
    events = flatten_period_events(payload, debug=debug)
    ticker_id = int(ticker_id or 0)

    for event in events:
        if event["seq"] <= ticker_id:
            continue

        remaining, _minutes = remaining_from_event(event, debug=debug)
        update_match_fn(
            match_id, last_ebbticker_id=event["seq"], remaining=remaining
        )

        if event.get("type") == "goal":
            data = event.get("data") or {}
            parsed = scores_from_current_score(data.get("currentScore"), debug=debug)
            if parsed is None:
                continue
            home_score, guest_score = parsed
            score = format_score(home_score, guest_score)
            score_time, _minutes = clock_from_game_time(
                data.get("scoreboardTime", event.get("time"))
            )
            scorer_name = scorer_from_event(data, debug=debug)
            period_label = period_label_from_key(event.get("period_key"), debug=debug)
            print_debug(
                debug,
                "json Tor: {0}, {1}, {2}".format(score_time, scorer_name, score),
            )
            update = TickerUpdate(
                home_score,
                guest_score,
                scorer_name,
                score_time,
                score,
                None,
                None,
                period_label,
            )
            break

        period_num, remaining_time = period_end_from_event(event, debug=debug)
        if period_num is None:
            continue
        print_debug(
            debug,
            "json: periodend {0} from {1}".format(period_num, event.get("type")),
        )
        update = TickerUpdate(
            home_score,
            guest_score,
            None,
            None,
            score,
            period_num,
            remaining_time,
        )
        break

    print_debug(
        debug,
        "json return: {0}, {1}, {2}, {3}, {4}, {5}, {6}".format(
            update.home_score,
            update.guest_score,
            update.scorer_name,
            update.score_time,
            update.score,
            update.period_num,
            update.remaining_time,
        ),
    )
    return update


def store_goal(match_id, score, scorer_name, score_time, period, goal_model=None):
    """Persist a scorer and return the text snippet for notifications."""
    if score_time and ":" not in str(score_time):
        score_time = "{0}:00".format(score_time)
    message = "{0} {1}\n".format(scorer_name, score_time)
    model = goal_model or Goal
    model.objects.update_or_create(
        match_id=match_id,
        score=score,
        defaults={
            "name": scorer_name,
            "match_id": match_id,
            "score": score,
            "time": score_time,
            "period": period,
        },
    )
    return message


def delete_goal(match_id, score, goal_model=None):
    """Remove the Goal row for a retracted score."""
    model = goal_model or Goal
    model.objects.filter(match_id=match_id, score=score).delete()


def unicode_multiplier(string, num):
    """Repeat a smiley once per goal."""
    return string * int(num)


def how_to_smile(new_home, new_guest, old_result, home_match):
    """Pick celebration or disappointment smileys for the scoring side."""
    old_home, old_guest = split_score(old_result)
    try:
        home_diff = old_home - int(new_home)
        guest_diff = old_guest - int(new_guest)
    except (TypeError, ValueError):
        return None

    if home_diff == -1:
        smiley = unicode_multiplier(
            HAPPY_SMILEY if home_match else POOP_SMILEY, new_home
        )
        return smiley.decode()
    if guest_diff == -1:
        smiley = unicode_multiplier(
            POOP_SMILEY if home_match else HAPPY_SMILEY, new_guest
        )
        return smiley.decode()
    return None


def classify_user_tips(tips, home_score, guest_score):
    """Split tips into still-alive (yai) and already-out (yao)."""
    yao_dic = {}
    yai_dic = {}
    home_score = int(home_score)
    guest_score = int(guest_score)
    for row in tips:
        tip = row.get("tip") or ""
        if ":" not in str(tip):
            continue
        tip_home, tip_guest = split_score(tip)
        username = row["user__username"]
        if tip_home < home_score or tip_guest < guest_score:
            yao_dic[username] = tip
        else:
            yai_dic[username] = tip
    return yao_dic, yai_dic


def build_goal_header(home_score, guest_score, smily, scorer_name):
    """Build the goal headline used in WhatsApp/Threema alerts."""
    message = "Tor: {0}:{1}".format(home_score, guest_score)
    if smily:
        message = "{0} {1}\n".format(message, smily)
    else:
        message = message + "\n"
    if scorer_name:
        message = "{0}{1}".format(message, scorer_name)
    return message


def build_correction_header(old_score, new_score):
    """Build the headline for a one-goal referee correction."""
    return "Korrektur: {0} → {1}\n".format(old_score, new_score)


def append_yao_whatsapp(message, group_name, yao_dic, yai_dic):
    """Append the WhatsApp you-are-out block."""
    if not yao_dic:
        return message
    if not yai_dic:
        return "{0}Alle sind raus {1}...".format(message, ALL_OUT_EMOJI)
    if len(yai_dic) < len(yao_dic):
        lines = ["{0}Alle sind raus bis auf:\n".format(message)]
        for username in sorted(yai_dic):
            lines.append(" - {0}: {1}\n".format(username, yai_dic[username]))
        return "".join(lines)
    lines = [
        '{0}Die folgenden User der Gruppe "{1}" sind raus:\n'.format(
            message, group_name
        )
    ]
    for username in sorted(yao_dic):
        lines.append(" - {0}: {1}\n".format(username, yao_dic[username]))
    return "".join(lines)


def append_yao_threema(message, group_name, yao_dic):
    """Append the Threema you-are-out block."""
    if not yao_dic:
        return message
    lines = [
        '{0} Die folgenden User der Gruppe "{1}" sind raus:\n'.format(
            message, group_name
        )
    ]
    for username in sorted(yao_dic):
        lines.append(" - {0}: {1}\n".format(username, yao_dic[username]))
    return "".join(lines)


def has_whatsapp_settings(settings_obj):
    """Return True when WhatsApp transport settings are present."""
    return hasattr(settings_obj, "WA_SRV") and hasattr(settings_obj, "WA_PORT")


def admin_whatsapp_number(settings_obj=None):
    """Return WA_ADMIN_NUMBER from the environment or Django settings."""
    number = os.environ.get("WA_ADMIN_NUMBER", "").strip()
    if number:
        return number
    if settings_obj is not None:
        number = getattr(settings_obj, "WA_ADMIN_NUMBER", None)
        if number:
            return str(number).strip()
    return ""


def resolve_whatsapp_recipient(settings_obj, number, reroute=False):
    """Return the WhatsApp destination, optionally replaced by WA_ADMIN_NUMBER."""
    if reroute:
        admin = admin_whatsapp_number(settings_obj)
        if not admin:
            raise RuntimeError(
                "WA_ADMIN_NUMBER is not set; cannot reroute WhatsApp messages"
            )
        return admin
    return (number or "").lstrip("+")


def has_threema_settings(settings_obj, require_key=True):
    """Return True when Threema transport settings are present."""
    if not (
        hasattr(settings_obj, "TR_ID") and hasattr(settings_obj, "TR_SECRET")
    ):
        return False
    if require_key:
        return hasattr(settings_obj, "TR_SK")
    return True


def dispatch_whatsapp(settings_obj, recipient, message, dry_run=False, send_fn=None):
    """Send a WhatsApp message, or print it during dry-run."""
    if dry_run:
        print("dry-run whatsapp {0}:\n{1}".format(recipient, message))
        return
    sender = send_fn or simple_send
    sender(settings_obj.WA_SRV, settings_obj.WA_PORT, recipient, message)


def dispatch_threema(
    settings_obj, receiver, message, dry_run=False, send_fn=None, secret_key=None
):
    """Send a Threema message, or print it during dry-run."""
    if dry_run:
        print("dry-run threema {0}:\n{1}".format(receiver, message))
        return
    sender = send_fn or send_threema
    if secret_key is None:
        secret_key = getattr(settings_obj, "TR_SK", None)
    sender(
        settings_obj.TR_ID,
        settings_obj.TR_SECRET,
        secret_key,
        receiver,
        message,
    )


def send_yao(
    scorer_name,
    home_score,
    guest_score,
    match_id,
    smily,
    match_start=False,
    correction=False,
    old_score=None,
    settings_obj=None,
    group_model=None,
    user_model=None,
    usersetting_model=None,
    tip_model=None,
    wa_send_fn=None,
    threema_send_fn=None,
    sleep_fn=None,
    dry_run=False,
    reroute=False,
):
    """Notify groups about kickoff or a goal, including you-are-out status."""
    settings_obj = settings_obj or settings
    group_model = group_model or Groupsetting
    user_model = user_model or User
    usersetting_model = usersetting_model or Usersetting
    tip_model = tip_model or Tip
    wa_send_fn = wa_send_fn or simple_send
    threema_send_fn = threema_send_fn or send_threema
    sleep_fn = sleep_fn or time.sleep
    tip = format_score(home_score, guest_score)

    groups = group_model.objects.values(
        "number", "group_id", "group__name", "yao_message", "alert"
    )
    for group in groups:
        if not (group["yao_message"] or group["alert"]):
            continue

        number = resolve_whatsapp_recipient(
            settings_obj, group["number"], reroute=reroute
        )
        group_name = group["group__name"]
        users = list(
            user_model.objects.filter(groups__name__in=[group_name]).values(
                "username", "id"
            )
        )
        user_ids = [user["id"] for user in users]
        threema_dic = {}
        for user in users:
            threema = list(
                usersetting_model.objects.filter(
                    user_id=user["id"], threema_reminder=True
                ).values_list("threema", flat=True)
            )
            if threema:
                threema_dic[user["username"]] = threema[0]

        tips = list(
            tip_model.objects.filter(
                match_id=match_id, user_id__in=user_ids
            ).values("user_id", "user__username", "tip")
        )
        yao_dic, yai_dic = ({}, {})
        if group["yao_message"] and not correction:
            yao_dic, yai_dic = classify_user_tips(tips, home_score, guest_score)

        message = None
        if match_start:
            message = "Das Spiel hat begonnen..."
        elif correction and (group["alert"] or group["yao_message"]):
            message = build_correction_header(old_score, tip)
        elif tip != "0:0" and (group["alert"] or yao_dic):
            message = build_goal_header(home_score, guest_score, smily, scorer_name)

        wa_message = message
        if group["yao_message"] and yao_dic and wa_message and not match_start and not correction:
            wa_message = append_yao_whatsapp(
                wa_message, group_name, yao_dic, yai_dic
            )

        if wa_message and number and (dry_run or has_whatsapp_settings(settings_obj)):
            dispatch_whatsapp(
                settings_obj,
                number,
                wa_message,
                dry_run=dry_run,
                send_fn=wa_send_fn,
            )
            if not dry_run:
                sleep_fn(WHATSAPP_SLEEP_SECONDS)

        threema_message = message
        if group["yao_message"] and yao_dic and threema_message and not match_start and not correction:
            threema_message = append_yao_threema(
                threema_message, group_name, yao_dic
            )
        if threema_message and threema_dic and (
            dry_run or has_threema_settings(settings_obj, require_key=True)
        ):
            for recipient in threema_dic.values():
                dispatch_threema(
                    settings_obj,
                    recipient,
                    threema_message,
                    dry_run=dry_run,
                    send_fn=threema_send_fn,
                    secret_key=getattr(settings_obj, "TR_SK", None),
                )


def get_gamestat_text(match_id, stats_fn=None):
    """Optional period-end statistics block. Missing helper is ignored."""
    if stats_fn is None:
        return None
    try:
        stats = stats_fn(match_id, True)
        if not stats or stats.get("homeSog", 0) <= 0 or stats.get("guestSog", 0) <= 0:
            return None
        return (
            "Hier die aktuellen Statistiken zum Spiel:\n"
            "Teams: {0} / {1}\n"
            "Torschüsse: {2} / {3}\n"
            "gewonnene Bullys: {4} / {5}\n"
            "Strafminuten: {6} / {7}\n"
        ).format(
            stats["homeTeam"],
            stats["guestTeam"],
            stats["homeSog"],
            stats["guestSog"],
            stats["homeBully"],
            stats["guestBully"],
            stats["homePim"],
            stats["guestPim"],
        )
    except Exception:
        return None


def period_transition(
    period, num, remaining_time, home_score, guest_score, break_time, break_end, now_uts
):
    """Return (defaults, message, attach_stats) for a period state change."""
    num = parse_period_number(num)
    result = format_score(home_score, guest_score)
    try:
        tied = int(home_score) == int(guest_score)
    except (TypeError, ValueError):
        tied = False

    if period == 0 and num == 1:
        return {"period_cnt": 1}, None, False
    if period == 1 and num == 1 and remaining_time == "0:00":
        return (
            {"period_cnt": 2, "break_time": break_end},
            "1. Drittel beendet. Zwischenstand: {0}".format(result),
            True,
        )
    if period == 2 and break_time <= now_uts:
        return {"period_cnt": 3}, "2. Drittel beginnt", False
    if period == 3 and num == 2 and remaining_time == "0:00":
        return (
            {"period_cnt": 4, "break_time": break_end},
            "2. Drittel beendet. Zwischenstand: {0}".format(result),
            True,
        )
    if period == 4 and break_time <= now_uts:
        return {"period_cnt": 5}, "3. Drittel beginnt", False
    if period == 5 and num == 3 and remaining_time == "0:00" and tied:
        return (
            {"period_cnt": 6},
            "3. Drittel beendet. Zwischenstand: {0}".format(result),
            True,
        )
    if period == 6 and num == 3 and remaining_time == "0:00" and tied:
        return {"period_cnt": 7}, "OT beendet. Stand: {0}".format(result), True
    if period >= 5 and num == 3 and remaining_time == "0:00" and not tied:
        return (
            {"done": True, "period_cnt": 8, "result": result},
            "Spielende. Endstand: {0}".format(result),
            True,
        )
    return None, None, False


def build_endgame_ranking(message, users, tip_dic, result, score_list, no_bet):
    """Append per-user points after the final whistle."""
    if no_bet or "spielende" not in message.lower():
        return message

    tmp_dic = {}
    for user in users:
        username = user["username"]
        if username in tip_dic:
            tmp_dic[username] = {
                "score": get_score(result, tip_dic[username], score_list),
                "tip": tip_dic[username],
            }
        else:
            tmp_dic[username] = {"score": 0, "tip": "-"}

    lines = [message + "\n*Punktevergabe:*\n"]
    for username in sort_dic(tmp_dic, "score", True):
        lines.append(
            "{0}: {1} ({2})\n".format(
                username, tmp_dic[username]["score"], tmp_dic[username]["tip"]
            )
        )
    return "".join(lines)


def send_alert(
    match_id,
    message,
    result,
    settings_obj=None,
    group_model=None,
    user_model=None,
    usersetting_model=None,
    tip_model=None,
    match_model=None,
    wa_send_fn=None,
    threema_send_fn=None,
    sleep_fn=None,
    dry_run=False,
    reroute=False,
):
    """Send a period/game alert to groups with alert enabled."""
    settings_obj = settings_obj or settings
    group_model = group_model or Groupsetting
    user_model = user_model or User
    usersetting_model = usersetting_model or Usersetting
    tip_model = tip_model or Tip
    match_model = match_model or Match
    wa_send_fn = wa_send_fn or simple_send
    threema_send_fn = threema_send_fn or send_threema
    sleep_fn = sleep_fn or time.sleep

    tip_dic = {}
    if "spielende" in message.lower():
        for row in tip_model.objects.filter(match_id=match_id).values(
            "tip", "user_id__username"
        ):
            tip_dic[row["user_id__username"]] = row["tip"]

    try:
        no_bet = match_model.objects.filter(id=match_id).values_list("no_bet", flat=True)[0]
    except IndexError:
        no_bet = False

    groups = group_model.objects.filter(alert=True).values(
        "number", "group_id", "group__name", "alert"
    )
    for group in groups:
        number = resolve_whatsapp_recipient(
            settings_obj, group["number"], reroute=reroute
        )
        users = list(
            user_model.objects.filter(groups__name__in=[group["group__name"]]).values(
                "username", "id"
            )
        )
        threema_dic = {}
        for user in users:
            threema = list(
                usersetting_model.objects.filter(
                    user_id=user["id"], threema_reminder=True
                ).values_list("threema", flat=True)
            )
            if threema:
                threema_dic[user["username"]] = threema[0]

        msg = message
        if "spielende" in message.lower():
            score_list = list(
                group_model.objects.filter(group__name=group["group__name"]).values(
                    "p_winloss", "p_diff", "p_tipp", "p_7vs2", "p_notip"
                )[:1]
            )
            msg = build_endgame_ranking(msg, users, tip_dic, result, score_list, no_bet)

        if number and (dry_run or has_whatsapp_settings(settings_obj)):
            dispatch_whatsapp(
                settings_obj, number, msg, dry_run=dry_run, send_fn=wa_send_fn
            )
            if not dry_run:
                sleep_fn(WHATSAPP_SLEEP_SECONDS)
        if threema_dic and (
            dry_run or has_threema_settings(settings_obj, require_key=False)
        ):
            for recipient in threema_dic.values():
                try:
                    dispatch_threema(
                        settings_obj,
                        recipient,
                        msg,
                        dry_run=dry_run,
                        send_fn=threema_send_fn,
                        secret_key=getattr(settings_obj, "TR_SK", None),
                    )
                except Exception:
                    pass


def check_report_period(
    debug,
    period,
    match_id,
    num,
    remaining_time,
    home_score,
    guest_score,
    break_time,
    break_end,
    now_uts,
    update_match_fn=None,
    send_alert_fn=None,
    stats_fn=None,
    dry_run=False,
    reroute=False,
):
    """Advance period state and send the matching alert when needed."""
    update_match_fn = update_match_fn or update_match
    send_alert_fn = send_alert_fn or partial(send_alert, dry_run=dry_run, reroute=reroute)
    print_debug(
        debug,
        "chk_rep: {0},{1},{2},{3},{4},{5}".format(
            period, num, remaining_time, now_uts, break_time, break_time - now_uts
        ),
    )
    defaults, message, attach_stats = period_transition(
        period,
        num,
        remaining_time,
        home_score,
        guest_score,
        break_time,
        break_end,
        now_uts,
    )
    if defaults:
        update_match_fn(match_id, **defaults)
    if message and attach_stats:
        gamestats = get_gamestat_text(match_id, stats_fn=stats_fn)
        if gamestats:
            suffix = "\n" if defaults and defaults.get("done") else ""
            message = "{0}\n\n{1}{2}".format(message, gamestats, suffix)
    if message:
        send_alert_fn(match_id, message, format_score(home_score, guest_score))


def apply_goal_update(debug, state, update, send_yao_fn=None, update_match_fn=None):
    """Store a one-goal increment or apply a one-goal correction."""
    send_yao_fn = send_yao_fn or send_yao
    update_match_fn = update_match_fn or update_match
    if state.result == update.score:
        return False
    if not is_single_goal_change(state.result, update.score):
        old_home, old_guest = split_score(state.result)
        print_debug(
            debug,
            "score {0}:{1} does not make sense, Keeping old one {2}:{3}".format(
                update.home_score, update.guest_score, old_home, old_guest
            ),
        )
        return False

    print_debug(debug, "score {0} (old: {1}) looks good".format(update.score, state.result))
    if is_single_goal_decrement(state.result, update.score):
        delete_goal(state.match_id, state.result)
        update_match_fn(state.match_id, result=update.score)
        send_yao_fn(
            None,
            update.home_score,
            update.guest_score,
            state.match_id,
            None,
            correction=True,
            old_score=state.result,
        )
        return True

    goal_data = ""
    if update.score != "0:0" and update.scorer_name:
        goal_data = store_goal(
            state.match_id,
            update.score,
            update.scorer_name,
            update.score_time,
            update.period_label or period_label_from_clock(update.score_time),
        )
    update_match_fn(state.match_id, result=update.score)
    smily = how_to_smile(
        update.home_score, update.guest_score, state.result, state.home_match
    )
    send_yao_fn(
        goal_data, update.home_score, update.guest_score, state.match_id, smily
    )
    return True


def run(
    debug=False,
    fake_breaktr=False,
    dry_run=False,
    reroute=False,
    now_uts=None,
    season_id=None,
    last_match_fn=None,
    load_state_fn=None,
    fetch_players_fn=None,
    fetch_ticker_fn=None,
    update_match_fn=None,
    send_yao_fn=None,
    check_period_fn=None,
):
    """Poll the live ticker for the current match and return an exit code."""
    now_uts = int(time.time()) if now_uts is None else int(now_uts)
    max_age, break_seconds = resolve_thresholds(fake_breaktr)
    if fake_breaktr:
        print_debug(debug, "break tr manipulated")

    season_id = load_season_id() if season_id is None else season_id
    last_match_fn = last_match_fn or get_last_match
    match_id, match_date, _matchday = last_match_fn(now_uts, season_id)
    if match_is_too_old(now_uts, match_date, max_age):
        print_debug(
            debug,
            "too old time difference: {0}".format(
                int(now_uts) - int(match_date or 0)
            ),
        )
        return EXIT_SUCCESS

    load_state_fn = load_state_fn or (
        lambda mid, mdate: load_match_state(mid, mdate)
    )
    state = load_state_fn(match_id, match_date)
    print_debug(debug, f"state: {state}")
    if state is None:
        state = EMPTY_MATCH
    print_debug(
        debug,
        f"home_team: {state.home_team} guest_team: {state.guest_team} home_match:{state.home_match} match_id:{state.match_id}, match_date:{format_match_datetime(state.match_date)}, result:{state.result}, period_cnt:{state.period_cnt}, ticker_id:{state.ticker_id}, delapp_game_id:{state.delapp_game_id}"
    )
    if state.done or not state.match_id:
        print_debug(debug, "match already over")
        return EXIT_SUCCESS

    update_match_fn = update_match_fn or update_match
    send_yao_fn = send_yao_fn or partial(send_yao, dry_run=dry_run, reroute=reroute)
    check_period_fn = check_period_fn or partial(
        check_report_period, dry_run=dry_run, reroute=reroute
    )

    break_end = now_uts + break_seconds
    if is_first_run(state):
        print_debug(debug, "this is the first run after the match started")
        fetch_fn = fetch_players_fn or fetch_and_store_players
        fetch_fn(debug)
        update_match_fn(state.match_id, result="0:0", period_cnt=1)
        if state.no_bet:
            send_yao_fn(None, 0, 0, state.match_id, None, match_start=True)
        return EXIT_SUCCESS

    print_debug(debug, "not the first run")
    if is_break(state.period_cnt):
        print_debug(
            debug,
            "we are in a break, no check. {0}s left...".format(
                state.break_time - now_uts
            ),
        )
        home_score, guest_score = split_score(state.result)
        update = TickerUpdate(
            home_score, guest_score, None, None, state.result, None, None
        )
    else:
        fetch_ticker_fn = fetch_ticker_fn or get_score_from_json
        update = fetch_ticker_fn(
            debug,
            state.match_id,
            state.delapp_game_id,
            state.ticker_id,
            state.result,
        )
        apply_goal_update(
            debug,
            state,
            update,
            send_yao_fn=send_yao_fn,
            update_match_fn=update_match_fn,
        )

    check_period_fn(
        debug,
        state.period_cnt,
        state.match_id,
        update.period_num,
        update.remaining_time,
        update.home_score,
        update.guest_score,
        state.break_time,
        break_end,
        now_uts,
    )
    return EXIT_SUCCESS


def main(argv=None):
    """CLI entry point."""
    args = parse_args(argv)
    try:
        return run(
            debug=args.debug,
            fake_breaktr=args.fake_breaktr,
            dry_run=args.dry_run,
            reroute=args.reroute,
        )
    except Exception as exc:
        print("life_score failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
