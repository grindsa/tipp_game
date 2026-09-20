#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch MagentaSport DEL streams and store them on Match rows."""

from __future__ import absolute_import

import argparse
import hashlib
import os
import re
import sys
import time
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")

import django

django.setup()

from django.conf import settings
from game.models import Match, Season
from game.myfunctions import print_debug

try:
    from wa_hack_cli import simple_send
except ImportError:
    from game.wa_hack_cli import simple_send

DEFAULT_VIDEO_LIST_URL = "https://www.magentasport.de/del"
VIDEO_URL_PREFIX = "https://www.magentasport.de"
RECENT_SECTION_TITLE = "Kürzlich hinzugefügt"
COMPETITION_NEEDLE = "PENNY DEL"
HTTP_TIMEOUT_SECONDS = 20
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HTTP_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": HTTP_USER_AGENT,
}
JSON_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": DEFAULT_VIDEO_LIST_URL,
    "User-Agent": HTTP_USER_AGENT,
    "X-Requested-With": "XMLHttpRequest",
}
API_PREFIX = "/api/v3"
API_TOKEN_SALT = "55!#r%Rn3%xn?U?PX*k"
TOKEN_SKEW_HOURS = 5
LANE_EVENT_TYPE = "teamEvent"
LANE_START_FORMAT = "%Y-%m-%d %H:%M:%S"
SOURCE_NAME = "load_video_streams.py"
MATCH_TIMEZONE = ZoneInfo("Europe/Berlin")
TEAM_MATCH_THRESHOLD = 0.72
UMLAUT_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "Ä": "ae",
    "Ö": "oe",
    "Ü": "ue",
}
LANE_SECTION_PROP_RE = re.compile(
    r'data-aria-title="{0}".*?prop-url=["\']([^"\']+)["\']'.format(
        re.escape(RECENT_SECTION_TITLE)
    ),
    re.DOTALL | re.IGNORECASE,
)
LANE_PROP_RE = re.compile(r'prop-url=["\']([^"\']+)["\']', re.IGNORECASE)

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1

VideoEntry = namedtuple("VideoEntry", "link home guest day month weekday label")
VideoUpdate = namedtuple("VideoUpdate", "match_id matchday link home guest")


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch MagentaSport DEL streams and store matching URLs."
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=False,
        help="Log each function call with important inputs and outputs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned Match updates and the admin WhatsApp message.",
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
        default=DEFAULT_VIDEO_LIST_URL,
        help="MagentaSport DEL page used to discover the event-lane API (default: {0}).".format(
            DEFAULT_VIDEO_LIST_URL
        ),
    )
    args = parser.parse_args(argv)
    print_debug(
        args.debug,
        "parse_args debug={0} dry_run={1} season_id={2} url={3}".format(
            args.debug, args.dry_run, args.season_id, args.url
        ),
    )
    return args


def load_season_id(season_model=None, debug=False):
    """Return the current season id."""
    print_debug(debug, "load_season_id()")
    model = season_model or Season
    season_id = len(list(model.objects.values()))
    print_debug(debug, "load_season_id -> {0}".format(season_id))
    return season_id


def load_matches(season_id, match_model=None, debug=False):
    """Load match rows used to attach video URLs."""
    print_debug(debug, "load_matches season_id={0}".format(season_id))
    model = match_model or Match
    matches = list(
        model.objects.filter(season_id=season_id).values(
            "id",
            "matchday",
            "date",
            "video_url",
            "home_team__team_name",
            "home_team__short_name",
            "guest_team__team_name",
            "guest_team__short_name",
        )
    )
    print_debug(debug, "load_matches count={0}".format(len(matches)))
    return matches


def matches_missing_video(matches, debug=False):
    """Return match rows that still have no video_url."""
    print_debug(debug, "matches_missing_video count={0}".format(len(matches or [])))
    missing = []
    for match in matches or []:
        if match.get("video_url"):
            continue
        if match.get("id") is None or match.get("matchday") is None:
            continue
        missing.append(match)
    print_debug(debug, "matches_missing_video -> {0}".format(len(missing)))
    return missing


