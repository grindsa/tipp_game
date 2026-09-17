#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Send a pre-game pump-up message via WhatsApp and Threema."""

from __future__ import absolute_import
from __future__ import print_function

import argparse
import datetime
import os
import sys
import time
from collections import namedtuple

from pytz import timezone

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from django.db.models import Q
from game.models import Groupsetting, Match, Season, Usersetting
from game.myfunctions import (
    collect_team_statistic,
    get_h2h_statistics,
    get_last_match,
    get_next_match,
    get_ranking,
    send_threema,
)
from wa_hack_cli import simple_send

TIMEZONE = timezone("Europe/Berlin")
THRESHOLD_SECONDS = 86400
EBB_SHORT_NAME = "EBB"
EBB_DEL_TEAM_ID = 3
EBB_DISPLAY_NAME = "Eisbären Berlin"
DEL_LEAGUE_ID = 1
EBB_TOPSCORER_YEAR = 2026
OPPONENT_TOPSCORER_YEAR = 2026
LAST_H2H_MATCH_LIMIT = 8
TOP_SCORER_LIMIT = 5
PLAYER_NAME_MAX_LEN = 16
BOOT_SIGNATURE = b"\xEE\x80\x9C".decode()
CFG_FILENAME = "delapphelper.cfg"

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
MISSING_TEAMS_MESSAGE = "h_team, g_team or m_day are missing. Aborting...."

MatchDetails = namedtuple(
    "MatchDetails",
    (
        "no_bet matchday home_id home_name home_short "
        "guest_id guest_name guest_short tv playoff opponent_del_id"
    ),
)
EMPTY_MATCH = MatchDetails(
    True, None, None, None, None, None, None, None, None, None, None
)

Sides = namedtuple(
    "Sides",
    (
        "ebb_id ebb_name ebb_short opponent_id opponent_name opponent_short "
        "ebb_table_label opponent_table_label match_type ebb_is_home"
    ),
)


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Send a pre-game pump-up message via WhatsApp and Threema."
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


def load_season_id(season_model=None):
    """Return the current season id as used by the original script."""
    model = season_model or Season
    return len(model.objects.values())


def match_is_within_window(match_date, now_uts, threshold=THRESHOLD_SECONDS):
    """Return True if the match starts within the next threshold window."""
    if match_date is None:
        return False
    return match_date <= now_uts + threshold and now_uts < match_date


def format_match_time(match_date):
    """Format a unix timestamp as a Berlin local kickoff time."""
    return datetime.datetime.fromtimestamp(match_date, tz=TIMEZONE).strftime("%H:%M")


def format_match_date(match_uts):
    """Format a match timestamp as a UTC date string."""
    return datetime.datetime.fromtimestamp(
        match_uts, tz=datetime.timezone.utc
    ).strftime("%d.%m.%y")


def shorten_player_name(player):
    """Shorten a player name if it is longer than the display limit."""
    try:
        if len(player) > PLAYER_NAME_MAX_LEN:
            first_name, last_name = player.split(" ", 2)
            return "{0}. {1}".format(first_name[:1], last_name)
        return player
    except (TypeError, ValueError, AttributeError):
        return player


def default_config_path(script_file=None):
    """Return the DelAppHelper config path from env or next to this script."""
    env_path = os.environ.get("DELAPPHELPER_CFG", "").strip()
    if env_path:
        return env_path
    script_file = script_file or __file__
    return os.path.join(os.path.dirname(script_file), CFG_FILENAME)


def delapp_helper_factory():
    """Create a DEL app helper using the local config file."""
    try:
        from delapphelper import DelAppHelper
    except ImportError as exc:
        raise RuntimeError(
            "delapphelper is not installed; add delapp-helper to requirements "
            "and rebuild the image"
        ) from exc
    return DelAppHelper(cfg_file=default_config_path())


def load_top_scorer_players(year, league_id, team_id, helper_factory=None):
    """Load player goal totals for a team from the DEL app helper."""
    factory = helper_factory or delapp_helper_factory
    players = []
    with factory() as helper:
        for player in helper.teamplayers_get(year, team_id, league_id):
            goals = (
                player["statistics"]["goals"]["away"]
                + player["statistics"]["goals"]["home"]
            )
            players.append(
                {
                    "name": player["name"],
                    "number": player["jersey"],
                    "goals": goals,
                }
            )
    return players


