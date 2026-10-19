import sqlite3

from sqlalchemy import event
from sqlalchemy.engine import Engine


def configure_sqlite_engine(app, db):
    busy_ms = app.config.get("DB_BUSY_TIMEOUT_MS", 10000)

    @event.listens_for(Engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):
        if not isinstance(dbapi_connection, sqlite3.Connection):
            return
        cur = dbapi_connection.cursor()
        cur.execute(f"PRAGMA busy_timeout={busy_ms}")
        try:
            cur.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        cur.close()