def fetch_html(url, timeout=HTTP_TIMEOUT_SECONDS, get_fn=None, headers=None, debug=False):
    """Download MagentaSport HTML."""
    print_debug(debug, "fetch_html url={0} timeout={1}".format(url, timeout))
    getter = get_fn or requests.get
    response = getter(url, timeout=timeout, headers=headers or HTTP_HEADERS)
    response.raise_for_status()
    content = response.content
    print_debug(
        debug,
        "fetch_html status={0} bytes={1}".format(
            getattr(response, "status_code", None),
            len(content or b""),
        ),
    )
    return content


def fetch_json(url, params=None, timeout=HTTP_TIMEOUT_SECONDS, get_fn=None, headers=None, debug=False):
    """Download a MagentaSport JSON payload."""
    print_debug(debug, "fetch_json url={0} params={1}".format(url, params))
    getter = get_fn or requests.get
    response = getter(url, params=params or {}, timeout=timeout, headers=headers or JSON_HEADERS)
    response.raise_for_status()
    payload = response.json()
    print_debug(debug, "fetch_json status={0}".format(getattr(response, "status_code", None)))
    return payload


def utc_now(now_uts=None):
    """Return a timezone-aware UTC datetime from a unix timestamp or the clock."""
    if now_uts is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(now_uts), tz=timezone.utc)


def token_day_unix(now_uts=None, skew_hours=TOKEN_SKEW_HOURS, debug=False):
    """Return the UTC midnight unix timestamp used in MagentaSport API tokens."""
    print_debug(debug, "token_day_unix now_uts={0} skew_hours={1}".format(now_uts, skew_hours))
    shifted = utc_now(now_uts) - timedelta(hours=skew_hours)
    day_start = datetime(shifted.year, shifted.month, shifted.day, tzinfo=timezone.utc)
    day_unix = int(day_start.timestamp())
    print_debug(debug, "token_day_unix -> {0}".format(day_unix))
    return day_unix


def generate_api_token(api_path, now_uts=None, salt=API_TOKEN_SALT, debug=False):
    """Build the SHA-256 token MagentaSport expects on /api/v3 requests.

    MagentaSport's client (class fL) builds the query token as:
        sha256(salt + utc_day_unix + decodeURIComponent(api_path))
    where salt is API_TOKEN_SALT and utc_day_unix is
        moment.utc().subtract(TOKEN_SKEW_HOURS, "hours").startOf("day").unix()
    i.e. UTC midnight of (now minus 5 hours). Example path:
        /api/v3/components/eventLane/12416
    The hex digest is sent as the `token` query parameter.
    """
    print_debug(debug, "generate_api_token api_path={0}".format(api_path))
    day_unix = token_day_unix(now_uts=now_uts, debug=debug)
    # token = sha256(salt + utc_midnight(now-5h) + api_path)
    raw = "{0}{1}{2}".format(salt, day_unix, api_path)
    token = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    print_debug(debug, "generate_api_token -> {0}".format(token))
    return token


def event_lane_api_path(prop_url, debug=False):
    """Return the /api/v3 path for an event-lane lazy-loader prop-url."""
    print_debug(debug, "event_lane_api_path prop_url={0}".format(prop_url))
    if not prop_url:
        print_debug(debug, "event_lane_api_path -> None")
        return None
    if prop_url.startswith(API_PREFIX):
        path = prop_url
    else:
        path = "{0}{1}".format(API_PREFIX, prop_url)
    print_debug(debug, "event_lane_api_path -> {0}".format(path))
    return path


def html_text(html, debug=False):
    """Decode MagentaSport page bytes into text."""
    print_debug(debug, "html_text type={0}".format(type(html).__name__))
    if html is None:
        return ""
    if isinstance(html, bytes):
        return html.decode("utf-8", "replace")
    return html


def find_recent_lane_prop_url(html, debug=False):
    """Return the lazy-loader prop-url for the 'Kürzlich hinzugefügt' section."""
    print_debug(debug, "find_recent_lane_prop_url()")
    text = html_text(html, debug=debug)
    matched = LANE_SECTION_PROP_RE.search(text)
    if matched is None:
        matched = LANE_PROP_RE.search(text)
    prop_url = matched.group(1) if matched is not None else None
    print_debug(debug, "find_recent_lane_prop_url -> {0}".format(prop_url))
    return prop_url


