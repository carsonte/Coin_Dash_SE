from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url, URL
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from ..config import DatabaseCfg, ROOT
from .models import Base

logger = logging.getLogger(__name__)


class DatabaseClient:
    def __init__(self, cfg: DatabaseCfg) -> None:
        self.cfg = cfg
        self.enabled = bool(cfg.enabled and cfg.dsn)
        self.engine: Optional[Engine] = None
        self._session_factory: Optional[scoped_session[Session]] = None
        if self.enabled:
            self._setup()

    def _setup(self) -> None:
        url = make_url(self.cfg.dsn)
        engine_kwargs: dict = {"echo": self.cfg.echo, "future": True}
        if url.drivername.startswith("sqlite"):
            url = self._prepare_sqlite_url(url)
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        else:
            engine_kwargs["pool_size"] = self.cfg.pool_size
        self.engine = create_engine(url, **engine_kwargs)
        factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False, future=True)
        self._session_factory = scoped_session(factory)
        if self.cfg.auto_migrate:
            Base.metadata.create_all(self.engine)
            logger.info("Database schema ensured via auto_migrate.")

    @contextmanager
    def session(self) -> Iterator[Session]:
        if not self.enabled or self._session_factory is None:
            yield None
            return
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()

    def _prepare_sqlite_url(self, url: URL) -> URL:
        db_path = url.database or ""
        if db_path not in ("", ":memory:"):
            path_obj = Path(db_path)
            if not path_obj.is_absolute():
                path_obj = ROOT / path_obj
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            url = url.set(database=str(path_obj))
        return url
