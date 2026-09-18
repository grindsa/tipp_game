#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch live DEL standings from the Livescore API and store them."""

from __future__ import absolute_import

import argparse
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from game.models import Delmatch, Ranking, Season, Team
from game.myfunctions import get_last_match, get_next_match, lookup_team, print_debug

DEFAULT_API_URL = (
    "https://prod-cdn-public-api.lsmedia1.com/v1/api/app/stage/"
    "hockey/germany/del/2?countryCode=DE&locale=en"
)
HTTP_TIMEOUT_SECONDS = 20
RANKING_TYPE = "all"
OVERALL_TABLE_TYPE = 1
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "tipp_game/get_life_ranking",
}
MATCH_TIMEZONE = ZoneInfo("Europe/Berlin")
DAY_FORMAT = "%Y-%m-%d"
RESULT_NOT_STARTED = "-"
STATUS_FINISHED = "beendet"
STATUS_LIVE = "LIVE"
EPS_NOT_STARTED = "NS"
EPS_FINISHED = "FT"

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1


def parse_day_value(value):
    """Validate a YYYY-MM-DD CLI day value."""
    try:
        datetime.strptime(value, DAY_FORMAT)
    except ValueError:
        raise argparse.ArgumentTypeError("day must be YYYY-MM-DD")
    return value


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch live DEL standings from the Livescore API and store them."
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=False,
        help="Log each step with important inputs and outputs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ranking and match rows instead of writing the database.",
    )
    parser.add_argument(
        "-s",
        "--season-id",
        type=int,
        default=None,
        help="Season id (default: number of Season rows).",
    )
    parser.add_argument(
        "--day",
        type=parse_day_value,
        default=None,
        help="Filter DEL matches for this day (YYYY-MM-DD, default: today in Europe/Berlin).",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_API_URL,
        help="Livescore standings API URL.",
    )
    return parser.parse_args(argv)


def script_filename(script_file=None):
    """Return the script basename used in Ranking.source."""
    return os.path.basename(script_file or __file__)


def as_int(value, default=0):
    """Convert API numeric fields to int, including numeric strings."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def today_berlin(now_uts=None, tzinfo=None, debug=False):
    """Return today's date in Europe/Berlin as YYYY-MM-DD."""
    tzinfo = tzinfo or MATCH_TIMEZONE
    if now_uts is None:
        current = datetime.now(tzinfo)
    else:
        current = datetime.fromtimestamp(int(now_uts), tz=tzinfo)
    day = current.strftime(DAY_FORMAT)
    print_debug(debug, "today_berlin now_uts={0} -> {1}".format(now_uts, day))
    return day


def resolve_day(day_arg, now_uts=None, debug=False):
    """Return the CLI day, or today in Europe/Berlin."""
    if day_arg:
        print_debug(debug, "resolve_day cli={0}".format(day_arg))
        return day_arg
    day = today_berlin(now_uts=now_uts, debug=debug)
    print_debug(debug, "resolve_day today={0}".format(day))
    return day


def esd_text(esd):
    """Normalize an Esd value to a digit string."""
    return str(esd or "").strip()


def esd_day(esd, debug=False):
    """Return YYYY-MM-DD from a Livescore Esd timestamp."""
    text = esd_text(esd)
    if len(text) < 8 or not text[:8].isdigit():
        print_debug(debug, "esd_day invalid esd={0}".format(esd))
        return None
    day = "{0}-{1}-{2}".format(text[0:4], text[4:6], text[6:8])
    print_debug(debug, "esd_day esd={0} -> {1}".format(esd, day))
    return day


def esd_kickoff_time(esd, debug=False):
    """Return HH:MM from a Livescore Esd timestamp."""
    text = esd_text(esd)
    if len(text) < 12 or not text[8:12].isdigit():
        print_debug(debug, "esd_kickoff_time invalid esd={0}".format(esd))
        return ""
    kickoff = "{0}:{1}".format(text[8:10], text[10:12])
    print_debug(debug, "esd_kickoff_time esd={0} -> {1}".format(esd, kickoff))
    return kickoff


