#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Send tip reminders or matchday summaries via WhatsApp and Threema."""

from __future__ import absolute_import
from __future__ import print_function

import argparse
import os
import sys
import time

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth.models import Group, User
from game.models import Groupsetting, Season, Tip, Usersetting
from game.myfunctions import get_last_match, get_next_match, send_threema
from wa_hack_cli import simple_send

WHATSAPP_SLEEP_SECONDS = 2
EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Send tip reminders or summaries.")
    parser.add_argument(
        "-s",
        "--summary",
        action="store_true",
        help="send summary instead of reminders",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated messages instead of sending WhatsApp/Threema.",
    )
    return parser.parse_args(argv)


def build_tip_url(allowed_hosts):
    """Build the tip form URL from the first allowed host."""
    return "http://%s/game/tip" % (allowed_hosts[0])


def index_users_by_id(user_rows):
    """Map user id to username."""
    return {row["id"]: row["username"] for row in user_rows}


def index_tips_by_user_id(tip_rows):
    """Map user id to tip value."""
    return {row["user_id"]: row["tip"] for row in tip_rows}


def index_tips_by_username(tip_rows):
    """Map username to tip value."""
    return {row["user__username"]: row["tip"] for row in tip_rows}


def missing_tip_usernames(user_dic, tip_dic):
    """Return sorted usernames that have no tip yet."""
    return sorted(
        username for user_id, username in user_dic.items() if user_id not in tip_dic
    )


def build_group_summary_message(group_name, user_dic, tip_dic):
    """Build a WhatsApp group summary of all member tips."""
    message = (
        'Hallo,\nHier die Zusammenfassung der Tipps des heutigen Spieltages der Gruppe "%s" :\n'
        % group_name
    )
    for user_id, username in sorted(user_dic.items(), key=lambda item: item[1]):
        message = message + str(username) + ":"
        if user_id in tip_dic:
            message = "%s  %s\n" % (message, tip_dic[user_id])
        else:
            message = message + "  --\n"
    return message


def build_group_reminder_message(group_name, user_dic, tip_dic, url):
    """Build a WhatsApp reminder listing members without a tip."""
    alert_list = missing_tip_usernames(user_dic, tip_dic)
    if not alert_list:
        return None

    message = "Hallo,\nDas ist ein Erinnermich der Gruppe %s:\n" % group_name
    for username in alert_list:
        message = "%s - %s \n" % (message, username)
    return message + "Tippen nicht vergessen %s ..." % (url)


def build_threema_reminder_message(username, url):
    """Build a personal Threema reminder."""
    return (
        "Hallo %s. Das ist ein Erinnermich vom Dynamop-Tippspiel. Tippen nicht vergessen... %s"
        % (username, url)
    )


def build_threema_summary_message(username, group_sections):
    """Build a personal Threema summary across the user's groups.

    group_sections is a sequence of (group_name, username_to_id, tips_by_username).
    """
    message = (
        "Hallo %s. Hier die Zusamenfassung der Tips des heutigen Spieltages:\n"
        % (username)
    )
    for group_name, user_name_dic, tip_dic in group_sections:
        message = message + '\nGruppe "%s":\n' % group_name
        for member_name in user_name_dic:
            tip = " -"
            if member_name in tip_dic:
                tip = tip_dic[member_name]
            message = message + "%s: %s\n" % (member_name, tip)
    return message


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


def dispatch_whatsapp(settings_obj, number, message, dry_run=False, send_fn=None):
    """Send a WhatsApp message, or print it during dry-run."""
    recipient = number.lstrip("+")
    if dry_run:
        print("dry-run whatsapp {0}:\n{1}".format(recipient, message))
        return
    sender = send_fn or simple_send
    sender(settings_obj.WA_SRV, settings_obj.WA_PORT, recipient, message)


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


def resolve_match_id(uts, season_id, summary, next_match_fn=None, last_match_fn=None):
    """Return the match id used for reminders or summaries."""
    next_match = next_match_fn or get_next_match
    last_match = last_match_fn or get_last_match
    match_id, _date, _tv = next_match(uts, season_id)
    if summary:
        match_id, _date, _matchday = last_match(uts, season_id)
    return match_id


def load_season_id(season_model=None):
    """Return the current season id as used by the original script."""
    model = season_model or Season
    return len(model.objects.values())


def load_reminder_groups(groupsetting_model=None):
    """Load WhatsApp groups that should receive reminders."""
    model = groupsetting_model or Groupsetting
    return list(
        model.objects.filter(reminder=True).values("number", "group_id", "group__name")
    )


def load_group_users(group_name, user_model=None, name_in=True):
    """Load users belonging to a Django auth group."""
    model = user_model or User
    if name_in:
        queryset = model.objects.filter(groups__name__in=[group_name])
    else:
        queryset = model.objects.filter(groups__name=group_name)
    return list(queryset.values("username", "id"))


def load_tips(match_id, user_ids, tip_model=None):
    """Load tips for the given match and user ids."""
    model = tip_model or Tip
    return list(
        model.objects.filter(match_id=match_id, user_id__in=user_ids).values(
            "user__username", "user_id", "tip"
        )
    )


