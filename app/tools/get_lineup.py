#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch and announce the Eisbären lineup and referees for the current match."""

from __future__ import absolute_import
from __future__ import print_function

import argparse
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from game.models import Groupsetting, Lineup, Match, Referee, Refpermatch, Season, Usersetting
from game.myfunctions import get_last_match, get_next_match, print_debug, send_threema

try:
    from wa_hack_cli import simple_send
except ImportError:
    from game.wa_hack_cli import simple_send

EBB_SHORT_NAME = "EBB"
CFG_FILENAME = "delapphelper.cfg"
LINEUP_INTRO = "Anbei die Aufstellung für das heutige Spiel:\n\n"
GUEST_LINEUP_INTRO = (
    "\nUnd, auf Wunsch einer einzelnen Dame, die Aufstellung des Gegners:\n\n"
)
REFEREE_INTRO = "Anbei die Schiedsrichter für das heutige Spiel:\n\n"
MESSAGE_GREETING = "Liebe Tippjemeinde\n\n"

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch the Eisbären lineup and referees and notify groups."
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable extra logging.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated messages instead of sending WhatsApp/Threema.",
    )
    return parser.parse_args(argv)


def load_season_id(season_model=None):
    """Return the current season id."""
    model = season_model or Season
    return len(model.objects.values())


def default_config_path(script_file=None):
    """Return the DelAppHelper config path from env or next to this script."""
    env_path = os.environ.get("DELAPPHELPER_CFG", "").strip()
    if env_path:
        return env_path
    script_file = script_file or __file__
    return os.path.join(os.path.dirname(script_file), CFG_FILENAME)


def create_del_app_helper(debug, cfg_file=None):
    """Create a DelAppHelper context manager."""
    try:
        from delapphelper import DelAppHelper
    except ImportError as exc:
        raise RuntimeError(
            "delapphelper is not installed; add delapp-helper to requirements "
            "and rebuild the image"
        ) from exc

    cfg_file = cfg_file or default_config_path()
    if not os.path.isfile(cfg_file):
        raise RuntimeError(
            "delapphelper config not found: {0}. Mount the file or set DELAPPHELPER_CFG".format(
                cfg_file
            )
        )
    return DelAppHelper(debug=debug, cfg_file=cfg_file)


def select_current_match(now_uts, next_match, last_match, debug=False):
    """Prefer the match whose kickoff is closer to now."""
    next_id, next_date, _tv = next_match
    last_id, last_date, _matchday = last_match
    if last_id and last_date is not None and next_date is not None:
        if abs(int(now_uts) - int(last_date)) < abs(int(now_uts) - int(next_date)):
            print_debug(debug, "use last match instead of next match")
            return last_id, last_date
    return next_id, next_date


def load_match_game(match_id, team_filter=EBB_SHORT_NAME, match_model=None):
    """Return (delapp_game_id, home_match) for a stored match."""
    if not match_id:
        return 0, False
    model = match_model or Match
    rows = list(
        model.objects.filter(id=match_id).values(
            "delapp_game_id", "home_team__short_name"
        )[:1]
    )
    if not rows:
        return 0, False
    raw_game_id = rows[0].get("delapp_game_id")
    if not raw_game_id:
        return 0, False
    home_match = rows[0].get("home_team__short_name") == team_filter
    return int(raw_game_id), home_match


def lineup_exists(match_id, lineup_model=None):
    """Return True when a lineup row is already stored for the match."""
    model = lineup_model or Lineup
    return model.objects.filter(match_id=match_id).exists()


def refs_exist(match_id, refpermatch_model=None):
    """Return True when referees are already stored for the match."""
    model = refpermatch_model or Refpermatch
    return model.objects.filter(match_id=match_id).exists()


def store_lineup(match_id, lineup_text, raw_json, lineup_model=None):
    """Create or update the lineup row for a match."""
    model = lineup_model or Lineup
    model.objects.update_or_create(
        match_id=match_id,
        defaults={"raw_json": raw_json, "lineup": lineup_text},
    )


def create_referee(name, referee_model=None):
    """Create a referee row and return its id."""
    model = referee_model or Referee
    return model.objects.create(name=name).id


def referee_search_name(full_name):
    """Return the last-name token used to match stored referees."""
    parts = (full_name or "").strip().split(" ", 1)
    if len(parts) == 2:
        return parts[1]
    return parts[0] if parts else ""


def match_existing_referee(name, referee_rows):
    """Return a stored referee id when the last name is already known."""
    search = referee_search_name(name).lower()
    if not search:
        return None
    for referee in referee_rows or []:
        stored_name = (referee.get("name") or "").lower()
        if search in stored_name:
            return referee.get("id")
    return None


