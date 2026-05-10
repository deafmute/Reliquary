import threading
from typing import Callable, Optional
from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import SQLAlchemyError
from gi.repository import GLib

from .manager import ConnectionConfig


class DatabaseConnection:
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._engine = None
        self._connected = False
        self._error: Optional[str] = None

    def connect(self):
        kwargs = dict(pool_pre_ping=True, connect_args=self._connect_args())
        if self.config.driver != 'sqlite':
            kwargs['pool_size'] = 3
            kwargs['max_overflow'] = 2
        self._engine = create_engine(self.config.get_url(), **kwargs)
        with self._engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        self._connected = True
        self._error = None

    def _connect_args(self) -> dict:
        if self.config.driver == 'sqlite':
            return {'check_same_thread': False}
        return {}

    def disconnect(self):
        if self._engine:
            self._engine.dispose()
            self._engine = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> Optional[str]:
        return self._error

    def execute_query(self, sql: str) -> tuple[list[str], list[tuple], int]:
        """Returns (columns, rows, rowcount). Raises on error."""
        with self._engine.connect() as conn:
            result = conn.execute(text(sql))
            if result.returns_rows:
                columns = list(result.keys())
                rows = [tuple(r) for r in result.fetchall()]
                return columns, rows, len(rows)
            else:
                conn.commit()
                return [], [], result.rowcount

    def execute_async(
        self,
        sql: str,
        on_success: Callable[[list[str], list[tuple], int], None],
        on_error: Callable[[str], None],
    ):
        def run():
            try:
                columns, rows, rowcount = self.execute_query(sql)
                GLib.idle_add(on_success, columns, rows, rowcount)
            except Exception as e:
                self._error = str(e)
                GLib.idle_add(on_error, str(e))

        threading.Thread(target=run, daemon=True).start()

    def fetch_table_data_async(
        self,
        table: str,
        schema: Optional[str],
        offset: int,
        limit: int,
        on_success: Callable,
        on_error: Callable,
    ):
        def run():
            try:
                qualified = f'"{schema}"."{table}"' if schema else f'"{table}"'
                sql = f'SELECT * FROM {qualified} LIMIT {limit} OFFSET {offset}'
                columns, rows, _ = self.execute_query(sql)

                count_sql = f'SELECT COUNT(*) FROM {qualified}'
                _, count_rows, _ = self.execute_query(count_sql)
                total = count_rows[0][0] if count_rows else 0

                GLib.idle_add(on_success, columns, rows, total)
            except Exception as e:
                GLib.idle_add(on_error, str(e))

        threading.Thread(target=run, daemon=True).start()
