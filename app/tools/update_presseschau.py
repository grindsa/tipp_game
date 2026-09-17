#!/usr/bin/env python3
"""update presseschau from several rss feeds and websites"""

# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import absolute_import
import os
import sys
import logging
import calendar
import time
import curl_cffi
from urllib.parse import urlparse
import ssl
from email.utils import parsedate_tz, mktime_tz
import requests
from bs4 import BeautifulSoup
import feedparser
from googlenewsdecoder import gnewsdecoder
from wa_hack_cli import simple_send

# pylint: disable=c0413, e0401, r0913
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")
import django

django.setup()
from article.models import Feedlink, Feed

LOGGER = logging.getLogger("tools.update_presseschau")

WALLABAG_URL = os.environ.get("WALLABAG_URL", "")
WALLABAG_USER = os.environ.get("WALLABAG_USER", "")
WALLABAG_PASSWORD = os.environ.get("WALLABAG_PASSWORD", "")
WALLABAG_CLIENTID = os.environ.get("WALLABAG_CLIENTID", "")
WALLABAG_SECRET = os.environ.get("WALLABAG_SECRET", "")
WA_ADMIN_NUMBER = os.environ.get("WA_ADMIN_NUMBER", "")
WA_SRV = os.environ.get("WA_SRV", "")
WA_PORT = os.environ.get("WA_PORT", "")
CHK_CERT = True
GOOGLE_RSS_URL = os.environ.get(
    "GOOGLE_RSS_URL",
    "https://news.google.com/rss/search?q=eisb%C3%A4ren%20berlin&hl=de&gl=DE&ceid=DE%3Ade",
)
GOOGLE_RSS_USER_AGENT = os.environ.get(
    "GOOGLE_RSS_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36",
)
GOOGLE_EXCLUDELIST = [
    entry.strip()
    for entry in os.environ.get(
        "GOOGLE_EXCLUDELIST", "www.penny-del.org/statistik/"
    ).split(",")
    if entry.strip()
]


def _get_google_max_age_hours(default_hours=48):
    """Return configured max Google entry age in hours."""
    try:
        return max(0, int(os.environ.get("GOOGLE_MAX_AGE_HOURS", str(default_hours))))
    except (TypeError, ValueError):
        return default_hours

GOOGLE_MAX_AGE_HOURS = _get_google_max_age_hours()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 4.0.4; Galaxy Nexus Build/IMM76B) AppleWebKit/535.19 (KHTML, like Gecko) Chrome/18.0.1025.133 Mobile Safari/535.19",
}


def is_wallabag_configured():
    """Return True if all required Wallabag environment values are present."""
    return all(
        [
            WALLABAG_URL,
            WALLABAG_USER,
            WALLABAG_PASSWORD,
            WALLABAG_CLIENTID,
            WALLABAG_SECRET,
        ]
    )


def store_link(url, usr, passwd, clientid, secret, link, logger):
    """store link"""
    logger.debug("store_link url=%s link=%s", url, link)
    gettoken = {
        "username": usr,
        "password": passwd,
        "client_id": clientid,
        "client_secret": secret,
        "grant_type": "password",
    }
    req = requests.get(f"{url}/oauth/v2/token", gettoken, timeout=10)
    req.raise_for_status()
    access = req.json().get("access_token")
    article = {"url": link, "archive": 0, "starred": 0, "access_token": access}
    req = requests.post(f"{url}/api/entries.json", article, timeout=20)
    req.raise_for_status()
    logger.debug("store_link response_status=%s url=%s", req.status_code, link)


def verify_link(link):
    """verify link"""

    # construct link
    source = urlparse(link)
    link = f"{source[0]}://{source[1]}{source[2]}"

    return link