def resolve_referee_ids(ref_names, referee_rows, create_fn=None):
    """Map DEL referee names to stored ids, creating missing rows."""
    create_fn = create_fn or create_referee
    ref_ids = []
    for name in ref_names or []:
        existing_id = match_existing_referee(name, referee_rows)
        if existing_id:
            ref_ids.append(existing_id)
        else:
            ref_ids.append(create_fn(name))
    return ref_ids


def store_referees(match_id, ref_names, referee_model=None, refpermatch_model=None, create_fn=None):
    """Store the two head referees for a match when both can be resolved."""
    referee_model = referee_model or Referee
    refpermatch_model = refpermatch_model or Refpermatch

    def create_missing(name):
        return create_referee(name, referee_model=referee_model)

    create_fn = create_fn or create_missing
    referee_rows = list(referee_model.objects.values("id", "name"))
    ref_ids = resolve_referee_ids(ref_names, referee_rows, create_fn=create_fn)
    if len(ref_ids) != 2:
        return False
    refpermatch_model.objects.update_or_create(
        match_id=match_id,
        defaults={"r1_id": ref_ids[0], "r2_id": ref_ids[1]},
    )
    return True


def head_referee_names(ref_dic):
    """Return the two head-referee names when both are present."""
    if not isinstance(ref_dic, dict):
        return None
    first = (ref_dic.get("headReferee1") or {}).get("name")
    second = (ref_dic.get("headReferee2") or {}).get("name")
    if first and second:
        return [first, second]
    return None


def format_referee_message(ref_list):
    """Build the referee announcement from a list of names."""
    if not ref_list:
        return None
    message = REFEREE_INTRO
    for referee in ref_list:
        message = "{0}{1}\n".format(message, referee)
    return message


def fetch_lineup_message(
    debug,
    helper,
    game_id,
    home_match,
    match_id,
    lineup_model=None,
):
    """Fetch, store, and format the lineup when it is not already stored."""
    if lineup_exists(match_id, lineup_model=lineup_model):
        print_debug(debug, "we have a lineup stored in db. Do nothing")
        return None

    print_debug(debug, "fetch lineup from DEL")
    lineup, raw_json = helper.lineup_format(game_id, home_match)
    if not lineup:
        return ""

    store_lineup(match_id, lineup, raw_json, lineup_model=lineup_model)
    message = "{0}{1}".format(LINEUP_INTRO, lineup)
    guest_lineup, _raw = helper.lineup_format(game_id, not home_match, match_id)
    if guest_lineup:
        message = "{0}{1}{2}".format(message, GUEST_LINEUP_INTRO, guest_lineup)
    return message


def fetch_referee_message(
    debug,
    helper,
    game_id,
    match_id,
    referee_model=None,
    refpermatch_model=None,
):
    """Fetch, store, and format referees when they are not already stored."""
    if refs_exist(match_id, refpermatch_model=refpermatch_model):
        print_debug(debug, "we have a refs stored in db. Do nothing")
        return None

    ref_list, ref_dic = helper.reflist_get(game_id)
    names = head_referee_names(ref_dic)
    if names:
        store_referees(
            match_id,
            names,
            referee_model=referee_model,
            refpermatch_model=refpermatch_model,
        )
    return format_referee_message(ref_list)


def merge_announcement(lineup_text, referee_text):
    """Combine lineup and referee texts into one announcement body."""
    if lineup_text and referee_text:
        return "{0}\n{1}".format(lineup_text, referee_text)
    return lineup_text or referee_text


def format_outgoing_message(body):
    """Prefix the announcement with the group greeting."""
    return "{0}{1}".format(MESSAGE_GREETING, body)


def notify_configured(settings_obj):
    """Return True when WhatsApp settings used as the notify gate are present."""
    return (
        hasattr(settings_obj, "WA_ADMIN_NUMBER")
        and hasattr(settings_obj, "WA_SRV")
        and hasattr(settings_obj, "WA_PORT")
    )


def whatsapp_configured(settings_obj):
    """Return True if WhatsApp connection settings are present."""
    return hasattr(settings_obj, "WA_SRV") and hasattr(settings_obj, "WA_PORT")


def threema_configured(settings_obj):
    """Return True if Threema credentials are present."""
    return (
        hasattr(settings_obj, "TR_ID")
        and hasattr(settings_obj, "TR_SECRET")
        and hasattr(settings_obj, "TR_SK")
    )


def load_whatsapp_groups(groupsetting_model=None):
    """Load WhatsApp groups that should receive lineup alerts."""
    model = groupsetting_model or Groupsetting
    return [
        number
        for number in model.objects.filter(alert=True).values_list("number", flat=True)
        if number
    ]