def esd_to_uts(esd, tzinfo=None, debug=False):
    """Convert a Livescore Esd value to a unix timestamp in Europe/Berlin."""
    text = esd_text(esd)
    tzinfo = tzinfo or MATCH_TIMEZONE
    if len(text) >= 14:
        formats = ("%Y%m%d%H%M%S", "%Y%m%d%H%M")
    else:
        formats = ("%Y%m%d%H%M",)
    parsed = None
    for time_format in formats:
        try:
            parsed = datetime.strptime(text, time_format)
            break
        except ValueError:
            continue
    if parsed is None:
        print_debug(debug, "esd_to_uts invalid esd={0}".format(esd))
        return None
    uts = int(parsed.replace(tzinfo=tzinfo).timestamp())
    print_debug(debug, "esd_to_uts esd={0} -> {1}".format(esd, uts))
    return uts


def load_season_id(season_model=None, debug=False):
    """Return the current season id."""
    model = season_model or Season
    season_id = len(list(model.objects.values()))
    print_debug(debug, "load_season_id -> {0}".format(season_id))
    return season_id


def load_del_teams(team_model=None, debug=False):
    """Load DEL teams used for name lookup."""
    model = team_model or Team
    teams = list(
        model.objects.filter(del_team=True).values("team_id", "team_name", "short_name")
    )
    print_debug(debug, "load_del_teams count={0}".format(len(teams)))
    return teams


def fetch_json(url, timeout=HTTP_TIMEOUT_SECONDS, get_fn=None, debug=False):
    """Fetch and decode the Livescore JSON payload."""
    print_debug(debug, "fetch_json url={0} timeout={1}".format(url, timeout))
    getter = get_fn or requests.get
    response = getter(url, timeout=timeout, headers=HTTP_HEADERS)
    response.raise_for_status()
    payload = response.json()
    stage_count = len(payload.get("Stages") or []) if isinstance(payload, dict) else None
    print_debug(
        debug,
        "fetch_json status={0} stage_count={1}".format(
            getattr(response, "status_code", None), stage_count
        ),
    )
    return payload


def extract_league_teams(payload, debug=False):
    """Return overall-table team rows from a Livescore stage payload."""
    stages = payload.get("Stages") or [] if isinstance(payload, dict) else []
    if not stages:
        print_debug(debug, "extract_league_teams: no Stages")
        return []

    stage = stages[0]
    league_table = stage.get("LeagueTable") or stage.get("League-Table") or {}
    leagues = league_table.get("L") or []
    if not leagues:
        print_debug(debug, "extract_league_teams: no league tables")
        return []

    first_league = leagues[0]
    tables = first_league.get("Tables") or []
    selected = None
    for table in tables:
        if table.get("LTT") == OVERALL_TABLE_TYPE:
            selected = table
            break
    if selected is None and tables:
        selected = tables[0]

    teams = []
    if selected:
        teams = selected.get("team") or []
    elif first_league.get("team"):
        teams = first_league.get("team") or []

    print_debug(
        debug,
        "extract_league_teams tables={0} team_count={1}".format(
            len(tables), len(teams)
        ),
    )
    return teams


def extract_events(payload, debug=False):
    """Return match events from a Livescore stage payload."""
    stages = payload.get("Stages") or [] if isinstance(payload, dict) else []
    if not stages:
        print_debug(debug, "extract_events: no Stages")
        return []
    events = stages[0].get("Events") or []
    print_debug(debug, "extract_events count={0}".format(len(events)))
    return events


def filter_events_for_day(events, day, debug=False):
    """Return events whose Esd date matches YYYY-MM-DD."""
    selected = []
    for event in events or []:
        event_day = esd_day(event.get("Esd"))
        if event_day == day:
            print_debug(
                debug,
                "filter_events_for_day keep esd={0}".format(event.get("Esd")),
            )
            selected.append(event)
    print_debug(
        debug,
        "filter_events_for_day day={0} matched={1}/{2}".format(
            day, len(selected), len(events or [])
        ),
    )
    return selected


def team_name_from_side(side, debug=False):
    """Return the team name from a T1/T2 Livescore node."""
    name = ""
    if isinstance(side, list) and side:
        name = side[0].get("Nm") or ""
    elif isinstance(side, dict):
        name = side.get("Nm") or ""
    print_debug(debug, "team_name_from_side side={0} -> {1}".format(side, name))
    return name