def check_url(feedlink_list, url, logger, ignore_pattern=None):
    """check an url"""
    logger.debug("check_url url=%s", url)
    if url in feedlink_list:
        logger.debug("url_already_exists url=%s", url)
        return False, None, None

    logger.info("new_url_detected url=%s", url)
    url_chk = verify_link(url)
    if not url_chk:
        logger.warning("url_verification_failed url=%s", url)
        return False, None, "invalid_link"

    try:
        _, created = Feedlink.objects.get_or_create(url=url)
        if not created:
            if hasattr(feedlink_list, "add"):
                feedlink_list.add(url)
            logger.debug("url_already_exists_db url=%s", url)
            return False, None, None
    except Exception as err:
        logger.exception("feedlink_create_failed url=%s", url)
        return False, url_chk, f"db_insert_failed: {err}"

    if ignore_pattern is not None and ignore_pattern in url:
        logger.info("url_verification_ignored url=%s", url)
        if hasattr(feedlink_list, "add"):
            feedlink_list.add(url)
        return True, url_chk, None

    if not is_wallabag_configured():
        logger.warning("wallabag_not_configured skipping_store url=%s", url_chk)
        return False, url_chk, "wallabag_not_configured"

    try:
        store_link(
            WALLABAG_URL,
            WALLABAG_USER,
            WALLABAG_PASSWORD,
            WALLABAG_CLIENTID,
            WALLABAG_SECRET,
            url_chk,
            logger,
        )
    except Exception as err:
        logger.exception("wallabag_store_failed url=%s", url_chk)
        return False, url_chk, f"wallabag_store_failed: {err}"

    if hasattr(feedlink_list, "add"):
        feedlink_list.add(url)

    return True, url_chk, None


def _parse_host_and_path(value):
    """Return normalized hostname/path for URL or hostname/path text."""
    candidate = value.strip()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or "/"
    return host, path


def _is_excluded_domain(url, excludelist):
    """Match URL against excludelist entries with optional path prefixes."""
    domain, path = _parse_host_and_path(url)
    for item in excludelist:
        if not item:
            continue

        blocked_domain, blocked_path = _parse_host_and_path(item)
        if domain != blocked_domain:
            continue

        if blocked_path in ["", "/"]:
            return True

        if path.startswith(blocked_path):
            return True

    return False


def _decode_google_link(google_url, logger):
    """Decode a Google News redirect link into the source URL."""
    try:
        decoded = gnewsdecoder(google_url, interval=1)
    except Exception as err:
        logger.warning("google_decode_exception url=%s error=%s", google_url, err)
        return None

    if not decoded.get("status"):
        logger.warning(
            "google_decode_failed url=%s reason=%s", google_url, decoded.get("message")
        )
        return None

    return decoded.get("decoded_url")


def _process_google_entry(
    feedlink_list, google_url, excludelist, logger, new_links, error_links
):
    """Process one Google feed entry and update result lists."""
    is_ok, _, error_reason = check_url(
        feedlink_list, google_url, logger, ignore_pattern="news.google.com"
    )
    if not is_ok:
        _append_error(error_links, google_url, None, error_reason)
        return

    decoded_link = _decode_google_link(google_url, logger)
    if not decoded_link:
        _append_error(error_links, google_url, None, "google_decode_failed")
        return

    if _is_excluded_domain(decoded_link, excludelist):
        logger.info("google_link_excluded url=%s", decoded_link)
        _append_error(error_links, decoded_link, decoded_link, "google_excluded")
        return

    is_ok, _, error_reason = check_url(feedlink_list, decoded_link, logger)
    if is_ok:
        new_links.append(decoded_link)
        return

    logger.warning(
        "google_link_check_failed url=%s reason=%s", decoded_link, error_reason
    )
    _append_error(error_links, decoded_link, None, error_reason)


def _google_entry_timestamp(entry):
    """Return UTC timestamp from a Google feed entry, else None."""
    published_parsed = getattr(entry, "published_parsed", None)
    if published_parsed:
        return calendar.timegm(published_parsed)

    published = getattr(entry, "published", None)
    if not published:
        return None

    parsed = parsedate_tz(published)
    if not parsed:
        return None

    return mktime_tz(parsed)


def _is_google_entry_too_old(entry, max_age_hours=GOOGLE_MAX_AGE_HOURS):
    """Return True when a Google feed entry is older than max_age_hours."""
    published_timestamp = _google_entry_timestamp(entry)
    if published_timestamp is None:
        return True

    max_age_seconds = max_age_hours * 3600
    current_timestamp = time.time()
    return (current_timestamp - published_timestamp) > max_age_seconds


def _parse_google_feed():
    """Fetch and parse the Google RSS feed."""
    if hasattr(ssl, "_create_unverified_context"):
        ssl._create_default_https_context = ssl._create_unverified_context
    return feedparser.parse(
        GOOGLE_RSS_URL,
        request_headers={"User-Agent": GOOGLE_RSS_USER_AGENT},
    )


def _iter_google_feed_entries(google_feed):
    """Yield Google feed entries."""
    for entry in getattr(google_feed, "entries", []):
        yield entry


