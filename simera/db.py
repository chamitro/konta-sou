import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/simera.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from simera import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Additive migrations for databases created by earlier versions."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "fuel_bulletins" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("fuel_bulletins")}
        if "columns" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE fuel_bulletins ADD COLUMN columns VARCHAR(120) DEFAULT ''"))
