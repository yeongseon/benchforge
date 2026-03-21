from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from benchflow.core.scenario.schema import Scenario, Step
from benchflow.workers.protocol import Worker, WorkerFactory, register_worker

logger = logging.getLogger(__name__)

_PYFORMAT_RE = re.compile(r"%\((\w+)\)s")


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    """Parse mysql://user:password@host:port/database into connect kwargs."""
    parsed = urlparse(dsn)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "database": (parsed.path or "/benchdb").lstrip("/"),
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "autocommit": False,
    }


def _translate_query(query: str, params: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """Convert %(name)s placeholders to %s and return ordered param tuple."""
    ordered: list[Any] = []

    def replacer(match: re.Match[str]) -> str:
        ordered.append(params[match.group(1)])
        return "%s"

    translated = _PYFORMAT_RE.sub(replacer, query)
    return translated, tuple(ordered)


class PyMySQLWorker(Worker):
    def __init__(self) -> None:
        self._dsn: str = ""
        self._conn: Any = None
        self._connect_kwargs: dict[str, Any] = {}

    def setup(self, *, dsn: str, worker_config: dict[str, Any], scenario: Scenario) -> None:
        self._dsn = dsn
        self._connect_kwargs = _parse_mysql_dsn(dsn)

    def open(self) -> None:
        import pymysql

        self._conn = pymysql.connect(**self._connect_kwargs)

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
        """Return MySQL server version and key settings."""
        assert self._conn is not None
        info: dict[str, Any] = {}
        try:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT version()")
                row = cursor.fetchone()
                if row:
                    info["server_version"] = row[0]

                _settings = [
                    "innodb_buffer_pool_size",
                    "max_connections",
                    "innodb_flush_log_at_trx_commit",
                    "sync_binlog",
                ]
                config: dict[str, str] = {}
                for setting in _settings:
                    try:
                        cursor.execute(f"SHOW VARIABLES LIKE '{setting}'")  # noqa: S608
                        row = cursor.fetchone()
                        if row:
                            config[setting] = row[1]
                    except Exception:
                        pass
                if config:
                    info["server_config"] = config
            finally:
                cursor.close()
        except Exception as exc:
            logger.debug("introspect() failed: %s", exc)
        return info

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class PyMySQLWorkerFactory(WorkerFactory):
    def create(self, thread_index: int) -> PyMySQLWorker:
        return PyMySQLWorker()


register_worker("python+pymysql", PyMySQLWorkerFactory)