def load_threema_users(usersetting_model=None):
    """Load Threema IDs that should receive lineup alerts."""
    model = usersetting_model or Usersetting
    return [
        threema_id
        for threema_id in model.objects.filter(threema_reminder=True).values_list(
            "threema", flat=True
        )
        if threema_id
    ]


def dispatch_whatsapp(settings_obj, groups, message, dry_run=False, send_fn=None):
    """Send a WhatsApp message, or print it during dry-run."""
    if dry_run:
        print("dry-run whatsapp {0}:\n{1}".format(groups, message))
        return
    sender = send_fn or simple_send
    sender(settings_obj.WA_SRV, settings_obj.WA_PORT, groups, message)


def dispatch_threema(settings_obj, receiver, message, dry_run=False, send_fn=None):
    """Send a Threema message, or print it during dry-run."""
    if dry_run:
        print("dry-run threema {0}:\n{1}".format(receiver, message))
        return
    sender = send_fn or send_threema
    sender(
        settings_obj.TR_ID,
        settings_obj.TR_SECRET,
        settings_obj.TR_SK,
        receiver,
        message,
    )


def notify_recipients(
    body,
    settings_obj,
    dry_run=False,
    groups=None,
    threema_users=None,
    wa_send_fn=None,
    threema_send_fn=None,
):
    """Send the lineup announcement, or print it during dry-run."""
    if not body:
        return False
    if not dry_run and not notify_configured(settings_obj):
        return False

    message = format_outgoing_message(body)
    if groups is None:
        groups = load_whatsapp_groups()
    if threema_users is None:
        threema_users = load_threema_users()

    groups_csv = ",".join(str(number) for number in groups)

    if dry_run:
        dispatch_whatsapp(
            settings_obj, groups_csv, message, dry_run=True, send_fn=wa_send_fn
        )
        for receiver in threema_users:
            dispatch_threema(
                settings_obj, receiver, message, dry_run=True, send_fn=threema_send_fn
            )
        return True

    if whatsapp_configured(settings_obj) and message and groups:
        dispatch_whatsapp(
            settings_obj, groups_csv, message, dry_run=False, send_fn=wa_send_fn
        )

    if threema_users and threema_configured(settings_obj):
        for receiver in threema_users:
            dispatch_threema(
                settings_obj,
                receiver,
                message,
                dry_run=False,
                send_fn=threema_send_fn,
            )
    return True


def run(
    debug=False,
    dry_run=False,
    now_uts=None,
    season_id=None,
    next_match_fn=None,
    last_match_fn=None,
    load_game_fn=None,
    helper_factory=None,
    fetch_lineup_fn=None,
    fetch_refs_fn=None,
    notify_fn=None,
    settings_obj=None,
    groups=None,
    threema_users=None,
    wa_send_fn=None,
    threema_send_fn=None,
):
    """Fetch lineup/referees for the current match and notify groups."""
    now_uts = int(time.time()) if now_uts is None else int(now_uts)
    season_id = load_season_id() if season_id is None else season_id
    next_match_fn = next_match_fn or get_next_match
    last_match_fn = last_match_fn or get_last_match
    load_game_fn = load_game_fn or load_match_game
    settings_obj = settings_obj or settings

    match_id, _match_date = select_current_match(
        now_uts,
        next_match_fn(now_uts, season_id),
        last_match_fn(now_uts, season_id),
        debug=debug,
    )
    game_id, home_match = load_game_fn(match_id)
    if home_match:
        print_debug(debug, "changing to HOME_MATCH")
    if not game_id:
        return EXIT_SUCCESS

    factory = helper_factory or create_del_app_helper
    fetch_lineup_fn = fetch_lineup_fn or fetch_lineup_message
    fetch_refs_fn = fetch_refs_fn or fetch_referee_message
    notify_fn = notify_fn or notify_recipients

    lineup_text = None
    referee_text = None
    with factory(debug) as helper:
        try:
            lineup_text = fetch_lineup_fn(debug, helper, game_id, home_match, match_id)
        except Exception as exc:
            print_debug(debug, "lineup fetch failed: {0}".format(exc))
            lineup_text = None
        try:
            referee_text = fetch_refs_fn(debug, helper, game_id, match_id)
        except Exception as exc:
            print_debug(debug, "referee fetch failed: {0}".format(exc))
            referee_text = None

    body = merge_announcement(lineup_text, referee_text)
    if not body:
        return EXIT_SUCCESS

    notify_fn(
        body,
        settings_obj,
        dry_run=dry_run,
        groups=groups,
        threema_users=threema_users,
        wa_send_fn=wa_send_fn,
        threema_send_fn=threema_send_fn,
    )
    return EXIT_SUCCESS


def main(argv=None):
    """CLI entry point."""
    args = parse_args(argv)
    try:
        return run(debug=args.debug, dry_run=args.dry_run)
    except Exception as exc:
        print("get_lineup failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
