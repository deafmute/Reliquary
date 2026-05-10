"""Table structure viewer — columns, indexes, foreign keys, DDL."""

import threading
from typing import Optional, TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib, Pango

if TYPE_CHECKING:
    from .window import ReliquaryWindow
    from .database.manager import ConnectionConfig
    from .database.connection import DatabaseConnection


class StructurePanel(Gtk.Box):
    def __init__(
        self,
        window: 'ReliquaryWindow',
        config: 'ConnectionConfig',
        db: 'DatabaseConnection',
        table: str,
        schema: Optional[str] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._config = config
        self._db = db
        self._table = table
        self._schema = schema

        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Toolbar
        toolbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=8, margin_end=8,
            margin_top=6, margin_bottom=6,
        )
        toolbar.add_css_class('toolbar')

        title_lbl = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        title_lbl.add_css_class('heading')
        qualified = f'{self._schema}.{self._table}' if self._schema else self._table
        title_lbl.set_label(qualified)
        toolbar.append(title_lbl)

        self._spinner = Gtk.Spinner()
        toolbar.append(self._spinner)

        refresh_btn = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Refresh')
        refresh_btn.add_css_class('flat')
        refresh_btn.connect('clicked', lambda *_: self._load())
        toolbar.append(refresh_btn)

        self.append(toolbar)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Notebook: Columns / Indexes / Foreign Keys / DDL
        self._notebook = Gtk.Notebook(vexpand=True)
        self.append(self._notebook)

        self._cols_scroll   = Gtk.ScrolledWindow(vexpand=True)
        self._idx_scroll    = Gtk.ScrolledWindow(vexpand=True)
        self._fk_scroll     = Gtk.ScrolledWindow(vexpand=True)
        self._ddl_scroll    = Gtk.ScrolledWindow(vexpand=True)

        self._notebook.append_page(self._cols_scroll, Gtk.Label(label='Columns'))
        self._notebook.append_page(self._idx_scroll,  Gtk.Label(label='Indexes'))
        self._notebook.append_page(self._fk_scroll,   Gtk.Label(label='Foreign Keys'))
        self._notebook.append_page(self._ddl_scroll,  Gtk.Label(label='DDL'))

    # ── Loading ───────────────────────────────────────────────────────────

    def _load(self):
        self._spinner.set_spinning(True)

        def run():
            try:
                data = self._fetch_structure()
                GLib.idle_add(self._populate, data)
            except Exception as e:
                GLib.idle_add(self._on_error, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _fetch_structure(self) -> dict:
        from sqlalchemy import inspect as sa_inspect, text
        engine = self._db._engine
        insp = sa_inspect(engine)
        schema = self._schema

        columns = insp.get_columns(self._table, schema=schema)
        pk_info = insp.get_pk_constraint(self._table, schema=schema)
        pk_cols = set(pk_info.get('constrained_columns', []))

        try:
            indexes = insp.get_indexes(self._table, schema=schema)
        except Exception:
            indexes = []

        try:
            fks = insp.get_foreign_keys(self._table, schema=schema)
        except Exception:
            fks = []

        # DDL — try dialect-specific query, fallback to None
        ddl = None
        try:
            dialect = engine.dialect.name
            with engine.connect() as conn:
                if dialect == 'sqlite':
                    row = conn.execute(
                        text("SELECT sql FROM sqlite_master WHERE type IN ('table','view') AND name = :n"),
                        {'n': self._table},
                    ).fetchone()
                    ddl = row[0] if row else None
                elif dialect == 'postgresql':
                    # pg_get_ddl requires pg_dump; use a best-effort reconstruction
                    ddl = None
                elif dialect in ('mysql', 'mariadb'):
                    row = conn.execute(text(f'SHOW CREATE TABLE `{self._table}`')).fetchone()
                    ddl = row[1] if row else None
        except Exception:
            pass

        return {
            'columns': columns,
            'pk_cols': pk_cols,
            'indexes': indexes,
            'fks': fks,
            'ddl': ddl,
        }

    def _populate(self, data: dict):
        self._spinner.set_spinning(False)
        self._populate_columns(data['columns'], data['pk_cols'])
        self._populate_indexes(data['indexes'])
        self._populate_fks(data['fks'])
        self._populate_ddl(data['ddl'])

    def _on_error(self, error: str):
        self._spinner.set_spinning(False)
        self._window.toast_error(f'Structure load failed: {error[:80]}')

    # ── Columns tab ───────────────────────────────────────────────────────

    def _populate_columns(self, columns: list, pk_cols: set):
        rows = []
        for col in columns:
            name     = col['name']
            typ      = str(col['type'])
            nullable = 'YES' if col.get('nullable', True) else 'NO'
            default  = str(col.get('default') or '')
            pk       = '✓' if name in pk_cols else ''
            rows.append((pk, name, typ, nullable, default))

        from .results_view import build_results_view
        widget = build_results_view(
            ['PK', 'Name', 'Type', 'Nullable', 'Default'],
            rows,
            show_row_numbers=False,
        )
        self._cols_scroll.set_child(widget)

    # ── Indexes tab ───────────────────────────────────────────────────────

    def _populate_indexes(self, indexes: list):
        if not indexes:
            self._idx_scroll.set_child(_empty_label('No indexes'))
            return

        rows = []
        for idx in indexes:
            name    = idx.get('name') or '(unnamed)'
            cols    = ', '.join(idx.get('column_names', []))
            unique  = '✓' if idx.get('unique') else ''
            rows.append((name, cols, unique))

        from .results_view import build_results_view
        widget = build_results_view(
            ['Name', 'Columns', 'Unique'],
            rows,
            show_row_numbers=False,
        )
        self._idx_scroll.set_child(widget)

    # ── Foreign Keys tab ──────────────────────────────────────────────────

    def _populate_fks(self, fks: list):
        if not fks:
            self._fk_scroll.set_child(_empty_label('No foreign keys'))
            return

        rows = []
        for fk in fks:
            name      = fk.get('name') or '(unnamed)'
            local     = ', '.join(fk.get('constrained_columns', []))
            ref_table = fk.get('referred_table', '')
            if fk.get('referred_schema'):
                ref_table = f"{fk['referred_schema']}.{ref_table}"
            ref_cols  = ', '.join(fk.get('referred_columns', []))
            rows.append((name, local, ref_table, ref_cols))

        from .results_view import build_results_view
        widget = build_results_view(
            ['Constraint', 'Column(s)', 'References Table', 'References Column(s)'],
            rows,
            show_row_numbers=False,
        )
        self._fk_scroll.set_child(widget)

    # ── DDL tab ───────────────────────────────────────────────────────────

    def _populate_ddl(self, ddl: Optional[str]):
        if not ddl:
            self._ddl_scroll.set_child(_empty_label('DDL not available for this database type'))
            return

        # Pretty-print with sqlparse if available
        try:
            import sqlparse
            ddl = sqlparse.format(ddl, reindent=True, keyword_case='upper')
        except ImportError:
            pass

        text_view = Gtk.TextView(
            editable=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.NONE,
            left_margin=12, right_margin=12,
            top_margin=8, bottom_margin=8,
        )
        text_view.get_buffer().set_text(ddl)
        self._ddl_scroll.set_child(text_view)


def _empty_label(msg: str) -> Gtk.Widget:
    lbl = Gtk.Label(
        label=msg,
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.CENTER,
        vexpand=True,
    )
    lbl.add_css_class('dim-label')
    return lbl
