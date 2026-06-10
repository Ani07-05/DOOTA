import logging
import re
import urllib3
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

try:
    from curl_cffi.requests import Session as CurlSession
    _CURL_AVAILABLE = True
except ImportError:
    _CURL_AVAILABLE = False

_PLAYWRIGHT_AVAILABLE = False  # Disabled: Chromium uses 6+ GB RAM, incompatible with this VPS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from database.models import Circular, Ministry
from scrapers.utils import KNOWN_CIRCULAR_PAGES, is_circular_url, make_fingerprint
from summarizer.groq_summarizer import summarize_circular

logger = logging.getLogger(__name__)

MAX_CIRCULARS_PER_MINISTRY = 25

_FALLBACK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


def _make_session():
    """curl_cffi Session (Chrome TLS fingerprint) or plain requests Session."""
    if _CURL_AVAILABLE:
        return CurlSession(impersonate="chrome120")
    s = requests.Session()
    s.headers.update(_FALLBACK_HEADERS)
    return s


def _get(session, url: str, timeout: int = 15):
    """GET with SSL fallback for .gov.in sites with bad certs."""
    try:
        return session.get(url, timeout=(5, timeout), verify=True)
    except Exception:
        try:
            return session.get(url, timeout=(5, timeout), verify=False)
        except Exception:
            return requests.get(url, headers=_FALLBACK_HEADERS, timeout=(5, timeout), verify=False)


def _is_circular_candidate(url: str) -> bool:
    lower = url.lower()
    if any(ex in lower for ex in ("press-release", "/press/", "/tender", "/recruitment", "/media/")):
        if "circular" not in lower:
            return False
    if is_circular_url(url):
        return True
    if lower.endswith(".pdf"):
        return True
    if any(kw in lower for kw in ("circular", "office-order", "order-no", "/order/", "gazette")):
        return True
    return False


def _parse_circular_links_from_text(text: str, base_url: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"https?://[^\s\)\]\"']+", text):
        full = match.group(0).rstrip(".,;)")
        if _is_circular_candidate(full):
            found.append(full)
    return list(dict.fromkeys(found))


_CIRCULAR_ANCHOR_WORDS = ("circular", "circulars", "orders", "office order", "gazette", "notification")


