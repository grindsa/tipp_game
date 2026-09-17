#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch last-matchday DEL results from sportal.de and store them."""

from __future__ import absolute_import

import argparse
import os
import sys
import time
from collections import namedtuple
from urllib.request import urlopen

from bs4 import BeautifulSoup

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from game.models import Delmatch, Season, Team
from game.myfunctions import get_last_match, get_winloss, lookup_team, print_debug

try:
    from wa_hack_cli import simple_send
except ImportError:
    from game.wa_hack_cli import simple_send

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

ParsedMatch = namedtuple(
    "ParsedMatch",
    "home_id home_name home_short guest_id guest_name guest_short result extension raw_result",
)


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch last-matchday DEL results from sportal.de and store them."
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=False,
        help="Enable extra logging.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned updates instead of writing the database or sending WhatsApp.",
    )
    parser.add_argument(
        "-s",
        "--season-id",
        type=int,
        default=None,
        help="Season id (default: number of Season rows).",
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


def load_del_teams(team_model=None):
    """Load DEL teams used for name lookup."""
    model = team_model or Team
    return list(
        model.objects.filter(del_team=True).values("team_id", "team_name", "short_name")
    )


def fetch_html(url, timeout=HTTP_TIMEOUT_SECONDS, opener=None):
    """Download the schedule HTML."""
    opener = opener or urlopen
    with opener(url, timeout=timeout) as response:
        return response.read()


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


def format_match_line(match):
    """Format one imported result for the admin message."""
    return "{0} - {1}: {2}".format(match.home_short, match.guest_short, match.result)


def format_admin_message(match_day, update_count, match_lines):
    """Build the WhatsApp admin summary."""
    message = "*get_delgames.py*\n\n{0}.Spieltag: {1} Spiele eingetragen.\n\n".format(
        match_day, update_count
    )
    for line in match_lines:
        message = "{0}{1}\n".format(message, line)
    return message


def whatsapp_configured(settings_obj):
    """Return True if WhatsApp admin notification settings are present."""
    return (
        hasattr(settings_obj, "WA_SRV")
        and hasattr(settings_obj, "WA_PORT")
        and getattr(settings_obj, "WA_ADMIN_NUMBER", None)
    )


def notify_admin(message, settings_obj, dry_run=False, send_fn=None):
    """Send the result summary, or print it during dry-run."""
    if not message:
        return False
    if dry_run:
        print(
            "dry-run whatsapp {0}:\n{1}".format(
                getattr(settings_obj, "WA_ADMIN_NUMBER", ""), message
            )
        )
        return True
    if not whatsapp_configured(settings_obj):
        return False
    sender = send_fn or simple_send
    sender(
        settings_obj.WA_SRV,
        settings_obj.WA_PORT,
        settings_obj.WA_ADMIN_NUMBER,
        message,
    )
    return True


def can_store_match(match, match_day):
    """Return True when a scraped match can be stored."""
    return bool(match.home_id and match.guest_id and match.result and match_day)


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
        if involves_ebb(match):
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


def run(
    argv=None,
    now_uts=None,
    season_id=None,
    teams=None,
    last_match=None,
    html=None,
    fetch_fn=None,
    lookup_fn=None,
    last_match_fn=None,
    team_model=None,
    delmatch_model=None,
    winloss_fn=None,
    settings_obj=None,
    send_fn=None,
):
    """Fetch last-matchday results, store them, and notify the admin."""
    args = parse_args(argv)
    now_uts = int(time.time()) if now_uts is None else int(now_uts)
    if args.season_id is not None:
        season_id = args.season_id
    elif season_id is None:
        season_id = load_season_id()

    last_match_fn = last_match_fn or get_last_match
    if last_match is None:
        last_match = last_match_fn(now_uts, season_id)
    _match_id, match_date, match_day = last_match
    print_debug(args.debug, "lmatchday: {0}".format(match_day))

    teams = load_del_teams(team_model=team_model) if teams is None else list(teams)
    settings_obj = settings_obj or settings

    if html is None:
        fetch_fn = fetch_fn or fetch_html
        html = fetch_fn(args.url)

    fragment = extract_matchday_html(html, match_day)
    raw_matches = parse_match_nodes(fragment)
    lines = import_matches(
        raw_matches,
        teams,
        match_day,
        match_date,
        season_id,
        now_uts,
        debug=args.debug,
        dry_run=args.dry_run,
        lookup_fn=lookup_fn,
        team_model=team_model,
        delmatch_model=delmatch_model,
        winloss_fn=winloss_fn,
    )

    if lines and (args.dry_run or whatsapp_configured(settings_obj)):
        notify_admin(
            format_admin_message(match_day, len(lines), lines),
            settings_obj,
            dry_run=args.dry_run,
            send_fn=send_fn,
        )
    return lines


def main(argv=None):
    """CLI entry point."""
    try:
        lines = run(argv)
    except Exception as exc:
        print("get_delgames failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR

    print("stored {0} del matches".format(len(lines)))
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
