#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch last-matchday DEL results and standings after a match."""

from __future__ import absolute_import

import argparse
import os
import sys
import time
from collections import namedtuple

import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from game.models import Delmatch, Ranking, Season, Team
from game.myfunctions import get_last_match, get_winloss, lookup_team, print_debug

try:
    from wa_hack_cli import simple_send
except ImportError:
    from game.wa_hack_cli import simple_send

CFG_FILENAME = "delapphelper.cfg"
DEFAULT_TABLE_ID = 44
DEFAULT_FAIRPLAY_YEAR = 2026
DEFAULT_LEAGUE_ID = 1
RANKING_TYPE = "all"
SOURCE_NAME = "get_ranking.py"
NOTIFY_WINDOW_SECONDS = 86400 # * 2
DEFAULT_SCHEDULE_URL = (
    "https://www.sportal.de/eishockey/del/spielplan/"
    "spielplan-chronologisch-saison-2026-2027"
)
HTTP_TIMEOUT_SECONDS = 20
HTML_PARSER = "lxml"
EBB_SHORT_NAME = "EBB"
RESULT_LIST_ID = "moduleResultContentResultateList"
MATCH_LIST_CLASS = "table_content"
HOME_CLASS = "heim"
GUEST_CLASS = "auswaerts"
SCORE_CLASS = "score"
MATCHDAY_SUFFIX = ". Spieltag"
TEAM_STAT_FIELDS = (
    "matches",
    "ebb_wins",
    "ebb_losses",
    "ebb_ot_wins",
    "ebb_ot_losses",
    "ebb_ps_wins",
    "ebb_ps_losses",
)

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1

RunResult = namedtuple("RunResult", "ranking_lines match_lines")
ParsedMatch = namedtuple(
    "ParsedMatch",
    "home_id home_name home_short guest_id guest_name guest_short result extension raw_result",
)


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Fetch last-matchday DEL results and standings, then notify admin."
        )
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned DEL updates and the admin WhatsApp message.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_SCHEDULE_URL,
        help="Sportal schedule URL (default: 2026-2027 chronological schedule).",
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


def persist_ranking(
    match_id, team, team_id, season_id, uts, penalty, ranking_model=None, dry_run=False
):
    """Create or update a ranking row for one team, or print it during dry-run."""
    defaults = build_ranking_defaults(team, team_id, season_id, uts, penalty)
    if dry_run:
        print(
            "dry-run ranking {0}: {1}".format(team.get("position"), team.get("name"))
        )
        return None, False
    model = ranking_model or Ranking
    return model.objects.update_or_create(
        matchday_id=match_id,
        ranking=int(team["position"]),
        type=RANKING_TYPE,
        defaults=defaults,
    )


def format_ranking_line(position, short_name, team_name):
    """Format one standings line for the admin message."""
    return "{0}: {1} - {2}".format(position, short_name, team_name)


def format_match_line(match):
    """Format one imported result for the admin message."""
    return "{0} - {1}: {2}".format(match.home_short, match.guest_short, match.result)


def format_admin_message(match_day, ranking_lines, match_lines=None):
    """Build the WhatsApp admin summary with results and standings."""
    match_lines = list(match_lines or [])
    ranking_lines = list(ranking_lines or [])
    if match_lines:
        message = "*get_ranking.py*\n\n{0}.Spieltag: {1} Spiele eingetragen.\n\n".format(
            match_day, len(match_lines)
        )
        for line in match_lines:
            message = "{0}{1}\n".format(message, line)
        message = "{0}\nall:\n".format(message)
    else:
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


def whatsapp_notify_decision(dry_run, settings_obj, now_uts, match_date):
    """Return (should_send, reason) for the admin WhatsApp message."""
    if dry_run:
        return True, "dry-run"
    if not whatsapp_configured(settings_obj):
        return False, "WhatsApp settings missing"
    if not within_notify_window(now_uts, match_date):
        return False, "last match older than {0}s (match_date={1})".format(
            NOTIFY_WINDOW_SECONDS, match_date
        )
    return True, "ok"


