#!/usr/bin/env python3
"""Check presseschau for new articles and send WhatsApp notifications."""

import argparse
import logging
import os
import sys
from datetime import timedelta
from urllib.parse import urlparse

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
)
import django

LOGGER = logging.getLogger("tools.notify_presseschau")


def _normalize_source(url):
    """Return a compact source host string for display."""
    hostname = urlparse(url or "").hostname or ""
    source = hostname.lower()
    for prefix in ("www.", "m.", "mobil."):
        if source.startswith(prefix):
            source = source[len(prefix) :]
    return source or "unknown-source"


def _normalize_recipients(group_numbers):
    """Return list of non-empty recipient numbers as strings."""
    recipients = []
    for number in group_numbers:
        if number is None:
            continue
        text = str(number).strip()
        if text:
            recipients.append(text)
    return recipients


def _build_message(entries, base_url):
    """Build notification message for newly found entries."""
    message = "Hallo,\n\nEs gibt neue Artikel in der Presseschau:\n\n"
    for entry in entries:
        source = _normalize_source(entry.get("url"))
        title = (entry.get("title") or "").strip() or "(ohne Titel)"
        message = (
            f"{message}- {source} - {title} {base_url}{entry.get('id')}\n\n"
        )
    return message


def _get_interval_seconds(default_seconds=43200, settings_obj=None):
    """Return alert interval in seconds from env/settings with fallback."""
    env_value = os.environ.get("PRESSSCHAU_ALERT_INTERVAL_SECONDS")
    settings_value = None
    if settings_obj is not None:
        settings_value = getattr(settings_obj, "PRESSSCHAU_ALERT_INTERVAL_SECONDS", None)
    raw_value = env_value if env_value is not None else settings_value

    if raw_value is None:
        return default_seconds

    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        LOGGER.warning(
            "invalid_interval_seconds value=%s using_default=%s",
            raw_value,
            default_seconds,
        )
        return default_seconds


def _get_article_url_base(default_url, settings_obj=None):
    """Return article URL base from env/settings with fallback."""
    settings_value = ""
    if settings_obj is not None:
        settings_value = getattr(settings_obj, "PRESSSCHAU_ARTICLE_URL_BASE", "")

    return (
        os.environ.get("PRESSSCHAU_ARTICLE_URL_BASE")
        or settings_value
        or default_url
    )


def main(argv=None):
    """Script entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated message instead of sending it via WhatsApp.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")
    django.setup()

    from django.conf import settings
    from django.utils import timezone
    from article.models import Entries
    from game.models import Groupsetting
    from wa_hack_cli import simple_send

    interval_seconds = _get_interval_seconds(settings_obj=settings)
    article_url_base = _get_article_url_base(
        "https://tippspiel.dynamop.de/article/showarticle?id=",
        settings_obj=settings,
    )

    group_list_qs = Groupsetting.objects.filter(news_alert=True).values_list(
        "number", flat=True
    )
    group_list = _normalize_recipients(group_list_qs)

    threshold_dt = timezone.now() - timedelta(seconds=interval_seconds)

    entry_list = (
        Entries.objects.using("wallabag")
        .filter(created_at__isnull=False, created_at__gte=threshold_dt)
        .order_by("-created_at", "-id")
        .values("id", "title", "url", "created_at")[:600]
    )

    new_entries = list(entry_list)

    if not new_entries:
        LOGGER.info("no_new_entries")
        return 0

    if not group_list:
        LOGGER.info("no_groups_configured_with_news_alert")
        return 0

    message = _build_message(new_entries, article_url_base)
    recipients = ",".join(group_list)

    LOGGER.info(
        (
            "sending_presseschau_alert recipients=%s entries=%d "
            "interval_seconds=%d dry_run=%s"
        ),
        len(group_list),
        len(new_entries),
        interval_seconds,
        args.dry_run,
    )

    if args.dry_run:
        print(message)
        LOGGER.info("presseschau_alert_dry_run_printed")
        return 0

    try:
        simple_send(settings.WA_SRV, settings.WA_PORT, recipients, message)
    except Exception:
        LOGGER.exception("simple_send_failed")
        return 1

    LOGGER.info("presseschau_alert_sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
