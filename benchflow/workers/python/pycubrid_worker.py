from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from benchflow.core.scenario.schema import Scenario, Step
from benchflow.workers.protocol import Worker, WorkerFactory, register_worker

logger = logging.getLogger(__name__)

_PYFORMAT_RE = re.compile(r"%\((\w+)\)s")


def _parse_cubrid_dsn(dsn: str) -> dict[str, Any]:
    """Parse cubrid://user:password@host:port/database into connect kwargs."""
    parsed = urlparse(dsn)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 33000,
        "database": (parsed.path or "/benchdb").lstrip("/"),
        "user": parsed.username or "dba",
        "password": parsed.password or "",
    }


def _translate_query(query: str, params: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """Convert %(name)s placeholders to ? and return ordered param tuple."""
    ordered: list[Any] = []

    def replacer(match: re.Match[str]) -> str:
        ordered.append(params[match.group(1)])
        return "?"

    translated = _PYFORMAT_RE.sub(replacer, query)
    return translated, tuple(ordered)


class PyCUBRIDWorker(Worker):
    def __init__(self) -> None:
        self._dsn: str = ""
        self._conn: Any = None
        self._connect_kwargs: dict[str, Any] = {}

    def setup(self, *, dsn: str, worker_config: dict[str, Any], scenario: Scenario) -> None:
        self._dsn = dsn
        self._connect_kwargs = _parse_cubrid_dsn(dsn)

    def open(self) -> None:
        import pycubrid

        self._conn = pycubrid.connect(**self._connect_kwargs)

    def execute(self, step: Step) -> None:
        assert self._conn is not None
        params = step.resolve_params()
        cursor = self._conn.cursor()
        try:
            if params:
                query, ordered_params = _translate_query(step.query, params)
                cursor.execute(query, ordered_params)
            else:
                cursor.execute(step.query)
            cursor.fetchall()
        finally:
            cursor.close()

    def execute_raw(self, query: str) -> None:
        """Execute a raw SQL query for setup/teardown."""
        assert self._conn is not None
        cursor = self._conn.cursor()
        try:
            cursor.execute(query)
            self._conn.commit()
        finally:
            cursor.close()

    def introspect(self) -> dict[str, Any]:
        """Return CUBRID server version."""
        assert self._conn is not None
        info: dict[str, Any] = {}
        try:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT version()")
                row = cursor.fetchone()
                if row:
                    info["server_version"] = row[0]
            finally:
                cursor.close()
        except Exception as exc:
            logger.debug("introspect() failed: %s", exc)
        return info

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class PyCUBRIDWorkerFactory(WorkerFactory):
    def create(self, thread_index: int) -> PyCUBRIDWorker:
        return PyCUBRIDWorker()


register_worker("python+pycubrid", PyCUBRIDWorkerFactory)
