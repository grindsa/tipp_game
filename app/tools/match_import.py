#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Import DEL matches for a season into the database."""

from __future__ import absolute_import

import argparse
import calendar
import os
import sys
from collections import namedtuple
from datetime import datetime, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from game.models import Match, Season, Team
from game.myfunctions import print_debug

INVALID_START_DATE = "0000-00-00 00:00:00"
START_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LEAGUE_ID = 3
DEFAULT_TEAM_ID = 3
DEFAULT_SEASON_YEAR = 2025
DEFAULT_START_MATCHDAY = 52
# API timestamps are parsed as UTC; subtract 3h, then store with +1h.
API_TO_UTC_OFFSET_SECONDS = 10800
STORED_DATE_ADJUSTMENT_SECONDS = 3600
CFG_FILENAME = "delapphelper.cfg"

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1

TeamRef = namedtuple("TeamRef", "team_id team_name short_name del_team")
UNRESOLVED_TEAM = TeamRef(None, None, None, False)


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="match_import.py - update matches in database")
    parser.add_argument("-d", "--debug", help="debug mode", action="store_true", default=False)
    tsg = parser.add_mutually_exclusive_group()
    tsg.add_argument("-s", "--season", help="hockeygraphs season id", type=int, default=None)
    tsg.add_argument("-t", "--tournament", help="del season id", type=int, default=None)
    parser.add_argument("--year", type=int, default=DEFAULT_SEASON_YEAR, help="DEL season year")
    parser.add_argument("--league-id", type=int, default=DEFAULT_LEAGUE_ID, help="DEL league id")
    parser.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID, help="DEL app team id")
    parser.add_argument(
        "--start-matchday",
        type=int,
        default=DEFAULT_START_MATCHDAY,
        help="matchday value before the first imported match",
    )
    return parser.parse_args(argv)


def date_to_uts_utc(date_human, time_format=START_DATE_FORMAT):
    """Convert a naive datetime or formatted string to a UTC unix timestamp."""
    if isinstance(date_human, datetime):
        parsed = date_human
    else:
        parsed = datetime.strptime(date_human, time_format)
    return int(calendar.timegm(parsed.timetuple()))


def uts_now():
    """Return the current UTC unix timestamp in whole seconds."""
    return int(datetime.now(timezone.utc).timestamp())


def _as_team_ref(team):
    """Build a TeamRef from a team dictionary."""
    return TeamRef(
        team.get("team_id"),
        team.get("team_name"),
        team.get("short_name"),
        team.get("del_team", False),
    )


def lookup_team(team_list, team_label):
    """Resolve a team by shortcut, full name, or a name-token substring."""
    if not team_label:
        return UNRESOLVED_TEAM

    for team in team_list:
        if team.get("short_name") == team_label:
            return _as_team_ref(team)

    for team in team_list:
        if team.get("team_name") == team_label:
            return _as_team_ref(team)

    for team in team_list:
        for token in (team.get("team_name") or "").split():
            if token and (token in team_label or team_label in token):
                return _as_team_ref(team)

    return UNRESOLVED_TEAM


def resolve_season(season_id, tournament_id, season_list):
    """Fill season/tournament ids from the ordered season list when omitted."""
    if not season_list:
        raise ValueError("no seasons found")

    if season_id is None:
        season_id = len(season_list)

    if tournament_id is None:
        index = season_id - 1
        if index < 0 or index >= len(season_list):
            raise ValueError("season_id {0} is out of range".format(season_id))
        tournament_id = season_list[index]["tournament_id"]

    return season_id, tournament_id


def start_date_to_uts(start_date, time_format=START_DATE_FORMAT):
    """Convert an API start_date to the unix timestamp used for future checks."""
    if not start_date or start_date == INVALID_START_DATE:
        return None
    return date_to_uts_utc(start_date, time_format) - API_TO_UTC_OFFSET_SECONDS


def team_shortcut(match, side):
    """Return a home/guest shortcut from a schedule match dict."""
    side_info = match.get(side) or {}
    return side_info.get("shortcut")


