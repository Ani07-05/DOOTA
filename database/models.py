from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Ministry(Base):
    __tablename__ = "ministries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(50))
    org_type: Mapped[str] = mapped_column(String(20), default="ministry")
    igod_url: Mapped[str | None] = mapped_column(String(1000))
    official_url: Mapped[str | None] = mapped_column(String(1000))
    rss_feed_url: Mapped[str | None] = mapped_column(String(1000))
    has_rss_feed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    circulars: Mapped[list["Circular"]] = relationship(back_populates="ministry")


class Circular(Base):
    __tablename__ = "circulars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ministry_id: Mapped[int] = mapped_column(ForeignKey("ministries.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True)
    published_date: Mapped[str | None] = mapped_column(String(100))
    raw_content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    key_points: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    ministry: Mapped["Ministry"] = relationship(back_populates="circulars")


class ScanStatus(Base):
    __tablename__ = "scan_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_type: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")
    new_circulars: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
