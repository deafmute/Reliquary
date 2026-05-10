import threading
from typing import Optional, TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib, GObject, Gio, Pango

if TYPE_CHECKING:
    from .window import ReliquaryWindow
    from .database.manager import ConnectionConfig
    from .database.connection import DatabaseConnection

PAGE_SIZE = 500


class _DataRow(GObject.Object):
    __gtype_name__ = 'ReliquaryTableDataRow'

    def __init__(self, values: list, raw: list):
        super().__init__()
        self._values = ['' if v is None else str(v) for v in values]
        self._raw = raw  # original Python values for UPDATE/DELETE

    def get(self, index: int) -> str:
        return self._values[index] if 0 <= index < len(self._values) else ''

    def raw(self, index: int):
        return self._raw[index] if 0 <= index < len(self._raw) else None


class TablePanel(Gtk.Box):
    """Browse and edit table data."""

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
        self._offset = 0
        self._total = 0
        self._columns: list[str] = []
        self._col_info: list[dict] = []
        self._pk_cols: list[str] = []
        self._sort_col: Optional[str] = None
        self._sort_asc: bool = True
        self._filter_sql: str = ''

        self._store = Gio.ListStore(item_type=_DataRow)
        self._selection = Gtk.SingleSelection(model=self._store)
        self._selection.set_autoselect(False)
        self._col_view: Optional[Gtk.ColumnView] = None

        self._build_ui()
        self._load_schema_then_data()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header widget (CRUD buttons) must be created first so self._edit_btn
        # and self._delete_btn exist before _on_selection_changed can fire.
        self._header_widget = self._build_header_widget()

        # Wrap in Adw.ToolbarView for proper Adwaita toolbar styling
        toolbar_view = Adw.ToolbarView()
        self.append(toolbar_view)

        # ── Toolbar ───────────────────────────────────────────────────────
        toolbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            margin_start=8, margin_end=8,
            margin_top=4, margin_bottom=4,
        )

        # Table name is shown in the window header; show count + spinner here
        spacer = Gtk.Box(hexpand=True)
        toolbar.append(spacer)

        self._count_label = Gtk.Label(label='')
        self._count_label.add_css_class('dim-label')
        self._count_label.add_css_class('caption')
        toolbar.append(self._count_label)

        self._spinner = Gtk.Spinner()
        toolbar.append(self._spinner)

        # Secondary actions
        sec_group = Gtk.Box(spacing=0, margin_start=4)

        self._filter_btn = Gtk.ToggleButton(
            icon_name='edit-find-symbolic',
            tooltip_text='Filter rows',
        )
        self._filter_btn.add_css_class('flat')
        self._filter_btn.connect('toggled', self._on_filter_toggled)
        sec_group.append(self._filter_btn)

        import_btn = Gtk.Button(icon_name='document-import-symbolic', tooltip_text='Import CSV…')
        import_btn.add_css_class('flat')
        import_btn.connect('clicked', self._on_import_csv)
        sec_group.append(import_btn)

        refresh_btn = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Refresh')
        refresh_btn.add_css_class('flat')
        refresh_btn.connect('clicked', lambda *_: self._load_page())
        sec_group.append(refresh_btn)

        editor_btn = Gtk.Button(
            icon_name='accessories-text-editor-symbolic',
            tooltip_text='Open in query editor',
        )
        editor_btn.add_css_class('flat')
        editor_btn.connect('clicked', self._open_in_editor)
        sec_group.append(editor_btn)

        toolbar.append(sec_group)

        toolbar_view.add_top_bar(toolbar)

        # ── Content box (filter bar + data stack + pagination) ────────────
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        toolbar_view.set_content(content_box)

        # Filter bar
        self._filter_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
        )
        filter_box = Gtk.Box(
            spacing=6,
            margin_start=8, margin_end=8,
            margin_top=4, margin_bottom=4,
        )
        filter_prefix = Gtk.Label(label='WHERE')
        filter_prefix.add_css_class('dim-label')
        filter_prefix.add_css_class('monospace')
        self._filter_entry = Gtk.Entry(
            hexpand=True,
            placeholder_text='e.g. id > 100 AND name LIKE \'%foo%\'',
        )
        self._filter_entry.add_css_class('monospace')
        self._filter_entry.connect('activate', self._on_filter_activate)
        apply_btn = Gtk.Button(label='Apply')
        apply_btn.connect('clicked', self._on_filter_activate)
        clear_btn = Gtk.Button(label='Clear')
        clear_btn.add_css_class('flat')
        clear_btn.connect('clicked', self._on_filter_clear)
        filter_box.append(filter_prefix)
        filter_box.append(self._filter_entry)
        filter_box.append(apply_btn)
        filter_box.append(clear_btn)
        self._filter_revealer.set_child(filter_box)
        content_box.append(self._filter_revealer)
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Stack: loading / table / error
        self._stack = Gtk.Stack(vexpand=True)

        loading_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True,
        )
        spin = Gtk.Spinner(spinning=True)
        spin.set_size_request(32, 32)
        loading_box.append(spin)
        loading_box.append(Gtk.Label(label='Loading…'))
        self._stack.add_named(loading_box, 'loading')

        self._table_scroll = Gtk.ScrolledWindow(vexpand=True)
        self._stack.add_named(self._table_scroll, 'table')

        self._error_page = Adw.StatusPage(title='Error', icon_name='dialog-error-symbolic')
        self._stack.add_named(self._error_page, 'error')

        content_box.append(self._stack)
        self._stack.set_visible_child_name('loading')

        # Pagination
        pager = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
            halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6,
        )
        self._prev_btn = Gtk.Button(
            icon_name='go-previous-symbolic', tooltip_text='Previous page', sensitive=False,
        )
        self._prev_btn.add_css_class('flat')
        self._prev_btn.connect('clicked', self._on_prev)

        self._page_label = Gtk.Label(label='')
        self._page_label.add_css_class('dim-label')
        self._page_label.set_width_chars(16)

        self._next_btn = Gtk.Button(
            icon_name='go-next-symbolic', tooltip_text='Next page', sensitive=False,
        )
        self._next_btn.add_css_class('flat')
        self._next_btn.connect('clicked', self._on_next)

        pager.append(self._prev_btn)
        pager.append(self._page_label)
        pager.append(self._next_btn)
        content_box.append(pager)

        # Selection changes
        self._selection.connect('notify::selected', self._on_selection_changed)

    # ── Header widget (CRUD actions shown in window header bar) ───────────

    def _build_header_widget(self) -> Gtk.Box:
        box = Gtk.Box(spacing=0, valign=Gtk.Align.CENTER)
        box.add_css_class('linked')

        add_btn = Gtk.Button(icon_name='list-add-symbolic', tooltip_text='Add row')
        add_btn.add_css_class('flat')
        add_btn.connect('clicked', self._on_add_row)
        box.append(add_btn)

        self._edit_btn = Gtk.Button(
            icon_name='document-edit-symbolic',
            tooltip_text='Edit selected row',
            sensitive=False,
        )
        self._edit_btn.add_css_class('flat')
        self._edit_btn.connect('clicked', self._on_edit_row)
        box.append(self._edit_btn)

        self._delete_btn = Gtk.Button(
            icon_name='edit-delete-symbolic',
            tooltip_text='Delete selected row',
            sensitive=False,
        )
        self._delete_btn.add_css_class('flat')
        self._delete_btn.connect('clicked', self._on_delete_row)
        box.append(self._delete_btn)

        return box

    def get_header_widget(self) -> Gtk.Widget:
        return self._header_widget

    # ── Schema + initial load ──────────────────────────────────────────────

    def _load_schema_then_data(self):
        self._stack.set_visible_child_name('loading')
        self._spinner.set_spinning(True)

        def run():
            try:
                from sqlalchemy import inspect as sa_inspect
                engine = self._db._engine
                insp = sa_inspect(engine)
                col_info = insp.get_columns(self._table, schema=self._schema)
                pk_info = insp.get_pk_constraint(self._table, schema=self._schema)
                pk_cols = pk_info.get('constrained_columns', [])
                GLib.idle_add(lambda: self._on_schema_loaded(col_info, pk_cols))
            except Exception as e:
                GLib.idle_add(lambda: self._on_error(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _on_schema_loaded(self, col_info: list, pk_cols: list):
        self._col_info = col_info
        self._pk_cols = pk_cols
        self._columns = [c['name'] for c in col_info]
        self._build_column_view()
        self._load_page()

    def _build_column_view(self):
        col_view = Gtk.ColumnView(model=self._selection)
        col_view.set_show_row_separators(True)
        col_view.set_show_column_separators(True)
        col_view.set_reorderable(True)
        col_view.set_vexpand(True)
        col_view.set_hexpand(True)
        col_view.add_css_class('data-table')
        col_view.connect('activate', self._on_row_activated)

        # Row number column
        num_factory = Gtk.SignalListItemFactory()
        num_factory.connect('setup', self._setup_num_cell)
        num_factory.connect('bind', self._bind_num_cell)
        num_col = Gtk.ColumnViewColumn(title='#', factory=num_factory)
        num_col.set_fixed_width(52)
        col_view.append_column(num_col)

        for i, col in enumerate(self._col_info):
            name = col['name']
            factory = Gtk.SignalListItemFactory()
            factory.connect('setup', self._setup_data_cell)
            factory.connect('bind', self._make_bind(i))
            vcol = Gtk.ColumnViewColumn(title=name, factory=factory)
            vcol.set_resizable(True)
            vcol.set_expand(i == len(self._col_info) - 1)
            # Header click → sort
            vcol.connect('notify::sort-order', lambda c, _, n=name: self._on_col_sort(n, c))
            col_view.append_column(vcol)

        self._col_view = col_view
        self._table_scroll.set_child(col_view)

    # ── Cell factories ─────────────────────────────────────────────────────

    def _setup_num_cell(self, factory, list_item):
        lbl = Gtk.Label(xalign=1, margin_start=8, margin_end=8)
        lbl.add_css_class('dim-label')
        lbl.add_css_class('numeric')
        list_item.set_child(lbl)

    def _bind_num_cell(self, factory, list_item):
        list_item.get_child().set_label(str(list_item.get_position() + 1))

    def _setup_data_cell(self, factory, list_item):
        lbl = Gtk.Label(
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=40,
            margin_start=8, margin_end=8,
            margin_top=4, margin_bottom=4,
        )
        lbl.set_selectable(True)
        list_item.set_child(lbl)

    def _make_bind(self, col_index: int):
        def on_bind(factory, list_item, idx=col_index):
            row: _DataRow = list_item.get_item()
            lbl: Gtk.Label = list_item.get_child()
            val = row.get(idx)
            lbl.set_label(val)
            if val == '':
                lbl.add_css_class('dim-label')
            else:
                lbl.remove_css_class('dim-label')
        return on_bind

    # ── Data loading ───────────────────────────────────────────────────────

    def _load_page(self):
        self._spinner.set_spinning(True)

        where = self._filter_sql.strip()
        order = ''
        if self._sort_col:
            direction = 'ASC' if self._sort_asc else 'DESC'
            order = f' ORDER BY "{self._sort_col}" {direction}'

        def run():
            try:
                from sqlalchemy import text
                engine = self._db._engine
                schema = self._schema
                qualified = f'"{schema}"."{self._table}"' if schema else f'"{self._table}"'

                with engine.connect() as conn:
                    count_sql = f'SELECT COUNT(*) FROM {qualified}'
                    if where:
                        count_sql += f' WHERE {where}'
                    total = conn.execute(text(count_sql)).scalar() or 0

                    data_sql = f'SELECT * FROM {qualified}'
                    if where:
                        data_sql += f' WHERE {where}'
                    data_sql += order
                    data_sql += f' LIMIT {PAGE_SIZE} OFFSET {self._offset}'
                    result = conn.execute(text(data_sql))
                    rows = result.fetchall()
                    cols = list(result.keys())

                GLib.idle_add(lambda: self._on_data_loaded(cols, rows, total))
            except Exception as e:
                GLib.idle_add(lambda: self._on_error(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _on_data_loaded(self, cols: list, rows, total: int):
        self._spinner.set_spinning(False)
        self._total = total
        if not self._columns:
            self._columns = cols

        self._store.remove_all()
        for row in rows:
            raw = list(row)
            self._store.append(_DataRow(raw, raw))

        self._stack.set_visible_child_name('table')

        page_num = self._offset // PAGE_SIZE + 1
        page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self._count_label.set_label(f'{total:,} rows')
        self._page_label.set_label(f'Page {page_num} of {page_count}')
        self._prev_btn.set_sensitive(self._offset > 0)
        self._next_btn.set_sensitive(self._offset + PAGE_SIZE < total)

    def _on_error(self, error: str):
        self._spinner.set_spinning(False)
        self._error_page.set_description(error)
        self._stack.set_visible_child_name('error')

    # ── Selection ──────────────────────────────────────────────────────────

    def _on_selection_changed(self, *_):
        has_sel = self._selection.get_selected() != Gtk.INVALID_LIST_POSITION
        self._edit_btn.set_sensitive(has_sel)
        self._delete_btn.set_sensitive(has_sel)

    def _selected_row(self) -> Optional[_DataRow]:
        pos = self._selection.get_selected()
        if pos == Gtk.INVALID_LIST_POSITION:
            return None
        return self._store.get_item(pos)

    # ── Add / Edit / Delete ────────────────────────────────────────────────

    def _on_row_activated(self, col_view, position):
        row = self._store.get_item(position)
        if row:
            self._show_row_dialog(row)

    def _on_add_row(self, *_):
        self._show_row_dialog(None)

    def _on_edit_row(self, *_):
        row = self._selected_row()
        if row:
            self._show_row_dialog(row)

    def _show_row_dialog(self, existing_row: Optional[_DataRow]):
        from .row_edit_dialog import RowEditDialog
        dialog = RowEditDialog(
            parent=self._window,
            col_info=self._col_info,
            pk_cols=self._pk_cols,
            existing_row=existing_row,
            on_save=self._execute_row_save,
        )
        dialog.present(self._window)

    def _execute_row_save(self, col_info, pk_cols, existing_row, values: dict):
        """Run INSERT or UPDATE in a thread."""
        def run():
            try:
                schema = self._schema
                qualified = f'"{schema}"."{self._table}"' if schema else f'"{self._table}"'
                from sqlalchemy import text
                engine = self._db._engine
                with engine.connect() as conn:
                    if existing_row is None:
                        # INSERT
                        cols = ', '.join(f'"{k}"' for k in values)
                        placeholders = ', '.join(f':{k}' for k in values)
                        sql = f'INSERT INTO {qualified} ({cols}) VALUES ({placeholders})'
                        conn.execute(text(sql), values)
                    else:
                        # UPDATE
                        if not pk_cols:
                            raise ValueError('Cannot UPDATE: no primary key defined')
                        set_clause = ', '.join(
                            f'"{k}" = :{k}' for k in values if k not in pk_cols
                        )
                        where_clause = ' AND '.join(
                            f'"{k}" = :pk_{k}' for k in pk_cols
                        )
                        params = {k: v for k, v in values.items() if k not in pk_cols}
                        for k in pk_cols:
                            idx = next(i for i, c in enumerate(col_info) if c['name'] == k)
                            params[f'pk_{k}'] = existing_row.raw(idx)
                        sql = f'UPDATE {qualified} SET {set_clause} WHERE {where_clause}'
                        conn.execute(text(sql), params)
                    conn.commit()
                GLib.idle_add(lambda: (self._window.toast('Saved'), self._load_page()))
            except Exception as e:
                GLib.idle_add(lambda: self._window.toast_error(f'Save failed: {e}'))

        threading.Thread(target=run, daemon=True).start()

    def _on_delete_row(self, *_):
        row = self._selected_row()
        if not row:
            return
        if not self._pk_cols:
            self._window.toast_error('Cannot delete: no primary key defined')
            return

        dialog = Adw.AlertDialog(
            heading='Delete row?',
            body='This row will be permanently deleted.',
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('delete', 'Delete')
        dialog.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')

        def on_response(d, response):
            if response == 'delete':
                self._execute_delete(row)

        dialog.connect('response', on_response)
        dialog.present(self._window)

    def _execute_delete(self, row: _DataRow):
        def run():
            try:
                schema = self._schema
                qualified = f'"{schema}"."{self._table}"' if schema else f'"{self._table}"'
                from sqlalchemy import text
                engine = self._db._engine
                where_clause = ' AND '.join(f'"{k}" = :pk_{k}' for k in self._pk_cols)
                params = {}
                for k in self._pk_cols:
                    idx = next(i for i, c in enumerate(self._col_info) if c['name'] == k)
                    params[f'pk_{k}'] = row.raw(idx)
                sql = f'DELETE FROM {qualified} WHERE {where_clause}'
                with engine.connect() as conn:
                    conn.execute(text(sql), params)
                    conn.commit()
                GLib.idle_add(lambda: (self._window.toast('Row deleted'), self._load_page()))
            except Exception as e:
                GLib.idle_add(lambda: self._window.toast_error(f'Delete failed: {e}'))

        threading.Thread(target=run, daemon=True).start()

    # ── Filter ─────────────────────────────────────────────────────────────

    def _on_filter_toggled(self, btn):
        self._filter_revealer.set_reveal_child(btn.get_active())
        if btn.get_active():
            self._filter_entry.grab_focus()

    def _on_filter_activate(self, *_):
        self._filter_sql = self._filter_entry.get_text().strip()
        self._offset = 0
        self._load_page()

    def _on_filter_clear(self, *_):
        self._filter_entry.set_text('')
        self._filter_sql = ''
        self._offset = 0
        self._load_page()

    # ── Sort ───────────────────────────────────────────────────────────────

    def _on_col_sort(self, col_name: str, vcol: Gtk.ColumnViewColumn):
        order = vcol.get_sort_order()
        if order == Gtk.SortType.ASCENDING:
            self._sort_col = col_name
            self._sort_asc = True
        elif order == Gtk.SortType.DESCENDING:
            self._sort_col = col_name
            self._sort_asc = False
        else:
            self._sort_col = None
        self._offset = 0
        self._load_page()

    # ── Pagination ─────────────────────────────────────────────────────────

    def _on_prev(self, *_):
        self._offset = max(0, self._offset - PAGE_SIZE)
        self._load_page()

    def _on_next(self, *_):
        if self._offset + PAGE_SIZE < self._total:
            self._offset += PAGE_SIZE
            self._load_page()

    # ── CSV import ─────────────────────────────────────────────────────────

    def _on_import_csv(self, *_):
        from .import_dialog import open_import_csv_dialog
        open_import_csv_dialog(
            window=self._window,
            config=self._config,
            db=self._db,
            table=self._table,
            schema=self._schema,
            on_done=self._load_page,
        )

    # ── Open in editor ─────────────────────────────────────────────────────

    def _open_in_editor(self, *_):
        qualified = f'"{self._schema}"."{self._table}"' if self._schema else f'"{self._table}"'
        self._window.open_query_editor(self._config, self._schema)
        def inject():
            from .editor_panel import EditorPanel
            page = self._window._tab_view.get_selected_page()
            if page:
                child = page.get_child()
                if isinstance(child, EditorPanel):
                    child._source_buffer.set_text(
                        f'SELECT *\nFROM {qualified}\nLIMIT 500;'
                    )
            return False
        GLib.idle_add(inject)