def format_top_scorers(players, team_name):
    """Build the topscorer section, or None if nobody has scored yet."""
    ranked = sorted(players, key=lambda item: item["goals"], reverse=True)
    if not ranked or ranked[0]["goals"] <= 0:
        return None

    lines = ['\n*Topscorer "{0}" nach Toren:*\n'.format(team_name)]
    for player in ranked[:TOP_SCORER_LIMIT]:
        if player["goals"] > 0:
            lines.append(
                "{0} ({1}) - {2}\n".format(
                    shorten_player_name(player["name"]),
                    player["number"],
                    player["goals"],
                )
            )
    return "".join(lines)


def get_top_scorers(year, league_id, team_id, team_name="EBB", helper_factory=None):
    """Return a formatted topscorer block for a team."""
    players = load_top_scorer_players(
        year, league_id, team_id, helper_factory=helper_factory
    )
    return format_top_scorers(players, team_name)


def load_last_h2h_matches(
    opponent_id, now_uts, match_model=None, limit=LAST_H2H_MATCH_LIMIT
):
    """Load recent matches involving the opponent."""
    model = match_model or Match
    rows = (
        model.objects.filter(
            Q(home_team_id=opponent_id, date__lte=now_uts)
            | Q(guest_team_id=opponent_id, date__lte=now_uts)
        )
        .order_by("-date")
        .values(
            "date",
            "home_team__short_name",
            "guest_team__short_name",
            "result",
            "id",
        )[:limit]
    )
    return {row["id"]: row for row in rows}


def load_match_details(match_id, match_model=None):
    """Load the fields needed to build a pump-up message."""
    model = match_model or Match
    rows = list(
        model.objects.filter(id=match_id).values(
            "date",
            "matchday",
            "home_team__team_id",
            "guest_team__team_id",
            "home_team__short_name",
            "guest_team__short_name",
            "home_team__team_name",
            "guest_team__team_name",
            "guest_team__del_teamid",
            "home_team__del_teamid",
            "no_bet",
            "tv",
            "playoff",
        )[:1]
    )
    if not rows:
        return EMPTY_MATCH

    row = rows[0]
    if row["home_team__del_teamid"] == EBB_DEL_TEAM_ID:
        opponent_del_id = row["guest_team__del_teamid"]
    else:
        opponent_del_id = row["home_team__del_teamid"]

    return MatchDetails(
        no_bet=row["no_bet"],
        matchday=row["matchday"],
        home_id=row["home_team__team_id"],
        home_name=row["home_team__team_name"],
        home_short=row["home_team__short_name"],
        guest_id=row["guest_team__team_id"],
        guest_name=row["guest_team__team_name"],
        guest_short=row["guest_team__short_name"],
        tv=row["tv"],
        playoff=row["playoff"],
        opponent_del_id=opponent_del_id,
    )


def resolve_sides(home_id, home_name, home_short, guest_id, guest_name, guest_short):
    """Map home/guest teams onto Eisbären vs opponent roles."""
    if guest_short == EBB_SHORT_NAME:
        return Sides(
            ebb_id=guest_id,
            ebb_name=guest_name,
            ebb_short=guest_short,
            opponent_id=home_id,
            opponent_name=home_name,
            opponent_short=home_short,
            ebb_table_label="Auswärtstabelle",
            opponent_table_label="Heimtabelle",
            match_type="auswärts",
            ebb_is_home=False,
        )
    return Sides(
        ebb_id=home_id,
        ebb_name=home_name,
        ebb_short=home_short,
        opponent_id=guest_id,
        opponent_name=guest_name,
        opponent_short=guest_short,
        ebb_table_label="Heimtabelle",
        opponent_table_label="Auswärtstabelle",
        match_type="zu Hause",
        ebb_is_home=True,
    )


def append_signature(body):
    """Append the original closing signature."""
    return "{0}\n\nEuer {1}".format(body, BOOT_SIGNATURE)