def parse_google_page(feedlink_list, logger):
    """parse google page"""
    logger.debug("parse_google_page start")

    google_feed = _parse_google_feed()
    google_link_list = []
    google_error_list = []
    for entry in _iter_google_feed_entries(google_feed):
        if _is_google_entry_too_old(entry):
            logger.info(
                "google_entry_skipped_old published=%s max_age_hours=%s",
                getattr(entry, "published", None),
                GOOGLE_MAX_AGE_HOURS,
            )
            continue

        google_url = getattr(entry, "link", None)
        if not google_url:
            continue

        _process_google_entry(
            feedlink_list,
            google_url,
            GOOGLE_EXCLUDELIST,
            logger,
            google_link_list,
            google_error_list,
        )

    return google_link_list, google_error_list


def _append_error(error_link_list, candidate_url, resolved_url, error_reason):
    """Append a normalized error entry when an URL check fails."""
    if not error_reason:
        return
    error_link_list.append(
        {
            "candidate_url": candidate_url,
            "resolved_url": resolved_url,
            "reason": error_reason,
        }
    )


def _handle_redirect(
    session, prefix, href, existing_link_list, logger, real_links, error_link_list
):
    """Resolve feed-reader redirect target and classify success/failure."""
    req = session.get(f"{prefix}{href}", impersonate="chrome")
    if req.status_code != 200:
        return

    redirect_ok, redirect_resolved_url, redirect_error_reason = check_url(
        existing_link_list,
        req.url,
        logger,
        ignore_pattern=prefix,
    )
    if redirect_ok:
        real_links.append(req.url)
        return

    _append_error(
        error_link_list, req.url, redirect_resolved_url, redirect_error_reason
    )


def _process_feedreader_href(
    session,
    prefix,
    href,
    existing_link_list,
    logger,
    feedreader_links,
    real_links,
    error_link_list,
):
    """Process a single feed-reader anchor candidate."""
    candidate_url = f"{prefix}{href[1:]}"
    is_ok, resolved_url, error_reason = check_url(
        existing_link_list,
        candidate_url,
        logger,
        ignore_pattern=prefix,
    )
    if not is_ok:
        _append_error(error_link_list, candidate_url, resolved_url, error_reason)
        return

    feedreader_links.append(f"{prefix}{href}")
    _handle_redirect(
        session, prefix, href, existing_link_list, logger, real_links, error_link_list
    )


def parse_feedreader_net(existing_link_list, logger):
    """parse feedreader.net"""
    logger.debug("parse_feedreader_net start")

    prefix = "https://news.feed-reader.net/nocrawl/target.php?id="
    url = "https://news.feed-reader.net/8416-eisbaeren-berlin.html#"
    session = curl_cffi.requests.Session()
    req = session.get(url, impersonate="chrome")
    html = req.text

    soup = BeautifulSoup(html, "lxml")
    results_div = soup.find("div", id="results")
    if not results_div:
        return [], [], []

    feedreader_links = []
    real_links = []
    error_link_list = []
    for link in results_div.find_all("a", href=True):
        href = link.get("href")
        if not href.startswith("#"):
            continue

        href = href[1:]  # Remove the leading '#' character
        _process_feedreader_href(
            session,
            prefix,
            href,
            existing_link_list,
            logger,
            feedreader_links,
            real_links,
            error_link_list,
        )

    logger.debug(
        "parse_feedreader_net feedreader_links=%s real_links=%s error_links=%s",
        len(feedreader_links),
        len(real_links),
        len(error_link_list),
    )
    return feedreader_links, real_links, error_link_list


def _build_summary_message(new_link_list, error_link_list):
    """Build whatsapp summary text for new and error links."""
    message = "*update_presseschau.py*\n\n"
    if new_link_list:
        message = "{0}{1}\n\n".format(
            message,
            "Neue Links:\n----------------------------------------------------------\n",
        )
        for nlink in new_link_list:
            message = "{0}{1}\n\n".format(message, nlink)

    if error_link_list:
        message = "{0}{1}\n\n".format(
            message,
            "fehlerhafte Links:\n----------------------------------------------------------\n",
        )
        for elink in error_link_list:
            if isinstance(elink, dict):
                candidate = elink.get("candidate_url", "-")
                reason = elink.get("reason", "-")
                resolved = elink.get("resolved_url", "-")
                line = "candidate={0} resolved={1} reason={2}".format(
                    candidate, resolved, reason
                )
                message = "{0}{1}\n\n".format(message, line)
            else:
                message = "{0}{1}\n\n".format(message, elink)

    return message


