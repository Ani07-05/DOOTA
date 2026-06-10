import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.routes import router as api_router
from config import settings
from database.session import SessionLocal, init_db

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

from scheduler.log_handler import ScanLogHandler as _ScanLogHandler
logging.getLogger().addHandler(_ScanLogHandler())

templates = Jinja2Templates(directory="templates")


def _clear_stale_scans() -> None:
    from datetime import datetime

    from database.models import ScanStatus
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        stale = db.query(ScanStatus).filter(ScanStatus.status == "running").all()
        for scan in stale:
            scan.status = "failed"
            scan.finished_at = datetime.utcnow()
            scan.message = "Interrupted — server restarted"
        if stale:
            db.commit()
            logger.info("Cleared %s stale scan(s) from previous session", len(stale))
    finally:
        db.close()


def _seed_ministries_if_empty() -> None:
    from database.models import Ministry
    from scrapers.igod_scraper import refresh_ministries

    db = SessionLocal()
    try:
        count = db.query(Ministry).count()
        if count == 0:
            seeded = refresh_ministries(db)
            logger.info("Fresh database — seeded %s ministries", seeded)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _seed_ministries_if_empty()
    _clear_stale_scans()
    logger.info("Doota ready — manual scan only, no automation")
    yield


app = FastAPI(title="Doota", description="Indian Government Circular Monitor", lifespan=lifespan)
app.include_router(api_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    db = SessionLocal()
    try:
        from sqlalchemy import desc
        from sqlalchemy.orm import joinedload

        from sqlalchemy import func

        from database.models import Circular, Ministry, ScanStatus

        ministries = db.query(Ministry).filter(Ministry.is_active.is_(True)).order_by(Ministry.name).all()
        circular_counts = dict(
            db.query(Circular.ministry_id, func.count(Circular.id))
            .group_by(Circular.ministry_id)
            .all()
        )
        latest_scan = db.query(ScanStatus).order_by(desc(ScanStatus.started_at)).first()
        total_circulars = db.query(Circular).count()
        rss_count = db.query(Ministry).filter(Ministry.has_rss_feed.is_(True)).count()
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "ministries": ministries,
                "circular_counts": circular_counts,
                "latest_scan": latest_scan,
                "total_circulars": total_circulars,
                "rss_count": rss_count,
                "recent_limit": settings.recent_circulars_limit,
            },
        )
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        reload_excludes=["*.db", "data/*"] if settings.debug else None,
    )