def build_match_defaults(matchday, uts, home_team_id, guest_team_id, season_id, delapp_game_id):
    """Build the Match.defaults payload for update_or_create."""
    return {
        "matchday": matchday,
        "date": uts + STORED_DATE_ADJUSTMENT_SECONDS,
        "home_team_id": home_team_id,
        "guest_team_id": guest_team_id,
        "season_id": season_id,
        "no_bet": False,
        "playoff": False,
        "delapp_game_id": delapp_game_id,
    }


def extract_matches(schedule):
    """Return the match list from a gameschedule payload."""
    if not schedule:
        return []
    return schedule.get("matches") or []


def build_upcoming_match_updates(matches, team_list, season_id, now_uts, start_matchday=DEFAULT_START_MATCHDAY):
    """Collect persistable future matches while preserving matchday numbering.

    Matchdays advance for every resolved team pair, including past or invalid
    dates, so later future games keep stable matchday numbers.
    """
    updates = []
    matchday = start_matchday

    for match in matches:
        home = lookup_team(team_list, team_shortcut(match, "home"))
        guest = lookup_team(team_list, team_shortcut(match, "guest"))
        print("{0} {1}".format(home.team_name, guest.team_name))

        if not (home.team_id and guest.team_id):
            continue

        matchday += 1
        uts = start_date_to_uts(match.get("start_date"))
        if uts is None or now_uts > uts:
            continue

        updates.append(
            {
                "home_name": home.team_name,
                "guest_name": guest.team_name,
                "matchday": matchday,
                "defaults": build_match_defaults(
                    matchday,
                    uts,
                    home.team_id,
                    guest.team_id,
                    season_id,
                    match.get("id"),
                ),
            }
        )

    return updates


def persist_matches(updates, match_model=None):
    """Create or update Match rows for prepared upcoming games."""
    model = match_model or Match
    saved = []
    for item in updates:
        print("update_db: {0}: {1}".format(item["home_name"], item["guest_name"]))
        obj, created = model.objects.update_or_create(
            matchday=item["matchday"],
            season_id=item["defaults"]["season_id"],
            defaults=item["defaults"],
        )
        saved.append((obj, created))
    return saved


def default_config_path(script_file=None):
    """Return the default DelAppHelper config path next to this script."""
    script_file = script_file or __file__
    return os.path.join(os.path.dirname(script_file), CFG_FILENAME)


def create_del_app_helper(debug, cfg_file=None):
    """Create a DelAppHelper context manager."""
    from delapphelper import DelAppHelper

    return DelAppHelper(debug=debug, cfg_file=cfg_file or default_config_path())


def load_seasons(season_model=None):
    """Load seasons ordered by id."""
    model = season_model or Season
    return list(model.objects.order_by("id").values())


def load_teams(team_model=None):
    """Load team lookup fields used during import."""
    model = team_model or Team
    return list(model.objects.values("team_id", "team_name", "short_name", "del_team"))


def fetch_gameschedule(helper, year, league_id, team_id):
    """Fetch the match list for a tournament/team from the DEL app helper."""
    return extract_matches(helper.gameschedule_get(year, league_id, team_id))


def run(
    argv=None,
    now_uts=None,
    seasons=None,
    teams=None,
    helper_factory=None,
    match_model=None,
):
    """Import upcoming matches and return the number of persisted rows."""
    args = parse_args(argv)
    now_uts = uts_now() if now_uts is None else now_uts
    seasons = load_seasons() if seasons is None else list(seasons)
    teams = load_teams() if teams is None else list(teams)

    season_id, tournament_id = resolve_season(args.season, args.tournament, seasons)
    print_debug(args.debug, "season_id: {0}, tournament_id: {1}".format(season_id, tournament_id))

    factory = helper_factory or create_del_app_helper
    with factory(args.debug) as helper:
        matches = fetch_gameschedule(helper, args.year, args.league_id, args.team_id)

    updates = build_upcoming_match_updates(
        matches,
        teams,
        season_id,
        now_uts,
        start_matchday=args.start_matchday,
    )
    persist_matches(updates, match_model=match_model)
    return len(updates)


def main(argv=None):
    """CLI entry point."""
    try:
        imported = run(argv)
    except Exception as exc:
        print("match_import failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR

    print("imported {0} upcoming matches".format(imported))
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
