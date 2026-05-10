"""GtkSource 5 SQL completion provider."""

import threading
from typing import Optional

from gi.repository import GObject, Gio, GLib, GtkSource

SQL_KEYWORDS = [
    'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER',
    'FULL', 'CROSS', 'ON', 'AND', 'OR', 'NOT', 'IN', 'EXISTS', 'BETWEEN',
    'LIKE', 'ILIKE', 'IS', 'NULL', 'TRUE', 'FALSE',
    'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE',
    'CREATE', 'TABLE', 'VIEW', 'INDEX', 'DROP', 'ALTER', 'ADD', 'COLUMN',
    'TRUNCATE', 'RENAME', 'TO',
    'ORDER', 'BY', 'GROUP', 'HAVING', 'LIMIT', 'OFFSET',
    'DISTINCT', 'ALL', 'AS', 'UNION', 'INTERSECT', 'EXCEPT',
    'WITH', 'RECURSIVE', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
    'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES', 'UNIQUE', 'CHECK',
    'DEFAULT', 'NOT NULL', 'AUTO_INCREMENT', 'SERIAL',
    'CAST', 'COALESCE', 'NULLIF', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
    'NOW', 'CURRENT_DATE', 'CURRENT_TIMESTAMP', 'DATE', 'TIME', 'TIMESTAMP',
    'EXTRACT', 'INTERVAL', 'RETURNING',
    'INTEGER', 'INT', 'BIGINT', 'SMALLINT', 'TEXT', 'VARCHAR', 'CHAR',
    'BOOLEAN', 'BOOL', 'FLOAT', 'DOUBLE', 'REAL', 'NUMERIC', 'DECIMAL',
    'BYTEA', 'BLOB', 'JSON', 'JSONB', 'UUID', 'ARRAY',
    'EXPLAIN', 'ANALYZE', 'VACUUM', 'BEGIN', 'COMMIT', 'ROLLBACK',
    'TRANSACTION', 'SAVEPOINT', 'RELEASE',
    'SCHEMA', 'DATABASE', 'USE',
]


class CompletionItem(GObject.Object, GtkSource.CompletionProposal):
    __gtype_name__ = 'ReliquaryCompletionItem'

    def __init__(self, label: str, typed_text: str, kind: str = 'keyword'):
        super().__init__()
        self.label = label
        self.typed_text = typed_text
        self.kind = kind  # 'keyword' | 'table' | 'view' | 'column' | 'schema'


class SQLCompletionProvider(GObject.Object, GtkSource.CompletionProvider):
    __gtype_name__ = 'ReliquarySQLCompletionProvider'

    def __init__(self):
        super().__init__()
        self._tables:  list[str] = []
        self._views:   list[str] = []
        self._columns: list[str] = []
        self._schemas: list[str] = []
        self._pending_store: Optional[Gio.ListStore] = None

    # ── Schema cache update (called when editor opens / schema loads) ──────

    def update_schema(
        self,
        tables:  list[str] = (),
        views:   list[str] = (),
        columns: list[str] = (),
        schemas: list[str] = (),
    ):
        self._tables  = list(tables)
        self._views   = list(views)
        self._columns = list(columns)
        self._schemas = list(schemas)

    def load_schema_async(self, db, schema: Optional[str] = None):
        """Background-load schema items from a live connection."""
        def run():
            try:
                from .database.introspect import get_tables, get_columns, get_schemas
                engine = db._engine

                schemas = get_schemas(engine)
                tables_raw = get_tables(engine, schema)
                tables  = [t['name'] for t in tables_raw if t['kind'] == 'table']
                views   = [t['name'] for t in tables_raw if t['kind'] == 'view']

                # Collect columns for all tables (limited to first 20 to avoid stalling)
                cols: set[str] = set()
                for tbl in tables[:20]:
                    for col in get_columns(engine, tbl, schema):
                        cols.add(col['name'])

                def apply():
                    self.update_schema(tables=tables, views=views,
                                       columns=list(cols), schemas=schemas)
                    return False
                GLib.idle_add(apply)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    # ── GtkSource.CompletionProvider vfuncs ───────────────────────────────

    def do_get_title(self) -> str:
        return 'SQL'

    def do_get_priority(self, context: GtkSource.CompletionContext) -> int:
        return 100

    def do_is_trigger(self, location, ch: str) -> bool:
        return ch.isalpha() or ch in ('_',)

    def do_populate_async(
        self,
        context: GtkSource.CompletionContext,
        cancellable: Optional[Gio.Cancellable],
        callback,
        user_data=None,
    ):
        word = (context.get_word() or '').lower()
        store = Gio.ListStore(item_type=CompletionItem)

        seen: set[str] = set()

        def add(label: str, kind: str):
            if label.lower() not in seen:
                seen.add(label.lower())
                store.append(CompletionItem(label, label, kind))

        if word:
            # Schema items first (higher relevance) — case-insensitive prefix match
            for name in self._schemas:
                if name.lower().startswith(word):
                    add(name, 'schema')
            for name in self._tables:
                if name.lower().startswith(word):
                    add(name, 'table')
            for name in self._views:
                if name.lower().startswith(word):
                    add(name, 'view')
            for name in self._columns:
                if name.lower().startswith(word):
                    add(name, 'column')
            for kw in SQL_KEYWORDS:
                if kw.lower().startswith(word):
                    add(kw, 'keyword')
        else:
            # No prefix typed — show schema objects only
            for name in self._tables[:30]:
                add(name, 'table')
            for name in self._views[:10]:
                add(name, 'view')

        self._pending_store = store

        task = Gio.Task.new(self, cancellable, callback)
        task.return_boolean(True)

    def do_populate_finish(
        self,
        result: Gio.AsyncResult,
    ) -> Optional[Gio.ListModel]:
        return self._pending_store

    def do_activate(
        self,
        context: GtkSource.CompletionContext,
        proposal: CompletionItem,
    ):
        buf = context.get_buffer()
        word = context.get_word() or ''

        end_iter = buf.get_iter_at_mark(buf.get_insert())
        start_iter = end_iter.copy()
        if word:
            start_iter.backward_chars(len(word))

        buf.begin_user_action()
        buf.delete(start_iter, end_iter)
        new_iter = buf.get_iter_at_mark(buf.get_insert())
        buf.insert(new_iter, proposal.typed_text)
        buf.end_user_action()

    def do_display(
        self,
        context: GtkSource.CompletionContext,
        proposal: CompletionItem,
        cell: GtkSource.CompletionCell,
    ):
        col = cell.get_column()
        if col == GtkSource.CompletionColumn.TYPED_TEXT:
            cell.set_text(proposal.typed_text)
        elif col == GtkSource.CompletionColumn.COMMENT:
            cell.set_text(proposal.kind)
        elif col == GtkSource.CompletionColumn.ICON:
            icon = {
                'keyword': 'lang-define-symbolic',
                'table':   'x-office-spreadsheet-symbolic',
                'view':    'view-list-symbolic',
                'column':  'input-dialpad-symbolic',
                'schema':  'folder-symbolic',
            }.get(proposal.kind, 'text-x-generic-symbolic')
            cell.set_icon_name(icon)


def attach_completion(source_view: GtkSource.View) -> SQLCompletionProvider:
    """Attach a fresh provider to a GtkSourceView and return it."""
    provider = SQLCompletionProvider()
    completion = source_view.get_completion()
    completion.add_provider(provider)

    # Also add the built-in words provider for buffer-scanned completion
    words_provider = GtkSource.CompletionWords.new('Buffer Words')
    words_provider.register(source_view.get_buffer())
    completion.add_provider(words_provider)

    return provider