def _playwright_fetch_html(url: str) -> tuple[str, str]:
    """Render page with Playwright (handles JS SPAs). Returns (html, resolved_url)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        try:
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                locale="en-IN",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            page = ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto(url, timeout=30000, wait_until="networkidle")
            html = page.content()
            resolved = page.url
        finally:
            browser.close()
    return html, resolved


def _playwright_fetch_text(url: str) -> tuple[str, str]:
    try:
        html, resolved = _playwright_fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)[:20000], resolved
    except Exception as exc:
        logger.warning("Playwright text fetch failed for %s: %s", url, exc)
        return "", url


def _playwright_fetch_links(url: str) -> list[str]:
    try:
        html, resolved = _playwright_fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for tag in soup.find_all("a", href=True):
            full = urljoin(resolved, tag["href"].strip())
            anchor_text = tag.get_text(strip=True).lower()
            if _is_circular_candidate(full) or any(w in anchor_text for w in _CIRCULAR_ANCHOR_WORDS):
                links.append(full)
        return list(dict.fromkeys(links))
    except Exception as exc:
        logger.warning("Playwright link fetch failed for %s: %s", url, exc)
        return []


def _bs4_fetch_links(url: str) -> list[str]:
    try:
        session = _make_session()
        resp = _get(session, url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for tag in soup.find_all("a", href=True):
            full = urljoin(resp.url, tag["href"].strip())
            anchor_text = tag.get_text(strip=True).lower()
            if _is_circular_candidate(full) or any(w in anchor_text for w in _CIRCULAR_ANCHOR_WORDS):
                links.append(full)
        return list(dict.fromkeys(links))
    except Exception as exc:
        logger.warning("Link fetch failed for %s: %s", url, exc)
        return []


def _bs4_fetch_links_with_text(url: str) -> tuple[list[tuple[str, str]], str]:
    """Fetch a listing page and return [(href, anchor_text), ...] plus resolved_url."""
    try:
        session = _make_session()
        resp = _get(session, url)
        resp.raise_for_status()
        # Reject binary/PDF responses
        ct = resp.headers.get("content-type", "")
        if "pdf" in ct or resp.content[:4] == b"%PDF":
            return [], url
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            full = urljoin(resp.url, href)
            anchor = tag.get_text(strip=True)
            anchor_lower = anchor.lower()
            if _is_circular_candidate(full) or any(w in anchor_lower for w in _CIRCULAR_ANCHOR_WORDS):
                results.append((full, anchor))
        return list({r[0]: r for r in results}.values()), resp.url
    except Exception as exc:
        logger.warning("Link+text fetch failed for %s: %s", url, exc)
        return [], url


def _bs4_fetch_text(url: str) -> tuple[str, str]:
    """Return (plain_text, resolved_url). Returns ('', url) on failure. Skips PDFs."""
    try:
        session = _make_session()
        resp = _get(session, url)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "pdf" in ct or resp.content[:4] == b"%PDF":
            return "", url
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)[:20000]
        return text, resp.url
    except Exception as exc:
        logger.warning("Text fetch failed for %s: %s", url, exc)
        return "", url


def _site_reachable(url: str) -> bool:
    """Quick 5-second HEAD check to see if the domain responds at all."""
    try:
        session = _make_session()
        resp = session.head(url, timeout=(5, 5), verify=False, allow_redirects=True)
        return resp.status_code < 400
    except Exception:
        return False


def discover_circular_urls(ministry_url: str) -> list[str]:
    if not _site_reachable(ministry_url):
        logger.warning("Site unreachable, skipping: %s", ministry_url)
        return []
    return list(dict.fromkeys(_bs4_fetch_links(ministry_url)))[:8]


def _parse_nic_table_rows(html: str, base_url: str) -> list[dict]:
    """Parse NIC/Drupal-style circular listing tables (serial | title | category | date | doc)."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        for tr in trs[1:]:
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue
            title = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            category = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            date_str = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            if not title or len(title) < 6:
                continue
            pdf_url = None
            for cell in cells:
                for a in cell.find_all("a", href=True):
                    href = urljoin(base_url, a["href"].strip())
                    if href.lower().endswith(".pdf") or "/sites/default/files/" in href.lower():
                        pdf_url = href
                        break
                if pdf_url:
                    break
            raw_content = f"Title: {title}\nCategory: {category}\nDate: {date_str}"
            if pdf_url:
                raw_content += f"\nDocument: {pdf_url}"
            rows.append({"title": title, "date": date_str, "category": category, "pdf_url": pdf_url, "raw_content": raw_content})
    return rows


def _scrape_table_listing(url: str, max_pages: int = 5) -> list[dict]:
    """Paginate through a NIC/Drupal table listing and collect all circular rows."""
    all_rows: list[dict] = []
    current_url = url
    for _ in range(max_pages):
        html = ""
        resolved_url = current_url
        try:
            session = _make_session()
            resp = _get(session, current_url)
            resp.raise_for_status()
            html = resp.text
            resolved_url = resp.url
        except Exception as exc:
            logger.warning("Table listing fetch failed for %s: %s", current_url, exc)
            if _PLAYWRIGHT_AVAILABLE:
                try:
                    html, resolved_url = _playwright_fetch_html(current_url)
                except Exception:
                    break
            else:
                break
        rows = _parse_nic_table_rows(html, resolved_url)
        all_rows.extend(rows)
        if not rows:
            break
        soup = BeautifulSoup(html, "html.parser")
        next_link = soup.find("a", rel="next") or soup.find("a", string=re.compile(r"Next|›|»", re.I))
        if not next_link or not next_link.get("href"):
            break
        next_url = urljoin(resolved_url, next_link["href"].strip())
        if next_url == current_url:
            break
        current_url = next_url
    return all_rows


_JUNK_TITLE_FRAGMENTS = (
    "customize cookies", "accept cookies", "cookie policy", "cookie consent",
    "page not found", "404", "403 forbidden", "access denied",
    "javascript", "enable javascript", "you are being redirected",
)


def _is_junk_title(title: str) -> bool:
    low = title.lower().strip()
    return any(f in low for f in _JUNK_TITLE_FRAGMENTS) or len(low) < 8