def fetch_event_lane(prop_url, get_fn=None, now_uts=None, debug=False):
    """Fetch the event-lane JSON that fills the unrendered MagentaSport shell."""
    print_debug(debug, "fetch_event_lane prop_url={0}".format(prop_url))
    api_path = event_lane_api_path(prop_url, debug=debug)
    if not api_path:
        raise ValueError("missing event-lane prop-url")
    token = generate_api_token(api_path, now_uts=now_uts, debug=debug)
    url = "{0}{1}".format(VIDEO_URL_PREFIX, api_path)
    return fetch_json(url, params={"token": token}, get_fn=get_fn, debug=debug)


def normalize_name(value, debug=False):
    """Lowercase a team/month name and fold German umlauts."""
    print_debug(debug, "normalize_name value={0}".format(value))
    text = value or ""
    for src, dest in UMLAUT_MAP.items():
        text = text.replace(src, dest)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    normalized = " ".join(text.split())
    print_debug(debug, "normalize_name -> {0}".format(normalized))
    return normalized


def name_similarity(left, right, debug=False):
    """Return a 0..1 similarity score for two team names."""
    print_debug(debug, "name_similarity left={0} right={1}".format(left, right))
    first = normalize_name(left)
    second = normalize_name(right)
    if not first or not second:
        print_debug(debug, "name_similarity -> 0.0")
        return 0.0
    if first == second:
        print_debug(debug, "name_similarity -> 1.0")
        return 1.0

    ratio = SequenceMatcher(None, first, second).ratio()
    left_tokens = set(first.split())
    right_tokens = set(second.split())
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens) / float(max(len(left_tokens), len(right_tokens)))
        contained = left_tokens <= right_tokens or right_tokens <= left_tokens
        ratio = max(ratio, overlap)
        if contained:
            ratio = max(ratio, 0.92)
    print_debug(debug, "name_similarity -> {0:.3f}".format(ratio))
    return ratio


def match_local_date(uts, tzinfo=None, debug=False):
    """Convert a match unix timestamp to a Europe/Berlin date."""
    print_debug(debug, "match_local_date uts={0}".format(uts))
    if uts in (None, ""):
        print_debug(debug, "match_local_date -> None")
        return None
    tzinfo = tzinfo or MATCH_TIMEZONE
    local_date = datetime.fromtimestamp(int(uts), tz=tzinfo).date()
    print_debug(debug, "match_local_date -> {0}".format(local_date.isoformat()))
    return local_date


def dates_match(entry, match, debug=False):
    """Return True when the MagentaSport day/month matches the stored match date."""
    print_debug(debug, "dates_match day={0} month={1} match_date={2}".format(
        getattr(entry, "day", None),
        getattr(entry, "month", None),
        match.get("date") if match else None,
    ))
    if not entry or entry.day is None or entry.month is None:
        print_debug(debug, "dates_match -> False missing event date")
        return False
    local_date = match_local_date(match.get("date") if match else None, debug=debug)
    if local_date is None:
        print_debug(debug, "dates_match -> False missing match date")
        return False
    matched = local_date.day == int(entry.day) and local_date.month == int(entry.month)
    print_debug(debug, "dates_match -> {0}".format(matched))
    return matched


def score_event_against_match(entry, match, debug=False):
    """Score a MagentaSport event against a stored match, or None if it is not a candidate."""
    print_debug(
        debug,
        "score_event_against_match home={0}/{1} guest={2}/{3}".format(
            entry.home,
            match.get("home_team__team_name"),
            entry.guest,
            match.get("guest_team__team_name"),
        ),
    )
    home_score = max(
        name_similarity(entry.home, match.get("home_team__team_name"), debug=debug),
        name_similarity(entry.home, match.get("home_team__short_name"), debug=debug),
    )
    guest_score = max(
        name_similarity(entry.guest, match.get("guest_team__team_name"), debug=debug),
        name_similarity(entry.guest, match.get("guest_team__short_name"), debug=debug),
    )
    if home_score < TEAM_MATCH_THRESHOLD or guest_score < TEAM_MATCH_THRESHOLD:
        print_debug(debug, "score_event_against_match -> None below threshold")
        return None
    if not dates_match(entry, match, debug=debug):
        print_debug(debug, "score_event_against_match -> None date mismatch")
        return None
    score = (home_score + guest_score) / 2.0
    print_debug(debug, "score_event_against_match -> {0:.3f}".format(score))
    return score


