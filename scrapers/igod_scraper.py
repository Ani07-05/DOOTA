import logging
import re

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from database.models import Ministry
from scrapers.utils import KNOWN_CIRCULAR_PAGES, clean_name, extract_abbreviation, normalize_url

logger = logging.getLogger(__name__)

IGOD_BASE = "https://igod.gov.in"
CATEGORIES_URL = f"{IGOD_BASE}/ug/categories"

HEADERS = {
    "User-Agent": "DootaBot/1.0 (+https://github.com/doota; legal government circular monitor)",
}


def _fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def _parse_categories_page(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for row in soup.select("div.search-result-row"):
        title_link = row.select_one("a.search-title")
        detail_link = row.select_one("a.btn-detail, a[href*='/organization/']")
        if not title_link or not detail_link:
            continue

        name = clean_name(title_link.get_text(" ", strip=True))
        if not name or len(name) < 8:
            continue

        igod_url = normalize_url(IGOD_BASE, detail_link["href"])
        if not igod_url or igod_url in seen_urls:
            continue

        official_url = title_link.get("href", "").strip()
        if official_url and not official_url.startswith("http"):
            official_url = None
        if official_url and "igod.gov.in" in official_url:
            official_url = None

        org_type = "ministry" if name.startswith("Ministry") else "department"
        seen_urls.add(igod_url)
        results.append(
            {
                "name": name,
                "abbreviation": extract_abbreviation(name),
                "igod_url": igod_url,
                "official_url": official_url,
                "org_type": org_type,
            }
        )

    return results


def _extract_official_url_from_detail(igod_url: str) -> str | None:
    try:
        html = _fetch_html(igod_url)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch igod detail %s: %s", igod_url, exc)
        return None

    soup = BeautifulSoup(html, "html.parser")
    for label in soup.find_all(string=re.compile(r"website", re.I)):
        parent = label.find_parent()
        if not parent:
            continue
        link = parent.find("a", href=True)
        if link and link["href"].startswith("http") and "igod.gov.in" not in link["href"]:
            return link["href"].strip()
    return None


def discover_organizations() -> list[dict[str, str]]:
    return _parse_categories_page(_fetch_html(CATEGORIES_URL))


def _has_known_circular_url(name: str) -> bool:
    name_lower = name.lower()
    return any(key.lower() in name_lower for key in KNOWN_CIRCULAR_PAGES)


def refresh_ministries(db: Session) -> int:
    organizations = discover_organizations()

    # Deactivate any existing ministries that no longer have a known circular URL
    for ministry in db.query(Ministry).filter(Ministry.is_active.is_(True)).all():
        if not _has_known_circular_url(ministry.name):
            ministry.is_active = False
    db.commit()

    updated = 0
    for org in organizations:
        if not _has_known_circular_url(org["name"]):
            continue

        existing = db.query(Ministry).filter(Ministry.igod_url == org["igod_url"]).first()
        official_url = org.get("official_url") or _extract_official_url_from_detail(org["igod_url"])

        if existing:
            existing.name = org["name"]
            existing.abbreviation = org.get("abbreviation")
            existing.org_type = org["org_type"]
            if official_url:
                existing.official_url = official_url
        else:
            db.add(
                Ministry(
                    name=org["name"],
                    abbreviation=org.get("abbreviation"),
                    org_type=org["org_type"],
                    igod_url=org["igod_url"],
                    official_url=official_url,
                )
            )
        updated += 1

    db.commit()
    logger.info("Refreshed %s organizations from igod.gov.in", updated)
    return updated
