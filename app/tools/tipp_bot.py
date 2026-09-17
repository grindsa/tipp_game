#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Place a fixed tip for a configured user and notify them via WhatsApp."""

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
from django.contrib.auth.models import User
from game.models import Match, Ranking, Season, Tip
from game.myfunctions import get_last_match, get_next_match
from wa_hack_cli import simple_send

BOOT_EMOJI = b"\xF0\x9F\x98\xB7".decode()
LUSER_BOT = "Josi-Bot"
EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1

PROFILES = {
    "josi": {
        "username": "Josi",
        "mobile": "+491723922673",
        "home_tip": "4:2",
        "away_tip": "2:4",
    },
    "hendrik": {
        "username": "Hendrik",
        "mobile": "+4917672607130",
        "home_tip": "3:2",
        "away_tip": "2:3",
    },
}


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Place a configured user's tip and send a WhatsApp notice."
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES.keys()),
        required=True,
        help="Bot profile to run (username, mobile number, and tip values).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the tip and WhatsApp message without writing or sending.",
    )
    return parser.parse_args(argv)


def load_season_id(season_model=None):
    """Return the current season id as used by the original bots."""
    model = season_model or Season
    return len(model.objects.values())


def load_user_id(username, user_model=None):
    """Return the first matching user id, or None."""
    model = user_model or User
    user_ids = list(model.objects.filter(username=username).values_list("id", flat=True)[:1])
    if not user_ids:
        return None
    return user_ids[0]


def load_match_rows(match_id, match_model=None):
    """Load the next-match row used to pick home/away tips."""
    model = match_model or Match
    return list(
        model.objects.filter(id=match_id).values(
            "date",
            "matchday",
            "home_team__short_name",
            "guest_team__short_name",
            "home_team__team_name",
            "guest_team__team_name",
        )[:1]
    )


def load_ranking_rows(last_match_id, ranking_model=None):
    """Load overall ranking rows for the previous matchday."""
    model = ranking_model or Ranking
    return list(
        model.objects.filter(matchday__id=last_match_id, type="all")
        .order_by("ranking")
        .values("ranking", "team__short_name")
    )


def choose_tip_and_opponent(match_rows, home_tip, away_tip):
    """Pick the EBB home/away tip and opponent name from match rows."""
    tip = None
    opponent = None
    home_short = None
    guest_short = None

    try:
        home_short = match_rows[0]["home_team__short_name"]
        guest_short = match_rows[0]["guest_team__short_name"]
    except (IndexError, KeyError, TypeError):
        home_short = None
        guest_short = None

    for match in match_rows:
        if match["home_team__short_name"] == "EBB":
            tip = home_tip
            opponent = match["guest_team__team_name"]
        elif match["guest_team__short_name"] == "EBB":
            tip = away_tip
            opponent = match["home_team__team_name"]

    return tip, opponent, home_short, guest_short


def rankings_for_match(ranking_rows, home_short, guest_short):
    """Return (ebb_ranking, opponent_ranking) for the current match."""
    home_ranking = None
    guest_ranking = None
    for row in ranking_rows:
        if row["team__short_name"] == home_short:
            home_ranking = row["ranking"]
        elif row["team__short_name"] == guest_short:
            guest_ranking = row["ranking"]

    if home_short == "EBB":
        return home_ranking, guest_ranking
    return guest_ranking, home_ranking


def build_message(username, opponent, tip, ebb_ranking, opponent_ranking):
    """Build the WhatsApp notice, including rankings when both are set."""
    if ebb_ranking and opponent_ranking:
        return (
            'Hallo {0},\n\nWir spielen heute gegen {1} und du hast gerade {2} getippt.\n\n'
            'Liebe Grüße\nDas Boot {3}\n\nPS: Wir sind übrigens auf Platz {4}, "{1}" auf Platz {5}...'
        ).format(username, opponent, tip, BOOT_EMOJI, ebb_ranking, opponent_ranking)
    return (
        "Hallo {0},\n\nWir spielen heute gegen {1} und du hast gerade {2} getippt.\n\n"
        "Liebe Grüße\nDas Boot {3}\n"
    ).format(username, opponent, tip, BOOT_EMOJI)


def build_tip_defaults(match_id, tip, user_id, now_uts):
    """Build Tip.defaults for update_or_create."""
    return {
        "match_id": match_id,
        "tip": tip,
        "user_id": user_id,
        "date": now_uts,
        "luser": LUSER_BOT,
    }


def persist_tip(match_id, user_id, defaults, tip_model=None):
    """Create or update the user's tip."""
    model = tip_model or Tip
    obj, created = model.objects.update_or_create(
        match_id=match_id, user_id=user_id, defaults=defaults
    )
    return obj, created


def whatsapp_configured(settings_obj):
    """Return True if WhatsApp connection settings are present."""
    return hasattr(settings_obj, "WA_SRV") and hasattr(settings_obj, "WA_PORT")


def dispatch_whatsapp(settings_obj, mobile, message, dry_run=False, send_fn=None):
    """Send a WhatsApp message, or print it during dry-run."""
    if dry_run:
        print("dry-run whatsapp {0}:\n{1}".format(mobile, message))
        return
    sender = send_fn or simple_send
    sender(settings_obj.WA_SRV, settings_obj.WA_PORT, mobile, message)


def place_and_notify(
    profile,
    now_uts,
    settings_obj,
    dry_run=False,
    next_match_fn=None,
    last_match_fn=None,
    load_user_id_fn=None,
    load_match_rows_fn=None,
    load_ranking_rows_fn=None,
    persist_fn=None,
    send_fn=None,
    season_id=None,
):
    """Place the profile tip and notify the user if the account exists."""
    user_id = (load_user_id_fn or load_user_id)(profile["username"])
    if not user_id:
        return EXIT_SUCCESS

    season_id = load_season_id() if season_id is None else season_id
    next_match = next_match_fn or get_next_match
    last_match = last_match_fn or get_last_match
    match_id, _match_date, _tv = next_match(now_uts, season_id)
    last_match_id, _last_date, _last_day = last_match(now_uts, season_id)

    match_rows = (load_match_rows_fn or load_match_rows)(match_id)
    tip, opponent, home_short, guest_short = choose_tip_and_opponent(
        match_rows, profile["home_tip"], profile["away_tip"]
    )
    ranking_rows = (load_ranking_rows_fn or load_ranking_rows)(last_match_id)
    ebb_ranking, opponent_ranking = rankings_for_match(
        ranking_rows, home_short, guest_short
    )

    if tip:
        defaults = build_tip_defaults(match_id, tip, user_id, now_uts)
        if dry_run:
            print(
                "dry-run tip user={0} match_id={1} tip={2}".format(
                    profile["username"], match_id, tip
                )
            )
        else:
            saver = persist_fn or persist_tip
            saver(match_id, user_id, defaults)

    message = build_message(
        profile["username"], opponent, tip, ebb_ranking, opponent_ranking
    )
    if whatsapp_configured(settings_obj):
        dispatch_whatsapp(
            settings_obj, profile["mobile"], message, dry_run=dry_run, send_fn=send_fn
        )
    return EXIT_SUCCESS


def run(argv=None, now_uts=None, settings_obj=None, **kwargs):
    """Run a bot profile."""
    args = parse_args(argv)
    profile = PROFILES[args.profile]
    return place_and_notify(
        profile,
        int(time.time()) if now_uts is None else now_uts,
        settings_obj or settings,
        dry_run=args.dry_run,
        **kwargs
    )


def main(argv=None):
    """CLI entry point."""
    try:
        return run(argv)
    except Exception as exc:
        print("tipp_bot failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