def absolute_video_url(href, prefix=VIDEO_URL_PREFIX, debug=False):
    """Build an absolute MagentaSport URL from a listing href."""
    print_debug(debug, "absolute_video_url href={0}".format(href))
    if not href:
        print_debug(debug, "absolute_video_url -> None")
        return None
    if href.startswith("http://") or href.startswith("https://"):
        print_debug(debug, "absolute_video_url -> {0}".format(href))
        return href
    link = "{0}{1}".format(prefix, href)
    print_debug(debug, "absolute_video_url -> {0}".format(link))
    return link


def lane_events(payload, debug=False):
    """Return the event list from a MagentaSport event-lane JSON payload."""
    print_debug(debug, "lane_events()")
    if isinstance(payload, list):
        print_debug(debug, "lane_events -> {0}".format(len(payload)))
        return payload
    if not isinstance(payload, dict):
        print_debug(debug, "lane_events -> 0")
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        data = data.get("data")
    events = data if isinstance(data, list) else []
    print_debug(debug, "lane_events -> {0}".format(len(events)))
    return events


def lane_event_local_date(scheduled_start, debug=False):
    """Return day and month from a MagentaSport scheduled_start object."""
    print_debug(debug, "lane_event_local_date scheduled_start={0}".format(scheduled_start))
    original = None
    iso_date = None
    if isinstance(scheduled_start, dict):
        original = scheduled_start.get("original")
        iso_date = scheduled_start.get("iso_date")
    elif scheduled_start:
        original = scheduled_start
    if original:
        try:
            local_dt = datetime.strptime(str(original)[:19], LANE_START_FORMAT)
            print_debug(debug, "lane_event_local_date -> {0}/{1}".format(local_dt.day, local_dt.month))
            return local_dt.day, local_dt.month
        except ValueError:
            print_debug(debug, "lane_event_local_date skip invalid original")
    if iso_date:
        try:
            aware = datetime.fromisoformat(str(iso_date).replace("Z", "+00:00"))
            local_dt = aware.astimezone(MATCH_TIMEZONE)
            print_debug(debug, "lane_event_local_date iso -> {0}/{1}".format(local_dt.day, local_dt.month))
            return local_dt.day, local_dt.month
        except ValueError:
            print_debug(debug, "lane_event_local_date skip invalid iso_date")
    print_debug(debug, "lane_event_local_date -> None")
    return None, None


def parse_lane_event(event, debug=False):
    """Turn one event-lane JSON object into a VideoEntry, or None."""
    print_debug(debug, "parse_lane_event type={0}".format((event or {}).get("type")))
    if not isinstance(event, dict) or event.get("type") != LANE_EVENT_TYPE:
        print_debug(debug, "parse_lane_event skip non teamEvent")
        return None
    metadata = event.get("metadata") or {}
    description = metadata.get("description_bold") or metadata.get("description") or ""
    if COMPETITION_NEEDLE.lower() not in str(description).lower():
        print_debug(debug, "parse_lane_event skip missing competition")
        return None
    details = metadata.get("details") or {}
    home = ((details.get("home") or {}).get("name_full") or "").strip()
    guest = ((details.get("away") or {}).get("name_full") or "").strip()
    if not home or not guest:
        print_debug(debug, "parse_lane_event skip missing teams")
        return None
    day, month = lane_event_local_date(metadata.get("scheduled_start"), debug=debug)
    link = absolute_video_url(event.get("target_url") or event.get("url"), debug=debug)
    if not link:
        print_debug(debug, "parse_lane_event skip missing url")
        return None
    entry = VideoEntry(link, home, guest, day, month, None, description)
    print_debug(debug, "parse_lane_event -> {0} gegen {1}".format(home, guest))
    return entry