def build_no_bet_message(opponent_name, match_time):
    """Build the message used for non-league games."""
    return (
        "Hallo liebe Tippjemeinde,\n\n"
        "Hier ein paar Informationen zum heutigen Spiel:\n\n"
        'Die Eisbären spielen heute um {1}Uhr gegen "{0}".\n'
        "Dieses Spiel ist kein Ligaspiel, es kann also nicht getippt werden\n\n"
        "Das Boot versucht aber, einen Liveticker zu senden.\n"
    ).format(opponent_name, match_time)


def build_intro_message(
    playoff, matchday, article_a, opponent_name, match_time, url, match_type, tv
):
    """Build the greeting used for regular and playoff league games."""
    if playoff:
        body = (
            "Hallo liebe Tippjemeinde,\n\n"
            "Hurra, hurra die Playoffs sind da und wir spielen heute um {3}Uhr "
            '{5} gegen {1} "{2}". Bitte nicht vergessen zu tippen: {4}\n\n'
        ).format(matchday, article_a, opponent_name, match_time, url, match_type)
    else:
        body = (
            "Hallo liebe Tippjemeinde,\n\n"
            "Hier ein paar Informationen zum heutigen Spiel:\n\n"
            "Am {0}. Spieltag spielen wir um {3}Uhr {5} gegen {1} "
            '"{2}". Bitte nicht vergessen zu tippen: {4}\n\n'
        ).format(matchday, article_a, opponent_name, match_time, url, match_type)

    if tv:
        body = "{0}Das Spiel wird übrigens im FreeTv übertragen.\n\n".format(body)
    return body


def _ranking_line(rank_info, team_name):
    """Format one DEL table row."""
    return "#{0} - {1} ({2}) - {3} Pkt".format(
        rank_info["ranking"], team_name, rank_info["match"], rank_info["score"]
    )


def ranks_need_separator(home_rank, guest_rank):
    """Return True if the two ranks are more than one place apart."""
    try:
        return abs(home_rank - guest_rank) > 1
    except TypeError:
        return False


def format_del_table(ranking_dic, home_name, guest_name):
    """Format the compact DEL table snippet."""
    home_rank = ranking_dic["ht"]["ranking"]
    guest_rank = ranking_dic["gt"]["ranking"]
    if not (home_rank and guest_rank):
        return ""

    home_line = _ranking_line(ranking_dic["ht"], home_name)
    guest_line = _ranking_line(ranking_dic["gt"], guest_name)
    if home_rank < guest_rank:
        first_line, second_line = home_line, guest_line
    else:
        first_line, second_line = guest_line, home_line

    if ranks_need_separator(home_rank, guest_rank):
        return "*DEL-Tabelle*\n{0}\n...\n{1}\n\n".format(first_line, second_line)
    return "*DEL-Tabelle*\n{0}\n{1}\n\n".format(first_line, second_line)


def format_virtual_tables(sides, home_ranking, away_ranking):
    """Format virtual home/away table placements."""
    if sides.ebb_is_home:
        ebb_rank = home_ranking["ht"]["ranking"]
        opponent_rank = away_ranking["gt"]["ranking"]
    else:
        ebb_rank = away_ranking["gt"]["ranking"]
        opponent_rank = home_ranking["ht"]["ranking"]

    parts = []
    if ebb_rank:
        parts.append(
            "In der virtuellen {0} befinden sich die Eisbären auf Platz {1}.\n".format(
                sides.ebb_table_label, ebb_rank
            )
        )
    if opponent_rank:
        parts.append(
            '"{0}" befinden sich in der virtuellen {1} auf Platz {2}.\n\n'.format(
                sides.opponent_name, sides.opponent_table_label, opponent_rank
            )
        )
    return "".join(parts)


def format_h2h_section(matches, wins, losses, ot_wins, ot_losses, ps_wins, ps_losses):
    """Format head-to-head counts from Eisbären's point of view."""
    parts = []
    if matches:
        parts.append(
            "Die beiden Mannschaften haben bisher {0} mal gegeneinander gespielt.\n".format(
                matches
            )
        )
    if wins > 0:
        parts.append(
            "\n*Ergebnisse aus Eisbärensicht:*\n  {0} Siege\n".format(wins)
        )
    if ot_wins > 0:
        parts.append("  - {0} in OT\n".format(ot_wins))
    if ps_wins > 0:
        parts.append("  - {0} nach PS\n".format(ps_wins))
    if losses > 0:
        parts.append("  {0} Niederlagen\n".format(losses))
    if ot_losses > 0:
        parts.append("  - {0} in OT\n".format(ot_losses))
    if ps_losses > 0:
        parts.append("  - {0} nach PS\n".format(ps_losses))
    return "".join(parts)


