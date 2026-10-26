from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from simera.db import Base


class FuelBulletin(Base):
    """One downloaded bulletin PDF from fuelprices.gr."""

    __tablename__ = "fuel_bulletins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # daily_prefecture | daily_national | weekly
    price_date: Mapped[date] = mapped_column(Date, index=True)
    url: Mapped[str] = mapped_column(String(300), unique=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    rows_parsed: Mapped[int] = mapped_column(Integer, default=0)
    columns: Mapped[str] = mapped_column(String(120), default="")  # fuel types in column order, comma-separated


class FuelPrice(Base):
    """Average retail price for one fuel type in one prefecture on one day (EUR/litre, VAT incl.)."""

    __tablename__ = "fuel_prices"
    __table_args__ = (UniqueConstraint("price_date", "prefecture", "fuel_type", name="uq_fuel_price"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price_date: Mapped[date] = mapped_column(Date, index=True)
    prefecture: Mapped[str] = mapped_column(String(80), index=True)  # as printed, e.g. "ΝΟΜΟΣ ΑΤΤΙΚΗΣ"; "ΕΛΛΑΔΑ" for the weighted national average
    fuel_type: Mapped[str] = mapped_column(String(30), index=True)
    price: Mapped[float] = mapped_column(Float)


class Pharmacy(Base):
    """A pharmacy as listed by a regional pharmacists' association (Attica first)."""

    __tablename__ = "pharmacies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # association's own id
    region: Mapped[str] = mapped_column(String(20), index=True)  # e.g. "attica"
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(200))
    area: Mapped[str] = mapped_column(String(100), index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)


class PharmacyDuty(Base):
    """One pharmacy on duty on one date. Intervals are minutes from 00:00 of duty_date (may exceed 1440)."""

    __tablename__ = "pharmacy_duties"
    __table_args__ = (UniqueConstraint("pharmacy_id", "duty_date", name="uq_pharmacy_duty"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pharmacy_id: Mapped[int] = mapped_column(Integer, index=True)
    duty_date: Mapped[date] = mapped_column(Date, index=True)
    hours_text: Mapped[str] = mapped_column(String(120))
    intervals: Mapped[str] = mapped_column(String(80))  # "480-1380;1020-1920"
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HospitalRota(Base):
    """One downloaded daily hospital duty document (Ministry of Health, Attica)."""

    __tablename__ = "hospital_rotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    duty_date: Mapped[date] = mapped_column(Date, unique=True)
    source_id: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    entries: Mapped[int] = mapped_column(Integer, default=0)


class HospitalDuty(Base):
    """One hospital, one clinic specialty, one shift, one day."""

    __tablename__ = "hospital_duties"
    __table_args__ = (UniqueConstraint("duty_date", "specialty", "shift", "hospital", name="uq_hospital_duty"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    duty_date: Mapped[date] = mapped_column(Date, index=True)
    specialty: Mapped[str] = mapped_column(String(60), index=True)
    shift: Mapped[str] = mapped_column(String(40))  # as printed, e.g. "08:00 – 08:00 επομένης"
    hospital: Mapped[str] = mapped_column(String(120))  # as printed, cleaned
    hospital_key: Mapped[str] = mapped_column(String(40), default="", index=True)  # key into attica_hospitals.json, or ""
    region: Mapped[str] = mapped_column(String(40), default="")
    note: Mapped[str] = mapped_column(String(120), default="")


class HealthCenterDuty(Base):
    __tablename__ = "health_center_duties"
    __table_args__ = (UniqueConstraint("duty_date", "name", name="uq_health_center_duty"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    duty_date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(80))
    hours: Mapped[str] = mapped_column(String(60))
    hospital_key: Mapped[str] = mapped_column(String(40), default="")


class OsmCache(Base):
    """Cached Overpass responses: one row per (category, ~100 m cell, radius)."""

    __tablename__ = "osm_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    payload: Mapped[str] = mapped_column(String)  # JSON list of Overpass elements
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Poi(Base):
    """Place of interest imported from the OpenStreetMap Greece extract (ODbL)."""

    __tablename__ = "pois"
    __table_args__ = (UniqueConstraint("osm_type", "osm_id", name="uq_poi"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    osm_type: Mapped[str] = mapped_column(String(1))  # n / w / r
    osm_id: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    brand: Mapped[str] = mapped_column(String(100), default="")
    lat: Mapped[float] = mapped_column(Float, index=True)
    lng: Mapped[float] = mapped_column(Float, index=True)
    address: Mapped[str] = mapped_column(String(200), default="")
    opening_hours: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    website: Mapped[str] = mapped_column(String(200), default="")
    cuisine: Mapped[str] = mapped_column(String(100), default="")
    extra: Mapped[str] = mapped_column(String(400), default="")  # JSON of a few more tags


class PoiImport(Base):
    __tablename__ = "poi_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(200))
    source_modified: Mapped[str] = mapped_column(String(40), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    count: Mapped[int] = mapped_column(Integer, default=0)


class RailFeed(Base):
    __tablename__ = "rail_feeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(300))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    first_date: Mapped[date] = mapped_column(Date)
    last_date: Mapped[date] = mapped_column(Date)
    stops: Mapped[int] = mapped_column(Integer, default=0)


class RailStation(Base):
    """A metro/tram station: GTFS platform stops grouped by name."""

    __tablename__ = "rail_stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    lat: Mapped[float] = mapped_column(Float, index=True)
    lng: Mapped[float] = mapped_column(Float, index=True)
    stop_ids: Mapped[str] = mapped_column(String(200))  # comma-separated GTFS stop_ids
    lines: Mapped[str] = mapped_column(String(80), default="")  # e.g. "M2,M3"
    wheelchair: Mapped[str] = mapped_column(String(10), default="")


class RailService(Base):
    __tablename__ = "rail_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[str] = mapped_column(String(20), index=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)


class RailDepartures(Base):
    """All scheduled departures at one station for one service day, one line and direction."""

    __tablename__ = "rail_departures"
    __table_args__ = (UniqueConstraint("station_id", "service_id", "line", "destination", name="uq_rail_dep"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, index=True)
    service_id: Mapped[str] = mapped_column(String(20), index=True)
    line: Mapped[str] = mapped_column(String(10))
    destination: Mapped[str] = mapped_column(String(120))
    route_type: Mapped[int] = mapped_column(Integer)  # 0 tram, 1 metro
    times: Mapped[str] = mapped_column(String)  # JSON sorted list of departure seconds since service midnight