def extract_video_entries(payload, debug=False):
    """Collect PENNY DEL team events from MagentaSport event-lane JSON."""
    print_debug(debug, "extract_video_entries()")
    entries = []
    for event in lane_events(payload, debug=debug):
        entry = parse_lane_event(event, debug=debug)
        if entry is None:
            continue
        entries.append(entry)
    print_debug(debug, "extract_video_entries -> {0}".format(len(entries)))
    return entries


def load_video_entries(
    html=None,
    lane_payload=None,
    page_url=DEFAULT_VIDEO_LIST_URL,
    fetch_fn=None,
    json_get_fn=None,
    now_uts=None,
    debug=False,
):
    """Read events from the MagentaSport event-lane API."""
    print_debug(debug, "load_video_entries()")
    if lane_payload is None:
        if html is None:
            html = fetch_html(page_url, get_fn=fetch_fn, debug=debug)
        prop_url = find_recent_lane_prop_url(html, debug=debug)
        if not prop_url:
            print("skipped videos: MagentaSport event list not found")
            print_debug(debug, "load_video_entries -> 0 missing prop-url")
            return []
        lane_payload = fetch_event_lane(
            prop_url,
            get_fn=json_get_fn,
            now_uts=now_uts,
            debug=debug,
        )
    entries = extract_video_entries(lane_payload, debug=debug)
    print_debug(debug, "load_video_entries -> {0}".format(len(entries)))
    return entries


def select_video_updates(entries, matches, debug=False):
    """Keep MagentaSport events that fuzzy-match a stored match without a video URL."""
    print_debug(
        debug,
        "select_video_updates entries={0} matches={1}".format(
            len(entries or []),
            len(matches or []),
        ),
    )
    unused = list(matches or [])
    updates = []
    for entry in entries or []:
        ranked = []
        for match in unused:
            score = score_event_against_match(entry, match, debug=debug)
            if score is None:
                continue
            ranked.append((score, match))
        if not ranked:
            print_debug(
                debug,
                "select_video_updates skip {0} gegen {1}".format(entry.home, entry.guest),
            )
            continue
        ranked.sort(key=lambda item: item[0], reverse=True)
        _score, match = ranked[0]
        unused.remove(match)
        updates.append(
            VideoUpdate(
                match.get("id"),
                match.get("matchday"),
                entry.link,
                entry.home,
                entry.guest,
            )
        )
    print_debug(debug, "select_video_updates -> {0}".format(len(updates)))
    return updates


def persist_video_urls(updates, match_model=None, dry_run=False, debug=False):
    """Store video URLs on Match rows, or print them during dry-run."""
    print_debug(debug, "persist_video_urls count={0} dry_run={1}".format(len(updates or []), dry_run))
    saved = []
    model = match_model or Match
    for item in updates or []:
        if dry_run:
            print("dry-run video Spieltag {0}: {1}".format(item.matchday, item.link))
            saved.append(item)
            continue
        print_debug(
            debug,
            "persist_video_urls update_or_create id={0} video_url={1}".format(
                item.match_id, item.link
            ),
        )
        model.objects.update_or_create(id=item.match_id, defaults={"video_url": item.link})
        saved.append(item)
    print_debug(debug, "persist_video_urls -> {0}".format(len(saved)))
    return saved


def format_video_line(item, debug=False):
    """Format one stored video for the admin message."""
    print_debug(debug, "format_video_line matchday={0} link={1}".format(item.matchday, item.link))
    return "Spieltag: {0}: {1}".format(item.matchday, item.link)


def format_admin_message(video_lines, debug=False):
    """Build the WhatsApp admin summary for newly stored videos."""
    print_debug(debug, "format_admin_message lines={0}".format(len(video_lines or [])))
    message = "*{0}*\n\nNeue Videos eingetragen:\n\n".format(SOURCE_NAME)
    for line in video_lines or []:
        message = "{0}{1}\n".format(message, line)
    return message