def parse_event_result(event, debug=False):
    """Return 'home:guest', or '-' when the match has not started."""
    if event.get("Tr1") is None or event.get("Tr2") is None:
        print_debug(debug, "parse_event_result missing scores -> {0}".format(RESULT_NOT_STARTED))
        return RESULT_NOT_STARTED
    result = "{0}:{1}".format(as_int(event.get("Tr1")), as_int(event.get("Tr2")))
    print_debug(debug, "parse_event_result -> {0}".format(result))
    return result


def parse_event_status(event, debug=False):
    """Map Livescore Eps onto the Delmatch.status values used by the live page."""
    eps = str(event.get("Eps") or "").upper()
    if eps == EPS_FINISHED:
        status = STATUS_FINISHED
    elif eps == EPS_NOT_STARTED:
        status = esd_kickoff_time(event.get("Esd")) or EPS_NOT_STARTED
    else:
        status = STATUS_LIVE
    print_debug(debug, "parse_event_status eps={0} -> {1}".format(eps, status))
    return status


def parse_event(event, debug=False):
    """Map one Livescore event onto Delmatch fields."""
    parsed = {
        "home_name": team_name_from_side(event.get("T1")),
        "guest_name": team_name_from_side(event.get("T2")),
        "result": parse_event_result(event, debug=debug),
        "status": parse_event_status(event, debug=debug),
        "esd": event.get("Esd"),
        "kickoff": esd_kickoff_time(event.get("Esd")),
        "date": esd_to_uts(event.get("Esd"), debug=debug),
    }
    print_debug(debug, "parse_event -> {0}".format(parsed))
    return parsed


def parse_team_row(team, fallback_rank=None, debug=False):
    """Map one Livescore team node onto ranking fields."""
    ranking = as_int(team.get("rnk", team.get("rank", fallback_rank)), default=0)
    parsed = {
        "ranking": ranking,
        "team_name": team.get("Tnm") or team.get("Tmn") or "",
        "score": as_int(team.get("ptsn", team.get("pts"))),
        "goal": as_int(team.get("gf")),
        "ggoal": as_int(team.get("ga")),
        "won": as_int(team.get("win")),
        "match": as_int(team.get("pld")),
    }
    print_debug(debug, "parse_team_row input={0} -> {1}".format(team, parsed))
    return parsed


def select_ranking_match(now_uts, last_match, next_match, debug=False):
    """Prefer the next matchday when its kickoff is closer than the last one."""
    match_id, match_date, match_day = last_match
    next_id, next_date, _next_tv = next_match
    print_debug(
        debug,
        "select_ranking_match now={0} last={1} next={2}".format(
            now_uts, last_match, next_match
        ),
    )
    if (
        next_id
        and next_date is not None
        and match_date is not None
        and abs(int(now_uts) - int(next_date)) < abs(int(now_uts) - int(match_date))
    ):
        selected = (next_id, next_date, int(match_day or 0) + 1)
        print_debug(debug, "kick-in: {0}:{1}".format(next_id, selected[2]))
        return selected
    selected = (match_id, match_date, match_day)
    print_debug(debug, "select_ranking_match -> {0}".format(selected))
    return selected


def build_ranking_defaults(row, team_id, season_id, uts, source):
    """Build the Ranking.defaults payload for update_or_create."""
    return {
        "season_id": season_id,
        "ranking": row["ranking"],
        "team_id": team_id,
        "match": row["match"],
        "won": row["won"],
        "goal": row["goal"],
        "ggoal": row["ggoal"],
        "score": row["score"],
        "uts": uts,
        "source": source,
        "type": RANKING_TYPE,
    }


def persist_ranking(
    match_id, row, team_id, season_id, uts, source, ranking_model=None, dry_run=False
):
    """Create or update a ranking row, or skip writes during dry-run."""
    defaults = build_ranking_defaults(row, team_id, season_id, uts, source)
    if dry_run:
        return None, False
    model = ranking_model or Ranking
    return model.objects.update_or_create(
        matchday_id=match_id,
        ranking=row["ranking"],
        defaults=defaults,
    )


def format_ranking_line(row, short_name, team_name):
    """Format one standings line for logs and summaries."""
    return "{0}: {1} - {2} P{3} {4}:{5}".format(
        row["ranking"],
        short_name,
        team_name,
        row["score"],
        row["goal"],
        row["ggoal"],
    )


