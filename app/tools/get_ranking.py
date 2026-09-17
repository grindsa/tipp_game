#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch DEL standings and store them in the ranking table."""

from __future__ import absolute_import

import argparse
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from game.models import Ranking, Season, Team
from game.myfunctions import get_last_match, lookup_team, print_debug

try:
    from wa_hack_cli import simple_send
except ImportError:
    from game.wa_hack_cli import simple_send

CFG_FILENAME = "delapphelper.cfg"
DEFAULT_TABLE_ID = 37
DEFAULT_FAIRPLAY_YEAR = 2026
DEFAULT_LEAGUE_ID = 1
RANKING_TYPE = "all"
SOURCE_NAME = "get_del_ranking.py"
NOTIFY_WINDOW_SECONDS = 86400

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch DEL standings and store them in the ranking table."
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=False,
        help="Enable extra logging.",
    )
    parser.add_argument(
        "-s",
        "--season-id",
        type=int,
        default=None,
        help="Season id (default: number of Season rows).",
    )
    parser.add_argument(
        "--table-id",
        type=int,
        default=DEFAULT_TABLE_ID,
        help="DEL standings table id (default: {0}).".format(DEFAULT_TABLE_ID),
    )
    parser.add_argument(
        "--year",
        type=int,
        default=DEFAULT_FAIRPLAY_YEAR,
        help="DEL season year used for the fairplay ranking (default: {0}).".format(
            DEFAULT_FAIRPLAY_YEAR
        ),
    )
    return parser.parse_args(argv)


def load_season_id(season_model=None):
    """Return the current season id."""
    model = season_model or Season
    return len(list(model.objects.values()))


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


def load_teams(team_model=None):
    """Load team lookup fields used while importing standings."""
    model = team_model or Team
    return list(model.objects.values("team_id", "team_name", "short_name"))


def fairplay_penalties(helper, year, league_id=DEFAULT_LEAGUE_ID):
    """Return penalty minutes keyed by DEL team id."""
    rows = helper.fairplay_ranking_get(str(year), league_id) or []
    penalties = {}
    for row in rows:
        team_id = row.get("teamId")
        if team_id is None:
            continue
        minutes = (row.get("penaltyMinutes") or {}).get("total") or 0
        penalties[team_id] = minutes
    return penalties


def fetch_standings_table(helper, table_id):
    """Return the standings table list from the DEL app helper."""
    ranking = helper.standings_get(table_id=table_id) or {}
    return ranking.get("table") or []


def build_ranking_defaults(team, team_id, season_id, uts, penalty):
    """Build the Ranking.defaults payload for update_or_create."""
    return {
        "season_id": season_id,
        "ranking": int(team["position"]),
        "team_id": team_id,
        "match": int(team["games"]),
        "won": int(team["wins"]),
        "wono": int(team["onlyOTwins"]),
        "wonp": int(team["onlySOwins"]),
        "losto": int(team["onlyOTlosts"]),
        "lostp": int(team["onlyOTlosts"]),
        "goal": int(team["score1"]),
        "ggoal": int(team["score2"]),
        "score": int(team["points"]),
        "uts": uts,
        "penalty": penalty,
        "source": SOURCE_NAME,
        "type": RANKING_TYPE,
    }


def persist_ranking(match_id, team, team_id, season_id, uts, penalty, ranking_model=None):
    """Create or update a ranking row for one team."""
    model = ranking_model or Ranking
    defaults = build_ranking_defaults(team, team_id, season_id, uts, penalty)
    return model.objects.update_or_create(
        matchday_id=match_id,
        ranking=int(team["position"]),
        type=RANKING_TYPE,
        defaults=defaults,
    )


def format_ranking_line(position, short_name, team_name):
    """Format one standings line for the admin message."""
    return "{0}: {1} - {2}".format(position, short_name, team_name)


def format_admin_message(match_day, ranking_lines):
    """Build the WhatsApp admin summary."""
    message = "*get_ranking.py*\n\n{0}.Spieltag:\n\nall:\n".format(match_day)
    for line in ranking_lines:
        message = "{0}{1}\n".format(message, line)
    return message