def format_recent_h2h_matches(match_dic):
    """Format recent head-to-head results."""
    if not match_dic:
        return ""

    lines = [
        "\n*Ergebnisse der letzen {0} Spiele gegeneinander:*\n".format(len(match_dic))
    ]
    for match_id in sorted(match_dic, reverse=True):
        match = match_dic[match_id]
        lines.append(
            "{0}: {1} - {2} {3}\n".format(
                format_match_date(match["date"]),
                match["home_team__short_name"],
                match["guest_team__short_name"],
                match["result"],
            )
        )
    return "".join(lines)


def format_opponent_recent_matches(
    sort_list, match_dic, season_id, article_g, opponent_name
):
    """Format the opponent's recent results in the current season."""
    result_lines = []
    for match_id in sorted(sort_list or [], reverse=True):
        match = match_dic[match_id]
        if match["season_id"] != season_id:
            continue
        result_lines.append(
            "{0}: {1} - {2} {3}\n".format(
                format_match_date(match["date"]),
                match["home_team__short_name"],
                match["guest_team__short_name"],
                match["result"],
            )
        )
    if not result_lines:
        return ""

    header = '\n*Ergebnisse der letzen {0} Spiele {1} "{2}":*\n'.format(
        len(sort_list), article_g, opponent_name
    )
    return header + "".join(result_lines)