def _cell(value, width, numeric=False):
    """Pad one table cell."""
    text = "" if value is None else str(value)
    if numeric:
        return text.rjust(width)
    return text.ljust(width)


def format_dry_run_table(rows, match_id, season_id, uts, source):
    """Render a readable standings table for dry-run output."""
    header = [
        "dry-run ranking (database not updated)",
        "Matchday: {0}    Season: {1}    UTS: {2}    Source: {3}".format(
            match_id, season_id, uts, source
        ),
        "",
    ]
    if not rows:
        return "\n".join(header + ["No ranking rows to store."])

    team_width = max(4, max(len(str(row.get("team_name") or "")) for row in rows))
    short_width = max(5, max(len(str(row.get("short_name") or "")) for row in rows))
    columns = (
        ("#", "ranking", 2, True),
        ("Team", "team_name", team_width, False),
        ("Short", "short_name", short_width, False),
        ("ID", "team_id", 4, True),
        ("GP", "match", 3, True),
        ("W", "won", 3, True),
        ("GF", "goal", 3, True),
        ("GA", "ggoal", 3, True),
        ("Pts", "score", 3, True),
    )

    def format_row(values):
        cells = []
        for index, column in enumerate(columns):
            _title, _key, width, numeric = column
            cells.append(_cell(values[index], width, numeric=numeric))
        return " | ".join(cells)

    titles = [column[0] for column in columns]
    separator = "-+-".join("-" * column[2] for column in columns)
    lines = header + [format_row(titles), separator]
    for row in rows:
        lines.append(format_row([row.get(column[1]) for column in columns]))
    return "\n".join(lines)


def format_dry_run_match_table(rows, day, match_day, season_id, uts):
    """Render a readable match table for dry-run output."""
    header = [
        "dry-run del matches (database not updated)",
        "Day: {0}    Matchday: {1}    Season: {2}    UTS: {3}".format(
            day, match_day, season_id, uts
        ),
        "",
    ]
    if not rows:
        return "\n".join(header + ["No del matches to store."])

    home_width = max(4, max(len(str(row.get("home_name") or "")) for row in rows))
    guest_width = max(5, max(len(str(row.get("guest_name") or "")) for row in rows))
    status_width = max(6, max(len(str(row.get("status") or "")) for row in rows))
    columns = (
        ("Time", "kickoff", 5, True),
        ("Home", "home_name", home_width, False),
        ("H", "home_short", 5, False),
        ("Guest", "guest_name", guest_width, False),
        ("G", "guest_short", 5, False),
        ("Result", "result", 6, True),
        ("Status", "status", status_width, False),
    )

    def format_row(values):
        cells = []
        for index, column in enumerate(columns):
            _title, _key, width, numeric = column
            cells.append(_cell(values[index], width, numeric=numeric))
        return " | ".join(cells)

    titles = [column[0] for column in columns]
    separator = "-+-".join("-" * column[2] for column in columns)
    lines = header + [format_row(titles), separator]
    for row in rows:
        lines.append(format_row([row.get(column[1]) for column in columns]))
    return "\n".join(lines)


def can_store_ranking(team_id, team_name, match_id):
    """Return True when a ranking row can be stored."""
    return bool(team_id and team_name and match_id)


def format_lookup_warning(api_name, ranking=None):
    """Return a warning for a failed team-name lookup."""
    name = api_name or "<empty>"
    if ranking is None:
        return "warning: lookup_team failed for '{0}'".format(name)
    return "warning: lookup_team failed for '{0}' (ranking {1})".format(name, ranking)