def dispatch_whatsapp(settings_obj, recipient, message, dry_run=False, send_fn=None):
    """Send a WhatsApp message, or print it during dry-run."""
    if not message:
        return False
    if dry_run:
        print("dry-run whatsapp {0}:\n{1}".format(recipient or "WA_ADMIN_NUMBER", message))
        return True
    if not recipient or not whatsapp_configured(settings_obj):
        return False
    sender = send_fn or simple_send
    sender(settings_obj.WA_SRV, settings_obj.WA_PORT, recipient, message)
    return True


def notify_admin(message, settings_obj, send_fn=None, dry_run=False):
    """Send the ranking summary to the WhatsApp admin number, or print it."""
    return dispatch_whatsapp(
        settings_obj,
        getattr(settings_obj, "WA_ADMIN_NUMBER", None),
        message,
        dry_run=dry_run,
        send_fn=send_fn,
    )


def can_store_ranking(team_id, match_id, match_day):
    """Return True when a ranking row can be stored for the last match."""
    return bool(team_id and match_id and match_day and match_day > 0)


def fetch_html(url, timeout=HTTP_TIMEOUT_SECONDS, get_fn=None):
    """Download the schedule HTML."""
    getter = get_fn or requests.get
    response = getter(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def parse_score(raw_result):
    """Return a normalized 'home:guest' score, or None if the match is unfinished."""
    if not raw_result or ":" not in raw_result:
        return None
    home_raw, guest_raw = raw_result.split(":", 1)
    home_token = home_raw.strip().split()[0] if home_raw.strip() else ""
    guest_token = guest_raw.strip().split()[0] if guest_raw.strip() else ""
    try:
        return "{0}:{1}".format(int(home_token), int(guest_token))
    except (TypeError, ValueError):
        return None


def parse_extension(raw_result):
    """Return OT/PP when the result text contains an overtime or shootout marker."""
    if not raw_result:
        return None
    if "n.V." in raw_result:
        return "OT"
    if "n.P." in raw_result:
        return "PP"
    return None


def extract_matchday_html(html, match_day, parser=HTML_PARSER):
    """Return the HTML fragment for one matchday heading block."""
    if match_day is None or html is None:
        return ""
    soup = BeautifulSoup(html, parser)
    block = soup.find("div", attrs={"id": RESULT_LIST_ID})
    if not block:
        return ""

    start_label = "{0}{1}".format(match_day, MATCHDAY_SUFFIX)
    chunks = []
    collecting = False
    for child in block:
        try:
            text = child.text.strip()
        except AttributeError:
            continue
        if text == start_label:
            collecting = True
        elif collecting and MATCHDAY_SUFFIX in text:
            break
        if collecting:
            chunks.append(str(child))
    return "\n".join(chunks)


def parse_match_nodes(html, parser=HTML_PARSER):
    """Parse home/guest/score nodes from a matchday HTML fragment."""
    if not html:
        return []
    soup = BeautifulSoup(html, parser)
    matches = []
    for node in soup.find_all("ul", attrs={"class": MATCH_LIST_CLASS}):
        home = node.find("li", attrs={"class": HOME_CLASS})
        guest = node.find("li", attrs={"class": GUEST_CLASS})
        score = node.find("li", attrs={"class": SCORE_CLASS})
        if not (home and guest and score):
            continue
        matches.append(
            {
                "home_name": home.text.strip(),
                "guest_name": guest.text.strip(),
                "raw_result": score.text.strip(),
            }
        )
    return matches


def resolve_parsed_match(raw_match, team_list, lookup_fn=None):
    """Attach team ids and a normalized score to a scraped match."""
    lookup_fn = lookup_fn or lookup_team
    home_id, home_name, home_short = lookup_fn(team_list, raw_match.get("home_name"))
    guest_id, guest_name, guest_short = lookup_fn(team_list, raw_match.get("guest_name"))
    raw_result = raw_match.get("raw_result") or ""
    return ParsedMatch(
        home_id,
        home_name,
        home_short,
        guest_id,
        guest_name,
        guest_short,
        parse_score(raw_result),
        parse_extension(raw_result),
        raw_result,
    )


def involves_ebb(match, ebb_short=EBB_SHORT_NAME):
    """Return True when Eisbären Berlin is one of the sides."""
    return match.home_short == ebb_short or match.guest_short == ebb_short


def ebb_and_opponent_ids(match, ebb_short=EBB_SHORT_NAME):
    """Return (ebb_id, opponent_id) for an Eisbären match."""
    if match.home_short == ebb_short:
        return match.home_id, match.guest_id
    if match.guest_short == ebb_short:
        return match.guest_id, match.home_id
    return None, None


def increment_team_stats(stats, winloss, extension):
    """Return a copy of opponent team stats with the Eisbären result applied."""
    updated = dict(stats)
    updated["matches"] = int(updated.get("matches") or 0) + 1
    if winloss == "win":
        updated["ebb_wins"] = int(updated.get("ebb_wins") or 0) + 1
        if extension == "OT":
            updated["ebb_ot_wins"] = int(updated.get("ebb_ot_wins") or 0) + 1
        elif extension == "PP":
            updated["ebb_ps_wins"] = int(updated.get("ebb_ps_wins") or 0) + 1
    elif winloss == "loss":
        updated["ebb_losses"] = int(updated.get("ebb_losses") or 0) + 1
        if extension == "OT":
            updated["ebb_ot_losses"] = int(updated.get("ebb_ot_losses") or 0) + 1
        elif extension == "PP":
            updated["ebb_ps_losses"] = int(updated.get("ebb_ps_losses") or 0) + 1
    return updated


def load_team_stats(team_id, team_model=None):
    """Load the Eisbären-vs-opponent counters for a team."""
    if not team_id:
        return None
    model = team_model or Team
    rows = list(
        model.objects.filter(team_id=team_id).values(*TEAM_STAT_FIELDS)[:1]
    )
    if not rows:
        return None
    return dict(rows[0])


def persist_team_stats(team_id, stats, team_model=None, dry_run=False):
    """Write opponent team statistics, or print them during dry-run."""
    if dry_run:
        print("dry-run team_stats team_id={0}: {1}".format(team_id, stats))
        return None, False
    model = team_model or Team
    return model.objects.update_or_create(team_id=team_id, defaults=stats)


def update_team_stats(
    debug,
    match,
    team_model=None,
    winloss_fn=None,
    dry_run=False,
):
    """Update Eisbären win/loss counters stored on the opponent team."""
    ebb_id, opponent_id = ebb_and_opponent_ids(match)
    print_debug(
        debug,
        "check team_stats: {0}, {1}, {2}".format(
            match.result, match.home_short, match.guest_short
        ),
    )
    if not (ebb_id and opponent_id and match.result):
        return False

    winloss_fn = winloss_fn or get_winloss
    winloss, _detail, _goal, _ggoal = winloss_fn(match.home_id, ebb_id, match.result)
    stats = load_team_stats(opponent_id, team_model=team_model)
    if not stats:
        return False

    updated = increment_team_stats(stats, winloss, match.extension)
    print_debug(debug, "update_database: {0}".format(updated))
    persist_team_stats(opponent_id, updated, team_model=team_model, dry_run=dry_run)
    return True


def build_delmatch_defaults(match, match_day, match_date, season_id, uts):
    """Build the Delmatch.defaults payload for update_or_create."""
    return {
        "matchday": match_day,
        "date": match_date,
        "home_team_id": match.home_id,
        "guest_team_id": match.guest_id,
        "result": match.result,
        "season_id": season_id,
        "update_date": uts,
    }


def persist_delmatch(
    match,
    match_day,
    match_date,
    season_id,
    uts,
    delmatch_model=None,
    dry_run=False,
):
    """Create or update a Delmatch row, or print it during dry-run."""
    defaults = build_delmatch_defaults(match, match_day, match_date, season_id, uts)
    if dry_run:
        print(
            "dry-run delmatch {0} - {1}: {2}".format(
                match.home_short, match.guest_short, match.result
            )
        )
        return None, False
    model = delmatch_model or Delmatch
    return model.objects.update_or_create(
        matchday=match_day,
        home_team_id=match.home_id,
        guest_team_id=match.guest_id,
        season_id=season_id,
        defaults=defaults,
    )


def can_store_match(match, match_day):
    """Return True when a scraped match can be stored."""
    return bool(match.home_id and match.guest_id and match.result and match_day)


def existing_delmatch_result(match, match_day, season_id, delmatch_model=None):
    """Return the stored result for this match, or None if it is missing."""
    if not (match.home_id and match.guest_id and match_day and season_id):
        return None
    model = delmatch_model or Delmatch
    rows = list(
        model.objects.filter(
            matchday=match_day,
            home_team_id=match.home_id,
            guest_team_id=match.guest_id,
            season_id=season_id,
        ).values("result")[:1]
    )
    if not rows:
        return None
    return rows[0].get("result")


def import_matches(
    raw_matches,
    team_list,
    match_day,
    match_date,
    season_id,
    uts,
    debug=False,
    dry_run=False,
    lookup_fn=None,
    team_model=None,
    delmatch_model=None,
    winloss_fn=None,
):
    """Persist finished matches and return formatted result lines."""
    lines = []
    for raw_match in raw_matches:
        match = resolve_parsed_match(raw_match, team_list, lookup_fn=lookup_fn)
        print_debug(
            debug,
            "home_team: {0}, guest_team: {1}, result: {2}".format(
                match.home_short, match.guest_short, match.result
            ),
        )
        if not can_store_match(match, match_day):
            continue
        previous_result = existing_delmatch_result(
            match, match_day, season_id, delmatch_model=delmatch_model
        )
        if involves_ebb(match) and previous_result != match.result:
            update_team_stats(
                debug,
                match,
                team_model=team_model,
                winloss_fn=winloss_fn,
                dry_run=dry_run,
            )
        persist_delmatch(
            match,
            match_day,
            match_date,
            season_id,
            uts,
            delmatch_model=delmatch_model,
            dry_run=dry_run,
        )
        lines.append(format_match_line(match))
    return lines


def import_last_matchday_results(
    url,
    match_day,
    match_date,
    season_id,
    uts,
    teams,
    debug=False,
    dry_run=False,
    html=None,
    fetch_fn=None,
    lookup_fn=None,
    team_model=None,
    delmatch_model=None,
    winloss_fn=None,
):
    """Fetch and store finished DEL results for the last matchday."""
    if not match_day:
        return []
    if html is None:
        fetch_fn = fetch_fn or fetch_html
        html = fetch_fn(url)
    fragment = extract_matchday_html(html, match_day)
    raw_matches = parse_match_nodes(fragment)
    return import_matches(
        raw_matches,
        teams,
        match_day,
        match_date,
        season_id,
        uts,
        debug=debug,
        dry_run=dry_run,
        lookup_fn=lookup_fn,
        team_model=team_model,
        delmatch_model=delmatch_model,
        winloss_fn=winloss_fn,
    )


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
    dry_run=False,
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
            dry_run=dry_run,
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
    html=None,
    fetch_fn=None,
    team_model=None,
    delmatch_model=None,
    winloss_fn=None,
):
    """Fetch results and standings, store them, and notify the admin."""
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
        "season_id={0} table_id={1} year={2} match_id={3} match_day={4} match_date={5}".format(
            season_id, args.table_id, args.year, match_id, match_day, match_date
        ),
    )

    match_lines = []
    try:
        match_lines = import_last_matchday_results(
            args.url,
            match_day,
            match_date,
            season_id,
            now_uts,
            teams,
            debug=args.debug,
            dry_run=args.dry_run,
            html=html,
            fetch_fn=fetch_fn,
            lookup_fn=lookup_fn,
            team_model=team_model,
            delmatch_model=delmatch_model,
            winloss_fn=winloss_fn,
        )
    except Exception as exc:
        print("result import failed: {0}".format(exc))

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
        dry_run=args.dry_run,
    )

    should_send, notify_reason = whatsapp_notify_decision(
        args.dry_run, settings_obj, now_uts, match_date
    )
    if should_send:
        dispatch_whatsapp(
            settings_obj,
            getattr(settings_obj, "WA_ADMIN_NUMBER", None),
            format_admin_message(match_day, ranking_lines, match_lines),
            dry_run=args.dry_run,
            send_fn=send_fn,
        )
    else:
        print("skipped whatsapp: {0}".format(notify_reason))
    return RunResult(ranking_lines, match_lines)


def main(argv=None):
    """CLI entry point."""
    try:
        result = run(argv)
    except Exception as exc:
        print("get_ranking failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR

    print(
        "stored {0} ranking rows, {1} del matches".format(
            len(result.ranking_lines), len(result.match_lines)
        )
    )
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