def format_league_body(
    details,
    sides,
    ranking_dic,
    home_ranking,
    away_ranking,
    h2h_stats,
    last_h2h_matches,
    opponent_sort_list,
    opponent_match_dic,
    season_id,
    article_g,
):
    """Build the non-playoff statistics body."""
    return "".join(
        [
            format_del_table(ranking_dic, details.home_name, details.guest_name),
            format_virtual_tables(sides, home_ranking, away_ranking),
            format_h2h_section(*h2h_stats),
            format_recent_h2h_matches(last_h2h_matches),
            format_opponent_recent_matches(
                opponent_sort_list,
                opponent_match_dic,
                season_id,
                article_g,
                sides.opponent_name,
            ),
        ]
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


def load_whatsapp_groups(groupsetting_model=None):
    """Load WhatsApp groups that should receive pump-up alerts."""
    model = groupsetting_model or Groupsetting
    return [
        number
        for number in model.objects.filter(alert=True).values_list("number", flat=True)
        if number
    ]


def load_threema_users(usersetting_model=None):
    """Load Threema IDs that should receive pump-up alerts."""
    model = usersetting_model or Usersetting
    return [
        threema_id
        for threema_id in model.objects.filter(threema_reminder=True).values_list(
            "threema", flat=True
        )
        if threema_id
    ]


def notify_recipients(
    message,
    settings_obj,
    dry_run=False,
    groups=None,
    threema_users=None,
    wa_send_fn=None,
    threema_send_fn=None,
):
    """Send the pump-up message, or print it during dry-run."""
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
        return

    if whatsapp_configured(settings_obj) and message and groups:
        dispatch_whatsapp(
            settings_obj, groups_csv, message, dry_run=False, send_fn=wa_send_fn
        )
    else:
        print(message)

    if threema_users and threema_configured(settings_obj):
        for receiver in threema_users:
            dispatch_threema(
                settings_obj,
                receiver,
                message,
                dry_run=False,
                send_fn=threema_send_fn,
            )


def build_pumpup_message(
    details,
    match_date,
    now_uts,
    season_id,
    last_match_id,
    url,
    collect_stats_fn=None,
    h2h_fn=None,
    ranking_fn=None,
    last_matches_fn=None,
    topscorers_fn=None,
):
    """Build the full pump-up message for a match."""
    collect_stats_fn = collect_stats_fn or collect_team_statistic
    h2h_fn = h2h_fn or get_h2h_statistics
    ranking_fn = ranking_fn or get_ranking
    last_matches_fn = last_matches_fn or load_last_h2h_matches
    topscorers_fn = topscorers_fn or get_top_scorers

    sides = resolve_sides(
        details.home_id,
        details.home_name,
        details.home_short,
        details.guest_id,
        details.guest_name,
        details.guest_short,
    )
    match_time = format_match_time(match_date)

    if details.no_bet:
        return append_signature(build_no_bet_message(sides.opponent_name, match_time))

    opponent_sort_list, opponent_match_dic, article_g, article_a = collect_stats_fn(
        False, now_uts, sides.opponent_id, sides.opponent_name
    )
    body = build_intro_message(
        details.playoff,
        details.matchday,
        article_a,
        sides.opponent_name,
        match_time,
        url,
        sides.match_type,
        details.tv,
    )

    if not details.playoff:
        h2h_stats = h2h_fn(sides.opponent_short)
        ranking_dic = ranking_fn(last_match_id, details.home_short, details.guest_short)
        home_ranking = ranking_fn(
            last_match_id, details.home_short, details.guest_short, "home"
        )
        away_ranking = ranking_fn(
            last_match_id, details.home_short, details.guest_short, "away"
        )
        last_h2h_matches = last_matches_fn(sides.opponent_id, now_uts)
        body = "{0}{1}".format(
            body,
            format_league_body(
                details,
                sides,
                ranking_dic,
                home_ranking,
                away_ranking,
                h2h_stats,
                last_h2h_matches,
                opponent_sort_list,
                opponent_match_dic,
                season_id,
                article_g,
            ),
        )

    if sides.ebb_name:
        topscorer = topscorers_fn(
            EBB_TOPSCORER_YEAR, DEL_LEAGUE_ID, EBB_DEL_TEAM_ID, EBB_DISPLAY_NAME
        )
        if topscorer:
            body = "{0}{1}".format(body, topscorer)

    if details.opponent_del_id:
        topscorer = topscorers_fn(
            OPPONENT_TOPSCORER_YEAR,
            DEL_LEAGUE_ID,
            details.opponent_del_id,
            sides.opponent_name,
        )
        if topscorer:
            body = "{0}{1}".format(body, topscorer)

    return append_signature(body)


def run(
    argv=None,
    now_uts=None,
    settings_obj=None,
    next_match_fn=None,
    last_match_fn=None,
    simple_send_fn=None,
    send_threema_fn=None,
    groups=None,
    threema_users=None,
    season_id=None,
    match_details=None,
    collect_stats_fn=None,
    h2h_fn=None,
    ranking_fn=None,
    last_matches_fn=None,
    topscorers_fn=None,
    load_details_fn=None,
):
    """Build and send (or dry-run) the pump-up message."""
    args = parse_args(argv)
    settings_obj = settings_obj or settings
    now_uts = int(time.time()) if now_uts is None else now_uts
    season_id = load_season_id() if season_id is None else season_id
    next_match = next_match_fn or get_next_match
    last_match = last_match_fn or get_last_match
    load_details = load_details_fn or load_match_details

    match_id, match_date, _tv = next_match(now_uts, season_id)
    last_match_id, _last_date, _match_day = last_match(now_uts, season_id)

    if not match_is_within_window(match_date, now_uts):
        return EXIT_SUCCESS

    details = match_details if match_details is not None else load_details(match_id)
    if not details.home_name or not details.guest_name:
        print(MISSING_TEAMS_MESSAGE)
        return EXIT_SUCCESS

    message = build_pumpup_message(
        details,
        match_date,
        now_uts,
        season_id,
        last_match_id,
        build_tip_url(settings_obj.ALLOWED_HOSTS),
        collect_stats_fn=collect_stats_fn,
        h2h_fn=h2h_fn,
        ranking_fn=ranking_fn,
        last_matches_fn=last_matches_fn,
        topscorers_fn=topscorers_fn,
    )
    notify_recipients(
        message,
        settings_obj,
        dry_run=args.dry_run,
        groups=groups,
        threema_users=threema_users,
        wa_send_fn=simple_send_fn,
        threema_send_fn=send_threema_fn,
    )
    return EXIT_SUCCESS


def main(argv=None):
    """CLI entry point."""
    try:
        return run(argv)
    except Exception as exc:
        print("match_pumpup failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
