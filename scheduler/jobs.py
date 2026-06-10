import logging
import threading
from datetime import datetime

from database.models import Ministry, ScanStatus
from database.session import SessionLocal
from scrapers.circular_scraper import scrape_ministry_circulars
from scrapers.igod_scraper import refresh_ministries
from scrapers.rss_scraper import discover_ministry_rss, poll_ministry_rss
from scheduler import scan_state

logger = logging.getLogger(__name__)


def refresh_ministry_list() -> int:
    db = SessionLocal()
    try:
        return refresh_ministries(db)
    finally:
        db.close()


def job_scan_ministries(ministry_ids: list[int]) -> None:
    db = SessionLocal()
    scan = ScanStatus(scan_type="selected", status="running")
    db.add(scan)
    db.commit()
    db.refresh(scan)

    ministries = (
        db.query(Ministry)
        .filter(Ministry.id.in_(ministry_ids), Ministry.is_active.is_(True))
        .order_by(Ministry.name)
        .all()
    )
    total = len(ministries)
    scan_state.clear_logs()
    scan_state.start(scan.id, total)
    total_new = 0

    try:
        for index, ministry in enumerate(ministries, start=1):
            pct = int(((index - 1) / max(total, 1)) * 100)
            scan_state.set_step(f"Scanning: {ministry.name}", pct, index - 1)
            logger.info("[%s/%s] Scanning %s", index, total, ministry.name)

            try:
                discover_ministry_rss(db, ministry)
                found = 0
                if ministry.has_rss_feed and ministry.rss_feed_url:
                    found = poll_ministry_rss(db, ministry)
                elif ministry.official_url:
                    found = scrape_ministry_circulars(db, ministry)
                else:
                    logger.warning("No official URL for %s", ministry.name)
            except Exception as exc:
                logger.exception("Failed scanning %s: %s", ministry.name, exc)
                found = 0

            total_new += found
            if found:
                scan_state.add_circulars(found)
            logger.info("[%s/%s] Done %s — indexed %s circulars", index, total, ministry.name, found)

        scan.status = "completed"
        scan.new_circulars = total_new
        scan.finished_at = datetime.utcnow()
        scan.message = f"Scanned {total} ministries, indexed {total_new} circulars"
        scan_state.finish("completed", scan.message)
    except Exception as exc:
        logger.exception("Selected scan failed: %s", exc)
        scan.status = "failed"
        scan.finished_at = datetime.utcnow()
        scan.message = str(exc)
        scan_state.finish("failed", str(exc))
    finally:
        db.commit()
        db.close()


def start_selected_scan_background(ministry_ids: list[int]) -> dict:
    if scan_state.is_running():
        return {"status": "already_running", "message": "A scan is already in progress"}

    thread = threading.Thread(target=job_scan_ministries, args=(ministry_ids,), daemon=True)
    thread.start()
    return {
        "status": "started",
        "message": f"Scan started for {len(ministry_ids)} ministries",
    }