def user_has_tip(match_id, user_id, tip_model=None):
    """Return True if the user already stored a tip for the match."""
    model = tip_model or Tip
    return bool(
        model.objects.filter(match_id=match_id, user_id=user_id).values_list(
            "tip", flat=True
        )
    )


def load_threema_users(usersetting_model=None):
    """Load users who receive Threema reminders."""
    model = usersetting_model or Usersetting
    return list(
        model.objects.filter(threema_reminder=True).values(
            "user__username", "user_id", "threema"
        )
    )


def load_user_group_names(user_id, group_model=None):
    """Load non-admin group names for a user."""
    model = group_model or Group
    return list(
        model.objects.filter(user=user_id)
        .values_list("name", flat=True)
        .exclude(name__endswith="-adm")
    )


def notify_whatsapp_groups(
    groups,
    match_id,
    url,
    summary,
    settings_obj,
    dry_run=False,
    load_users_fn=None,
    load_tips_fn=None,
    send_fn=None,
    sleep_fn=None,
):
    """Notify configured WhatsApp groups with a reminder or summary."""
    load_users_fn = load_users_fn or (lambda name: load_group_users(name, name_in=True))
    load_tips_fn = load_tips_fn or load_tips
    sleep = sleep_fn or time.sleep

    for group in groups:
        if not group["number"]:
            continue

        user_rows = load_users_fn(group["group__name"])
        user_dic = index_users_by_id(user_rows)
        tip_rows = load_tips_fn(match_id, list(user_dic.keys()))
        tip_dic = index_tips_by_user_id(tip_rows)

        if summary:
            message = build_group_summary_message(
                group["group__name"], user_dic, tip_dic
            )
        else:
            message = build_group_reminder_message(
                group["group__name"], user_dic, tip_dic, url
            )

        if whatsapp_configured(settings_obj) and message and group["number"]:
            dispatch_whatsapp(
                settings_obj,
                group["number"],
                message,
                dry_run=dry_run,
                send_fn=send_fn,
            )

        if not dry_run:
            sleep(WHATSAPP_SLEEP_SECONDS)


def notify_threema_users(
    users,
    match_id,
    url,
    summary,
    settings_obj,
    dry_run=False,
    has_tip_fn=None,
    load_groups_fn=None,
    load_users_fn=None,
    load_tips_fn=None,
    send_fn=None,
):
    """Notify Threema users with a personal reminder or summary."""
    has_tip_fn = has_tip_fn or user_has_tip
    load_groups_fn = load_groups_fn or load_user_group_names
    load_users_fn = load_users_fn or (
        lambda name: load_group_users(name, name_in=False)
    )
    load_tips_fn = load_tips_fn or load_tips

    for user in users:
        message = ""
        if not summary:
            if not has_tip_fn(match_id, user["user_id"]):
                message = build_threema_reminder_message(user["user__username"], url)
        else:
            group_sections = []
            for group_name in load_groups_fn(user["user_id"]):
                user_rows = load_users_fn(group_name)
                user_name_dic = {}
                user_id_list = []
                for row in user_rows:
                    user_name_dic[row["username"]] = row["id"]
                    user_id_list.append(row["id"])
                tip_dic = index_tips_by_username(load_tips_fn(match_id, user_id_list))
                group_sections.append((group_name, user_name_dic, tip_dic))
            message = build_threema_summary_message(
                user["user__username"], group_sections
            )

        if threema_configured(settings_obj) and message:
            dispatch_threema(
                settings_obj,
                user["threema"],
                message,
                dry_run=dry_run,
                send_fn=send_fn,
            )


def run(
    argv=None,
    now_uts=None,
    settings_obj=None,
    next_match_fn=None,
    last_match_fn=None,
    simple_send_fn=None,
    send_threema_fn=None,
    sleep_fn=None,
    groups=None,
    threema_users=None,
    season_id=None,
):
    """Run reminder or summary notifications."""
    args = parse_args(argv)
    settings_obj = settings_obj or settings
    now_uts = int(time.time()) if now_uts is None else now_uts
    season_id = load_season_id() if season_id is None else season_id
    url = build_tip_url(settings_obj.ALLOWED_HOSTS)
    match_id = resolve_match_id(
        now_uts,
        season_id,
        args.summary,
        next_match_fn=next_match_fn,
        last_match_fn=last_match_fn,
    )

    if groups is None:
        groups = load_reminder_groups()
    notify_whatsapp_groups(
        groups,
        match_id,
        url,
        args.summary,
        settings_obj,
        dry_run=args.dry_run,
        send_fn=simple_send_fn,
        sleep_fn=sleep_fn,
    )

    if threema_users is None:
        threema_users = load_threema_users()
    notify_threema_users(
        threema_users,
        match_id,
        url,
        args.summary,
        settings_obj,
        dry_run=args.dry_run,
        send_fn=send_threema_fn,
    )
    return EXIT_SUCCESS


def main(argv=None):
    """CLI entry point."""
    try:
        return run(argv)
    except Exception as exc:
        print("tipp_reminder failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
