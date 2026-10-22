"""Database engine/session. Tables are created by Alembic migrations (alembic upgrade head);
for the zero-configuration demo the app also runs `create_all` at startup when
RHOB_AUTO_CREATE_TABLES=true (default in demo)."""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings
from .models import Base

_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url
        kw = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kw)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db():
    e = engine()
    if os.getenv("RHOB_AUTO_CREATE_TABLES", "true").lower() == "true":
        Base.metadata.create_all(e)


def db_ok() -> bool:
    try:
        with engine().connect() as c:
            c.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


@contextmanager
def session():
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