def import_standings(
    teams,
    team_list,
    match_id,
    season_id,
    uts,
    source,
    debug=False,
    dry_run=False,
    lookup_fn=None,
    ranking_model=None,
):
    """Persist standings rows and return formatted ranking lines."""
    lookup_fn = lookup_fn or lookup_team
    ranking_lines = []
    dry_run_rows = []
    print_debug(
        debug,
        "import_standings teams={0} match_id={1} season_id={2} dry_run={3}".format(
            len(teams), match_id, season_id, dry_run
        ),
    )
    for index, team in enumerate(teams, start=1):
        row = parse_team_row(team, fallback_rank=index, debug=debug)
        team_id, team_name, short_name = lookup_fn(team_list, row["team_name"])
        print_debug(
            debug,
            "lookup {0} -> id={1} name={2} short={3}".format(
                row["team_name"], team_id, team_name, short_name
            ),
        )
        if team_id is None:
            print(format_lookup_warning(row["team_name"], row["ranking"]))
            print_debug(debug, "skip row={0}".format(row))
            continue
        if not can_store_ranking(team_id, row["team_name"], match_id):
            print_debug(debug, "skip row={0}".format(row))
            continue
        persist_ranking(
            match_id,
            row,
            team_id,
            season_id,
            uts,
            source,
            ranking_model=ranking_model,
            dry_run=dry_run,
        )
        ranking_lines.append(format_ranking_line(row, short_name, team_name))
        dry_run_rows.append(
            {
                "ranking": row["ranking"],
                "team_name": team_name,
                "short_name": short_name,
                "team_id": team_id,
                "match": row["match"],
                "won": row["won"],
                "goal": row["goal"],
                "ggoal": row["ggoal"],
                "score": row["score"],
            }
        )
    if dry_run:
        print(format_dry_run_table(dry_run_rows, match_id, season_id, uts, source))
    print_debug(debug, "import_standings stored={0}".format(len(ranking_lines)))
    return ranking_lines


def can_store_delmatch(home_id, guest_id, match_day):
    """Return True when a Delmatch row can be stored."""
    return bool(home_id and guest_id and match_day)


def build_delmatch_defaults(parsed, home_id, guest_id, match_day, season_id, uts):
    """Build the Delmatch.defaults payload for update_or_create."""
    return {
        "matchday": match_day,
        "date": parsed["date"],
        "home_team_id": home_id,
        "guest_team_id": guest_id,
        "result": parsed["result"],
        "season_id": season_id,
        "update_date": uts,
        "status": parsed["status"],
    }


def persist_delmatch(
    parsed,
    home_id,
    guest_id,
    match_day,
    season_id,
    uts,
    delmatch_model=None,
    dry_run=False,
):
    """Create or update a Delmatch row, or skip writes during dry-run."""
    defaults = build_delmatch_defaults(
        parsed, home_id, guest_id, match_day, season_id, uts
    )
    if dry_run:
        return None, False
    model = delmatch_model or Delmatch
    return model.objects.update_or_create(
        matchday=match_day,
        home_team_id=home_id,
        guest_team_id=guest_id,
        season_id=season_id,
        defaults=defaults,
    )


def format_match_line(home_short, guest_short, result, status):
    """Format one imported match for summaries."""
    return "{0} - {1}: {2} ({3})".format(home_short, guest_short, result, status)


def import_del_matches(
    events,
    team_list,
    match_day,
    season_id,
    uts,
    day,
    debug=False,
    dry_run=False,
    lookup_fn=None,
    delmatch_model=None,
):
    """Persist today's DEL matches and return formatted match lines."""
    lookup_fn = lookup_fn or lookup_team
    match_lines = []
    dry_run_rows = []
    print_debug(
        debug,
        "import_del_matches events={0} day={1} match_day={2} season_id={3} dry_run={4}".format(
            len(events or []), day, match_day, season_id, dry_run
        ),
    )
    for event in events or []:
        parsed = parse_event(event, debug=debug)
        home_id, home_name, home_short = lookup_fn(team_list, parsed["home_name"])
        guest_id, guest_name, guest_short = lookup_fn(team_list, parsed["guest_name"])
        print_debug(
            debug,
            "lookup home {0} -> id={1} short={2}; guest {3} -> id={4} short={5}".format(
                parsed["home_name"],
                home_id,
                home_short,
                parsed["guest_name"],
                guest_id,
                guest_short,
            ),
        )
        if home_id is None:
            print(format_lookup_warning(parsed["home_name"]))
        if guest_id is None:
            print(format_lookup_warning(parsed["guest_name"]))
        if parsed["date"] is None:
            print("warning: could not parse Esd '{0}'".format(parsed["esd"]))
            continue
        if not can_store_delmatch(home_id, guest_id, match_day):
            print_debug(debug, "skip event={0}".format(parsed))
            continue
        persist_delmatch(
            parsed,
            home_id,
            guest_id,
            match_day,
            season_id,
            uts,
            delmatch_model=delmatch_model,
            dry_run=dry_run,
        )
        match_lines.append(
            format_match_line(home_short, guest_short, parsed["result"], parsed["status"])
        )
        dry_run_rows.append(
            {
                "kickoff": parsed["kickoff"],
                "home_name": home_name,
                "home_short": home_short,
                "guest_name": guest_name,
                "guest_short": guest_short,
                "result": parsed["result"],
                "status": parsed["status"],
            }
        )
    if dry_run:
        print(format_dry_run_match_table(dry_run_rows, day, match_day, season_id, uts))
    print_debug(debug, "import_del_matches stored={0}".format(len(match_lines)))
    return match_lines