def _save_scraped_circular(
    db: Session,
    ministry: Ministry,
    source_url: str,
    raw_content: str,
    title_hint: str | None = None,
) -> "Circular | None":
    if not raw_content.strip():
        return None

    if db.query(Circular).filter(Circular.source_url == source_url).first():
        return None

    fingerprint = make_fingerprint(source_url, raw_content)
    if db.query(Circular).filter(Circular.fingerprint == fingerprint).first():
        return None

    title = title_hint or raw_content.split("\n", 1)[0][:500] or "Government Circular"
    title = title.strip("# ").strip() or "Government Circular"
    if _is_junk_title(title):
        return None
    summary_data = summarize_circular(title, raw_content, ministry.name)

    circular = Circular(
        ministry_id=ministry.id,
        title=summary_data.get("title") or title,
        source_url=source_url,
        published_date=summary_data.get("published_date"),
        raw_content=raw_content,
        summary=summary_data.get("summary"),
        key_points=summary_data.get("key_points"),
        fingerprint=fingerprint,
    )
    db.add(circular)
    db.commit()
    db.refresh(circular)
    return circular


def _known_circular_url(ministry_name: str) -> str | None:
    name_lower = ministry_name.lower()
    for key, url in KNOWN_CIRCULAR_PAGES.items():
        if key.lower() in name_lower:
            return url
    return None


def scrape_ministry_circulars(db: Session, ministry: Ministry) -> int:
    if not ministry.official_url:
        return 0

    known = _known_circular_url(ministry.name)
    if known:
        listing_urls = [known]
        logger.info("%s: using known circular page %s", ministry.name, known)
    else:
        listing_urls = discover_circular_urls(ministry.official_url)

    if not listing_urls:
        return 0

    saved_count = 0

    # Try table-style scraping first (NIC/Drupal listing pages like icar.gov.in/en/circulars-data)
    for listing_url in listing_urls:
        table_rows = _scrape_table_listing(listing_url)
        if table_rows:
            for row in table_rows[:MAX_CIRCULARS_PER_MINISTRY]:
                source_url = row["pdf_url"] or f"{listing_url}#t{make_fingerprint(listing_url, row['title'])[:16]}"
                saved = _save_scraped_circular(db, ministry, source_url, row["raw_content"], title_hint=row["title"])
                if saved:
                    saved_count += 1
            ministry.last_scraped_at = datetime.utcnow()
            db.commit()
            logger.info("%s: indexed %s circulars (table mode)", ministry.name, saved_count)
            return saved_count

    # Fallback: discover and follow individual circular links
    detail_urls: list[str] = []
    for listing_url in listing_urls:
        text, resolved_url = _bs4_fetch_text(listing_url)
        if text:
            detail_urls.extend(_parse_circular_links_from_text(text, resolved_url))
        detail_urls.extend(_bs4_fetch_links(resolved_url))

    if not detail_urls:
        detail_urls = listing_urls

    detail_urls = list(dict.fromkeys(detail_urls))[:MAX_CIRCULARS_PER_MINISTRY]

    for url in detail_urls:
        text, source_url = _bs4_fetch_text(url)
        if not source_url or not text:
            continue
        saved = _save_scraped_circular(db, ministry, source_url, text)
        if saved:
            saved_count += 1

    ministry.last_scraped_at = datetime.utcnow()
    db.commit()
    logger.info("%s: indexed %s circulars", ministry.name, saved_count)
    return saved_count


def run_firecrawl_scan(db: Session, on_progress=None) -> int:
    ministries = (
        db.query(Ministry)
        .filter(
            Ministry.is_active.is_(True),
            Ministry.has_rss_feed.is_(False),
            Ministry.official_url.isnot(None),
        )
        .all()
    )

    total_new = 0
    total = len(ministries)
    for index, ministry in enumerate(ministries, start=1):
        try:
            found = scrape_ministry_circulars(db, ministry)
            total_new += found
            if on_progress:
                on_progress(ministry.name, index, total, found)
        except Exception as exc:
            logger.exception("Failed scraping %s: %s", ministry.name, exc)
            if on_progress:
                on_progress(ministry.name, index, total, 0)

    logger.info("Scan complete — indexed %s circulars total", total_new)
    return total_new
