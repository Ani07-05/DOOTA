import asyncio
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload

from database.models import Circular, Ministry, ScanStatus
from database.session import get_db
from scheduler import scan_state
from scheduler.jobs import refresh_ministry_list, start_selected_scan_background

router = APIRouter()


class ScanRequest(BaseModel):
    ministry_ids: list[int] = Field(..., min_length=1)


@router.get("/progress")
def get_scan_progress():
    return scan_state.get_progress()


@router.get("/scan/stream")
async def scan_log_stream(offset: int = 0):
    async def generator():
        sent = offset
        idle_ticks = 0
        while True:
            lines, total = scan_state.get_logs_from(sent)
            for line in lines:
                safe = line.replace("\n", " ").replace("\r", "")
                yield f"data: {safe}\n\n"
            sent += len(lines)

            if scan_state.is_running():
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks >= 6:  # 3 s of silence after scan ends
                    yield "event: done\ndata: \n\n"
                    return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/scan/progress")
def get_scan_progress_legacy():
    return scan_state.get_progress()


@router.post("/scan")
def trigger_scan(body: ScanRequest):
    return start_selected_scan_background(body.ministry_ids)


@router.post("/refresh-ministries")
def trigger_refresh():
    count = refresh_ministry_list()
    return {"status": "ok", "message": f"Refreshed {count} ministries from igod.gov.in"}


@router.get("/ministries")
def list_ministries(db: Session = Depends(get_db)):
    ministries = db.query(Ministry).filter(Ministry.is_active.is_(True)).order_by(Ministry.name).all()
    counts = dict(
        db.query(Circular.ministry_id, func.count(Circular.id))
        .group_by(Circular.ministry_id)
        .all()
    )
    return [
        {
            "id": m.id,
            "name": m.name,
            "abbreviation": m.abbreviation,
            "org_type": m.org_type,
            "official_url": m.official_url,
            "has_rss_feed": m.has_rss_feed,
            "last_scraped_at": m.last_scraped_at,
            "circular_count": counts.get(m.id, 0),
        }
        for m in ministries
    ]


@router.get("/circulars")
def list_circulars(
    ministry_id: int | None = Query(None),
    ministry: str | None = Query(None),
    days: int = Query(3650, ge=1, le=3650),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Circular).options(joinedload(Circular.ministry))
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = query.filter(Circular.discovered_at >= cutoff)

    if ministry_id is not None:
        query = query.filter(Circular.ministry_id == ministry_id)
    elif ministry:
        query = query.join(Ministry).filter(
            (Ministry.abbreviation == ministry) | (Ministry.name.ilike(f"%{ministry}%"))
        )

    total = query.count()
    items = (
        query.order_by(desc(Circular.discovered_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": c.id,
                "title": c.title,
                "ministry": c.ministry.name,
                "abbreviation": c.ministry.abbreviation,
                "source_url": c.source_url,
                "published_date": c.published_date,
                "summary": c.summary,
                "key_points": json.loads(c.key_points) if c.key_points else [],
                "discovered_at": c.discovered_at,
            }
            for c in items
        ],
    }


@router.get("/circulars/{circular_id}")
def get_circular(circular_id: int, db: Session = Depends(get_db)):
    circular = (
        db.query(Circular)
        .options(joinedload(Circular.ministry))
        .filter(Circular.id == circular_id)
        .first()
    )
    if not circular:
        raise HTTPException(status_code=404, detail="Circular not found")

    return {
        "id": circular.id,
        "title": circular.title,
        "ministry": circular.ministry.name,
        "abbreviation": circular.ministry.abbreviation,
        "source_url": circular.source_url,
        "published_date": circular.published_date,
        "summary": circular.summary,
        "key_points": json.loads(circular.key_points) if circular.key_points else [],
        "raw_content": circular.raw_content,
        "discovered_at": circular.discovered_at,
    }


@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    latest_scans = (
        db.query(ScanStatus)
        .order_by(desc(ScanStatus.started_at))
        .limit(5)
        .all()
    )
    return {
        "ministries": db.query(Ministry).filter(Ministry.is_active.is_(True)).count(),
        "circulars": db.query(Circular).count(),
        "rss_ministries": db.query(Ministry).filter(Ministry.has_rss_feed.is_(True)).count(),
        "live_scan": scan_state.get_progress(),
        "recent_scans": [
            {
                "scan_type": s.scan_type,
                "status": s.status,
                "new_circulars": s.new_circulars,
                "started_at": s.started_at,
                "finished_at": s.finished_at,
                "message": s.message,
            }
            for s in latest_scans
        ],
    }