def update_del_matches(
    payload,
    team_list,
    match_day,
    season_id,
    uts,
    day,
    debug=False,
    dry_run=False,
    lookup_fn=None,
    delmatch_model=None,
):
    """Filter today's Livescore events and store them in Delmatch."""
    print_debug(
        debug,
        "update_del_matches day={0} match_day={1} season_id={2}".format(
            day, match_day, season_id
        ),
    )
    events = filter_events_for_day(
        extract_events(payload, debug=debug), day, debug=debug
    )
    return import_del_matches(
        events,
        team_list,
        match_day,
        season_id,
        uts,
        day,
        debug=debug,
        dry_run=dry_run,
        lookup_fn=lookup_fn,
        delmatch_model=delmatch_model,
    )


def run(
    argv=None,
    now_uts=None,
    season_id=None,
    teams=None,
    last_match=None,
    next_match=None,
    payload=None,
    fetch_fn=None,
    lookup_fn=None,
    last_match_fn=None,
    next_match_fn=None,
    ranking_model=None,
    team_model=None,
    delmatch_model=None,
    source=None,
):
    """Fetch live standings and store ranking and match rows."""
    args = parse_args(argv)
    now_uts = int(time.time()) if now_uts is None else int(now_uts)
    source = source or script_filename()
    day = resolve_day(args.day, now_uts=now_uts, debug=args.debug)
    print_debug(
        args.debug,
        "run debug={0} dry_run={1} uts={2} source={3} url={4} day={5}".format(
            args.debug, args.dry_run, now_uts, source, args.url, day
        ),
    )

    if args.season_id is not None:
        season_id = args.season_id
    elif season_id is None:
        season_id = load_season_id(debug=args.debug)
    print_debug(args.debug, "season_id={0}".format(season_id))

    last_match_fn = last_match_fn or get_last_match
    next_match_fn = next_match_fn or get_next_match
    if last_match is None:
        last_match = last_match_fn(now_uts, season_id)
    if next_match is None:
        next_match = next_match_fn(now_uts, season_id)
    match_id, _match_date, match_day = select_ranking_match(
        now_uts, last_match, next_match, debug=args.debug
    )
    print_debug(
        args.debug,
        "selected match_id={0} match_day={1}".format(match_id, match_day),
    )

    teams = (
        load_del_teams(team_model=team_model, debug=args.debug)
        if teams is None
        else list(teams)
    )

    if payload is None:
        if fetch_fn is None:
            payload = fetch_json(args.url, debug=args.debug)
        else:
            print_debug(args.debug, "fetch_fn url={0}".format(args.url))
            payload = fetch_fn(args.url)

    api_teams = extract_league_teams(payload, debug=args.debug)
    ranking_lines = import_standings(
        api_teams,
        teams,
        match_id,
        season_id,
        now_uts,
        source,
        debug=args.debug,
        dry_run=args.dry_run,
        lookup_fn=lookup_fn,
        ranking_model=ranking_model,
    )
    match_lines = update_del_matches(
        payload,
        teams,
        match_day,
        season_id,
        now_uts,
        day,
        debug=args.debug,
        dry_run=args.dry_run,
        lookup_fn=lookup_fn,
        delmatch_model=delmatch_model,
    )
    return ranking_lines, match_lines


def main(argv=None):
    """CLI entry point."""
    try:
        ranking_lines, match_lines = run(argv)
    except Exception as exc:
        print("get_life_ranking failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR

    print("stored {0} ranking rows".format(len(ranking_lines)))
    print("stored {0} del matches".format(len(match_lines)))
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