def whatsapp_configured(settings_obj, debug=False):
    """Return True if WhatsApp admin notification settings are present."""
    print_debug(debug, "whatsapp_configured()")
    configured = bool(
        hasattr(settings_obj, "WA_SRV")
        and hasattr(settings_obj, "WA_PORT")
        and getattr(settings_obj, "WA_ADMIN_NUMBER", None)
    )
    print_debug(debug, "whatsapp_configured -> {0}".format(configured))
    return configured


def dispatch_whatsapp(settings_obj, recipient, message, dry_run=False, send_fn=None, debug=False):
    """Send a WhatsApp message, or print it during dry-run."""
    print_debug(
        debug,
        "dispatch_whatsapp recipient={0} dry_run={1} message_len={2}".format(
            recipient, dry_run, len(message or "")
        ),
    )
    if not message:
        print_debug(debug, "dispatch_whatsapp skip empty message")
        return False
    if dry_run:
        print("dry-run whatsapp {0}:\n{1}".format(recipient or "WA_ADMIN_NUMBER", message))
        return True
    if not recipient or not whatsapp_configured(settings_obj, debug=debug):
        print_debug(debug, "dispatch_whatsapp skip missing recipient or settings")
        return False
    sender = send_fn or simple_send
    sender(settings_obj.WA_SRV, settings_obj.WA_PORT, recipient, message)
    print_debug(debug, "dispatch_whatsapp sent")
    return True


def notify_admin(video_lines, settings_obj, send_fn=None, dry_run=False, debug=False):
    """Send the video summary to the WhatsApp admin number, or print it."""
    print_debug(
        debug,
        "notify_admin lines={0} dry_run={1}".format(len(video_lines or []), dry_run),
    )
    if not video_lines:
        print_debug(debug, "notify_admin skip no new videos")
        return False
    return dispatch_whatsapp(
        settings_obj,
        getattr(settings_obj, "WA_ADMIN_NUMBER", None),
        format_admin_message(video_lines, debug=debug),
        dry_run=dry_run,
        send_fn=send_fn,
        debug=debug,
    )


def run(
    argv=None,
    now_uts=None,
    season_id=None,
    matches=None,
    html=None,
    lane_payload=None,
    fetch_fn=None,
    json_get_fn=None,
    match_model=None,
    season_model=None,
    settings_obj=None,
    send_fn=None,
):
    """Fetch new MagentaSport videos, store them, and notify the admin."""
    args = parse_args(argv)
    debug = args.debug
    print_debug(debug, "run()")
    now_uts = int(time.time()) if now_uts is None else int(now_uts)
    if args.season_id is not None:
        season_id = args.season_id
    elif season_id is None:
        season_id = load_season_id(season_model=season_model, debug=debug)
    print_debug(debug, "run season_id={0} now_uts={1}".format(season_id, now_uts))

    if matches is None:
        matches = load_matches(season_id, match_model=match_model, debug=debug)
    missing = matches_missing_video(matches, debug=debug)

    entries = load_video_entries(
        html=html,
        lane_payload=lane_payload,
        page_url=args.url,
        fetch_fn=fetch_fn,
        json_get_fn=json_get_fn,
        now_uts=now_uts,
        debug=debug,
    )
    updates = select_video_updates(entries, missing, debug=debug)
    saved = persist_video_urls(
        updates,
        match_model=match_model,
        dry_run=args.dry_run,
        debug=debug,
    )
    video_lines = [format_video_line(item, debug=debug) for item in saved]

    settings_obj = settings_obj or settings
    if video_lines:
        if args.dry_run or whatsapp_configured(settings_obj, debug=debug):
            notify_admin(
                video_lines,
                settings_obj,
                send_fn=send_fn,
                dry_run=args.dry_run,
                debug=debug,
            )
        else:
            print("skipped whatsapp: WhatsApp settings missing")
    else:
        print_debug(debug, "run no new videos")

    print_debug(debug, "run -> {0}".format(len(saved)))
    return saved


def main(argv=None):
    """CLI entry point."""
    try:
        saved = run(argv)
    except Exception as exc:
        print("load_video_streams failed: {0}".format(exc))
        return EXIT_RUNTIME_ERROR

    print("stored {0} video urls".format(len(saved)))
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
