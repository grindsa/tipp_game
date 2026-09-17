#!/usr/bin/env python3
"""Count words from recent wallabag entries and persist top words."""

import os
import sys
import argparse
import logging
from bs4 import BeautifulSoup

DEFAULT_ARTICLE_NUMBER = 30
DEFAULT_TOP_N = 25
DEFAULT_DB_ALIAS = "wallabag"


def configure_django():
    """Configure Django runtime for standalone script execution."""
    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
    if app_root not in sys.path:
        sys.path.append(app_root)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")
    import django

    django.setup()


def get_runtime_dependencies():
    """Load Django-dependent models and helper functions lazily."""
    from article.models import Entries, Articletopwords
    from article.myfunctions import get_top_words

    return Entries, Articletopwords, get_top_words


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Count words in recent entries and update top-word ranks."
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="Enable debug output",
        action="store_true",
    )
    parser.add_argument(
        "--article-number",
        type=int,
        default=DEFAULT_ARTICLE_NUMBER,
        help="Number of recent entries to analyze (default: %(default)s)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Number of top words to persist (default: %(default)s)",
    )
    parser.add_argument(
        "--db-alias",
        type=str,
        default=DEFAULT_DB_ALIAS,
        help="Database alias used to load source entries (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        help="Print computed ranking without database writes",
        action="store_true",
    )
    return parser.parse_args()


def setup_logging(debug=False):
    """Configure script logger."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")
    return logging.getLogger("tools.word_counter")


def fetch_recent_entries(entries_model, db_alias, article_number):
    """Fetch recent entry content strings from the configured database alias."""
    return entries_model.objects.using(db_alias).order_by("-id").values("content")[:article_number]


def strip_html_from_entries(entry_list):
    """Remove HTML and normalize text payloads for tokenization."""
    cleaned_entries = []
    for entry in entry_list:
        content = entry.get("content") or ""
        text = BeautifulSoup(content, "lxml").get_text(" ", strip=True)
        cleaned_entries.append({"content": text})
    return cleaned_entries


def rank_top_words(word_dict, top_n):
    """Return sorted word/count tuples in descending frequency order."""
    return sorted(word_dict.items(), key=lambda item: item[1], reverse=True)[:top_n]


def persist_top_words(topwords_model, ranked_words):
    """Persist ranked words and return number of written rows."""
    from django.db import transaction

    with transaction.atomic():
        for rank, (word, count) in enumerate(ranked_words, start=1):
            topwords_model.objects.update_or_create(
                rank=rank,
                defaults={"word": word, "count": count},
            )
        topwords_model.objects.filter(rank__gt=len(ranked_words)).delete()

    return len(ranked_words)


def main():
    """Script entrypoint."""
    args = parse_args()
    logger = setup_logging(debug=args.debug)

    if args.article_number <= 0:
        logger.error("--article-number must be greater than 0")
        return 2
    if args.top_n <= 0:
        logger.error("--top-n must be greater than 0")
        return 2

    configure_django()
    entries_model, topwords_model, get_top_words = get_runtime_dependencies()

    logger.debug(
        "loading_entries db_alias=%s article_number=%s", args.db_alias, args.article_number
    )
    entry_list = fetch_recent_entries(entries_model, args.db_alias, args.article_number)
    cleaned_entries = strip_html_from_entries(entry_list)

    word_dict = get_top_words(cleaned_entries, "content")
    ranked_words = rank_top_words(word_dict, args.top_n)

    if args.debug or args.dry_run:
        for rank, (word, count) in enumerate(ranked_words, start=1):
            logger.info("rank=%s word=%s count=%s", rank, word, count)

    if args.dry_run:
        logger.info("dry_run_completed entries=%s top_words=%s", len(cleaned_entries), len(ranked_words))
        return 0

    written_count = persist_top_words(topwords_model, ranked_words)
    logger.info("word_counter_completed entries=%s written=%s", len(cleaned_entries), written_count)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