def whatsapp_configured(settings_obj):
    """Return True if WhatsApp admin notification settings are present."""
    return (
        hasattr(settings_obj, "WA_SRV")
        and hasattr(settings_obj, "WA_PORT")
        and getattr(settings_obj, "WA_ADMIN_NUMBER", None)
    )


def within_notify_window(now_uts, match_date, window=NOTIFY_WINDOW_SECONDS):
    """Return True if the last match is recent enough to notify."""
    if match_date is None:
        return False
    return int(now_uts) < int(match_date) + window


def notify_admin(message, settings_obj, send_fn=None):
    """Send the ranking summary to the WhatsApp admin number."""
    if not message or not whatsapp_configured(settings_obj):
        return False
    sender = send_fn or simple_send
    sender(
        settings_obj.WA_SRV,
        settings_obj.WA_PORT,
        settings_obj.WA_ADMIN_NUMBER,
        message,
    )
    return True


def can_store_ranking(team_id, match_id, match_day):
    """Return True when a ranking row can be stored for the last match."""
    return bool(team_id and match_id and match_day and match_day > 0)


def import_standings(
    table,
    team_list,
    match_id,
    match_day,
    season_id,
    uts,
    penalties,
    lookup_fn=None,
    ranking_model=None,
):
    """Persist standings rows and return formatted ranking lines."""
    lookup_fn = lookup_fn or lookup_team
    ranking_lines = []
    for team in table:
        team_id, _team_name, short_name = lookup_fn(team_list, team.get("name"))
        if not can_store_ranking(team_id, match_id, match_day):
            continue
        penalty = penalties.get(team.get("id"), 0)
        persist_ranking(
            match_id,
            team,
            team_id,
            season_id,
            uts,
            penalty,
            ranking_model=ranking_model,
        )
        ranking_lines.append(
            format_ranking_line(team.get("position"), short_name, team.get("name"))
        )
    return ranking_lines


def run(
    argv=None,
    now_uts=None,
    season_id=None,
    teams=None,
    last_match=None,
    helper_factory=None,
    ranking_model=None,
    lookup_fn=None,
    last_match_fn=None,
    settings_obj=None,
    send_fn=None,
):
    """Fetch standings, store ranking rows, and notify the admin."""
    args = parse_args(argv)
    now_uts = int(time.time()) if now_uts is None else int(now_uts)
    if args.season_id is not None:
        season_id = args.season_id
    elif season_id is None:
        season_id = load_season_id()

    teams = load_teams() if teams is None else list(teams)
    last_match_fn = last_match_fn or get_last_match
    if last_match is None:
        last_match = last_match_fn(now_uts, season_id)
    match_id, match_date, match_day = last_match
    settings_obj = settings_obj or settings

    print_debug(
        args.debug,
        "season_id={0} table_id={1} year={2} match_id={3} match_day={4}".format(
            season_id, args.table_id, args.year, match_id, match_day
        ),
    )

    factory = helper_factory or create_del_app_helper
    with factory(args.debug) as helper:
        penalties = fairplay_penalties(helper, args.year, DEFAULT_LEAGUE_ID)
        table = fetch_standings_table(helper, args.table_id)

    ranking_lines = import_standings(
        table,
        teams,
        match_id,
        match_day,
        season_id,
        now_uts,
        penalties,
        lookup_fn=lookup_fn,
        ranking_model=ranking_model,
    )

    if whatsapp_configured(settings_obj) and within_notify_window(now_uts, match_date):
        notify_admin(
            format_admin_message(match_day, ranking_lines),
            settings_obj,
            send_fn=send_fn,
        )
    return ranking_lines


def main(argv=None):
    """CLI entry point."""
    try:
        ranking_lines = run(argv)
    except Exception as exc:
        print("get_ranking failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR

    print("stored {0} ranking rows".format(len(ranking_lines)))
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
