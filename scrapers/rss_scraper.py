import logging
from datetime import datetime

import feedparser
import requests
from sqlalchemy.orm import Session

from database.models import Circular, Ministry
from scrapers.utils import KNOWN_CIRCULAR_RSS_FEEDS, is_excluded_feed, make_fingerprint
from summarizer.groq_summarizer import summarize_circular

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "DootaBot/1.0 (+https://github.com/doota; legal government circular monitor)",
}


def _probe_rss_feed(url: str) -> bool:
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        if response.status_code != 200:
            return False
        parsed = feedparser.parse(response.content)
        return bool(parsed.entries)
    except requests.RequestException:
        return False


def discover_rss_feeds(db: Session) -> int:
    found = 0
    ministries = db.query(Ministry).filter(Ministry.is_active.is_(True)).all()

    for ministry in ministries:
        if ministry.name in KNOWN_CIRCULAR_RSS_FEEDS:
            feed_url = KNOWN_CIRCULAR_RSS_FEEDS[ministry.name]
            if _probe_rss_feed(feed_url):
                ministry.rss_feed_url = feed_url
                ministry.has_rss_feed = True
                found += 1
            continue

        if not ministry.official_url:
            continue

        candidates = [
            f"{ministry.official_url.rstrip('/')}/circular-rss-feed",
            f"{ministry.official_url.rstrip('/')}/circulars/feed",
            f"{ministry.official_url.rstrip('/')}/feed/circulars",
        ]
        for candidate in candidates:
            if _probe_rss_feed(candidate):
                ministry.rss_feed_url = candidate
                ministry.has_rss_feed = True
                found += 1
                break

    db.commit()
    logger.info("Discovered %s circular RSS feeds", found)
    return found


def _save_circular(
    db: Session,
    ministry: Ministry,
    title: str,
    source_url: str,
    published_date: str | None,
    raw_content: str,
) -> Circular | None:
    fingerprint = make_fingerprint(source_url, raw_content)
    if db.query(Circular).filter(Circular.fingerprint == fingerprint).first():
        return None
    if db.query(Circular).filter(Circular.source_url == source_url).first():
        return None

    summary_data = summarize_circular(title, raw_content, ministry.name)
    circular = Circular(
        ministry_id=ministry.id,
        title=title,
        source_url=source_url,
        published_date=published_date,
        raw_content=raw_content,
        summary=summary_data.get("summary"),
        key_points=summary_data.get("key_points"),
        fingerprint=fingerprint,
    )
    db.add(circular)
    db.commit()
    db.refresh(circular)
    return circular


def discover_ministry_rss(db: Session, ministry: Ministry) -> bool:
    if ministry.name in KNOWN_CIRCULAR_RSS_FEEDS:
        feed_url = KNOWN_CIRCULAR_RSS_FEEDS[ministry.name]
        if _probe_rss_feed(feed_url):
            ministry.rss_feed_url = feed_url
            ministry.has_rss_feed = True
            db.commit()
            return True

    if not ministry.official_url:
        return False

    candidates = [
        f"{ministry.official_url.rstrip('/')}/circular-rss-feed",
        f"{ministry.official_url.rstrip('/')}/circulars/feed",
        f"{ministry.official_url.rstrip('/')}/feed/circulars",
    ]
    for candidate in candidates:
        if _probe_rss_feed(candidate):
            ministry.rss_feed_url = candidate
            ministry.has_rss_feed = True
            db.commit()
            return True
    return False


def poll_ministry_rss(db: Session, ministry: Ministry) -> int:
    if not ministry.rss_feed_url:
        return 0

    new_count = 0
    try:
        parsed = feedparser.parse(ministry.rss_feed_url)
    except Exception as exc:
        logger.warning("RSS parse failed for %s: %s", ministry.name, exc)
        return 0

    for entry in parsed.entries[:200]:
        title = entry.get("title", "Untitled circular")
        source_url = entry.get("link") or ministry.rss_feed_url
        if is_excluded_feed(title, source_url):
            continue

        published = entry.get("published") or entry.get("updated")
        raw_content = entry.get("summary", "") or title

        saved = _save_circular(db, ministry, title, source_url, published, raw_content)
        if saved:
            new_count += 1

    ministry.last_scraped_at = datetime.utcnow()
    db.commit()
    return new_count


def poll_circular_rss(db: Session) -> int:
    ministries = (
        db.query(Ministry)
        .filter(Ministry.is_active.is_(True), Ministry.has_rss_feed.is_(True))
        .all()
    )
    new_count = 0
    for ministry in ministries:
        new_count += poll_ministry_rss(db, ministry)
    logger.info("RSS poll found %s new circulars", new_count)
    return new_count