def _send_whatsapp_summary(new_link_list, error_link_list, logger):
    """Send whatsapp summary when notification env is configured."""
    if not (new_link_list or error_link_list):
        return

    if WA_ADMIN_NUMBER and WA_SRV and WA_PORT:
        try:
            wa_port = int(WA_PORT)
        except (TypeError, ValueError):
            logger.warning("invalid_whatsapp_port WA_PORT=%s", WA_PORT)
            return

        message = _build_summary_message(new_link_list, error_link_list)
        simple_send(WA_SRV, wa_port, WA_ADMIN_NUMBER, message)
        return

    logger.warning("missing_whatsapp_env WA_ADMIN_NUMBER/WA_SRV/WA_PORT")


def _is_rss_post_public(post):
    """Return True when the feed entry is public or has no access flag."""
    return (
        not hasattr(post, "dcterms_accessrights") or post.dcterms_accessrights == "free"
    )


def _process_rss_post(post, known_links, logger, new_link_list, error_link_list):
    """Process one RSS entry and update result lists."""
    post_url = getattr(post, "link", None)
    if not post_url or not _is_rss_post_public(post):
        return

    is_ok, resolved_url, error_reason = check_url(known_links, post_url, logger=logger)
    if is_ok:
        known_links.add(post_url)
        new_link_list.append(resolved_url or post_url)
        return

    _append_error(error_link_list, post_url, resolved_url, error_reason)


def _parse_single_rss_feed(
    feed_url, known_links, logger, new_link_list, error_link_list
):
    """Parse one RSS feed URL and process all feed entries."""
    feed = feedparser.parse(feed_url)
    for post in getattr(feed, "entries", []):
        _process_rss_post(post, known_links, logger, new_link_list, error_link_list)


def parse_rss_feeds(feed_urls, known_links, logger):
    """Parse configured RSS feeds and return new links and errors."""
    logger.debug("parse_rss_feeds start feed_urls=%s", len(feed_urls))

    new_link_list = []
    error_link_list = []

    if hasattr(ssl, "_create_unverified_context"):
        ssl._create_default_https_context = ssl._create_unverified_context

    for feed_url in feed_urls:
        _parse_single_rss_feed(
            feed_url, known_links, logger, new_link_list, error_link_list
        )

    logger.debug(
        "parse_rss_feeds end new_links=%s error_links=%s",
        len(new_link_list),
        len(error_link_list),
    )
    return new_link_list, error_link_list


def main(logger=None):
    """Script entrypoint."""

    log = logger or LOGGER
    log.info("job_started name=update_presseschau")
    if not is_wallabag_configured():
        log.warning(
            "missing_wallabag_env WALLABAG_URL/WALLABAG_USER/WALLABAG_PASSWORD/WALLABAG_CLIENTID/WALLABAG_SECRET"
        )

    # get last entries from database and keep one shared in-run known set
    feedlink_list = Feedlink.objects.order_by("-id").values_list("url", flat=True)[
        :1600
    ]
    known_links = set(feedlink_list)

    # initialize empty lists for new and error links
    new_link_list, error_link_list = [], []

    # parse feedreader.net
    _feed_reader_link_list, feedreader_new_link_list, feedreader_error_link_list = (
        parse_feedreader_net(known_links, log)
    )
    new_link_list = new_link_list + feedreader_new_link_list
    error_link_list = error_link_list + feedreader_error_link_list

    # parse feeds
    feeds = Feed.objects.values_list("url", flat=True)
    rss_new_link_list, rss_error_link_list = parse_rss_feeds(feeds, known_links, log)
    new_link_list = feedreader_new_link_list + rss_new_link_list
    error_link_list = feedreader_error_link_list + rss_error_link_list

    # parse google news
    googe_new_link_list, google_error_link_list = parse_google_page(known_links, log)
    new_link_list = new_link_list + googe_new_link_list
    error_link_list = error_link_list + google_error_link_list

    log.info(
        "job_finished name=update_presseschau new_links=%s error_links=%s",
        len(new_link_list),
        len(error_link_list),
    )
    _send_whatsapp_summary(new_link_list, error_link_list, log)


if __name__ == "__main__":
    main()
