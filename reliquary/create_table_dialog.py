"""Create table wizard — form-based DDL builder."""
import threading
from typing import Optional, Callable, TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib, Gio

if TYPE_CHECKING:
    from .window import ReliquaryWindow
    from .database.connection import DatabaseConnection

COLUMN_TYPES = [
    'INTEGER', 'BIGINT', 'SMALLINT',
    'TEXT', 'VARCHAR(255)', 'CHAR(1)',
    'REAL', 'DOUBLE PRECISION', 'NUMERIC(10,2)',
    'BOOLEAN',
    'DATE', 'TIMESTAMP', 'TIMESTAMP WITH TIME ZONE',
    'BLOB', 'BYTEA',
    'JSON', 'JSONB',
    'UUID',
]


class CreateTableDialog(Adw.Dialog):
    def __init__(
        self,
        window: 'ReliquaryWindow',
        db: 'DatabaseConnection',
        schema: Optional[str],
        on_created: Callable,
    ):
        super().__init__(title='Create Table')
        self._window = window
        self._db = db
        self._schema = schema
        self._on_created = on_created
        self._col_rows: list[dict] = []

        self.set_content_width(580)
        self.set_content_height(640)
        self._build_ui()
        self._add_column_row()  # start with one blank column

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.add_css_class('flat')
        toolbar_view.add_top_bar(header)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda *_: self.close())
        header.pack_start(cancel_btn)

        self._create_btn = Gtk.Button(label='Create')
        self._create_btn.add_css_class('suggested-action')
        self._create_btn.connect('clicked', self._on_create)
        header.pack_end(self._create_btn)

        scroll = Gtk.ScrolledWindow(
            vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        toolbar_view.set_content(scroll)

        clamp = Adw.Clamp(maximum_size=540, margin_top=12, margin_bottom=12)
        scroll.set_child(clamp)

        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(self._main_box)

        # Table name
        name_group = Adw.PreferencesGroup(title='Table')
        self._main_box.append(name_group)

        self._name_row = Adw.EntryRow(title='Table name')
        name_group.add(self._name_row)

        # Columns section
        cols_header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            margin_top=4, margin_bottom=4,
        )
        cols_lbl = Gtk.Label(label='Columns', xalign=0, hexpand=True)
        cols_lbl.add_css_class('heading')
        add_col_btn = Gtk.Button(
            icon_name='list-add-symbolic',
            tooltip_text='Add column',
        )
        add_col_btn.add_css_class('flat')
        add_col_btn.connect('clicked', lambda *_: self._add_column_row())
        cols_header.append(cols_lbl)
        cols_header.append(add_col_btn)
        self._main_box.append(cols_header)

        self._cols_group = Adw.PreferencesGroup()
        self._main_box.append(self._cols_group)

        # DDL preview
        preview_group = Adw.PreferencesGroup(title='Preview')
        self._main_box.append(preview_group)

        self._preview_view = Gtk.TextView(
            editable=False, monospace=True,
            wrap_mode=Gtk.WrapMode.WORD,
            left_margin=8, right_margin=8,
            top_margin=6, bottom_margin=6,
        )
        preview_scroll = Gtk.ScrolledWindow(min_content_height=100)
        preview_scroll.set_child(self._preview_view)
        preview_group.add(preview_scroll)

        self._status = Gtk.Label(label='', xalign=0, margin_start=12)
        self._status.add_css_class('error')
        self._main_box.append(self._status)

    def _add_column_row(self):
        row_data: dict = {}
        self._col_rows.append(row_data)

        expander_row = Adw.ExpanderRow(title=f'column{len(self._col_rows)}')
        row_data['expander'] = expander_row

        # Name
        name_entry = Adw.EntryRow(title='Name')
        name_entry.connect('notify::text', lambda *_: self._refresh_preview())
        expander_row.add_row(name_entry)
        row_data['name'] = name_entry

        # Type (combo)
        type_row = Adw.ComboRow(title='Type')
        type_model = Gtk.StringList()
        for t in COLUMN_TYPES:
            type_model.append(t)
        type_row.set_model(type_model)
        type_row.connect('notify::selected', lambda *_: self._refresh_preview())
        expander_row.add_row(type_row)
        row_data['type'] = type_row

        # Primary key
        pk_row = Adw.SwitchRow(title='Primary key')
        pk_row.connect('notify::active', lambda *_: self._refresh_preview())
        expander_row.add_row(pk_row)
        row_data['pk'] = pk_row

        # NOT NULL
        nn_row = Adw.SwitchRow(title='Not null')
        nn_row.connect('notify::active', lambda *_: self._refresh_preview())
        expander_row.add_row(nn_row)
        row_data['not_null'] = nn_row

        # Default
        default_row = Adw.EntryRow(title='Default value')
        default_row.connect('notify::text', lambda *_: self._refresh_preview())
        expander_row.add_row(default_row)
        row_data['default'] = default_row

        # Remove button
        remove_btn = Gtk.Button(
            icon_name='edit-delete-symbolic',
            valign=Gtk.Align.CENTER,
            tooltip_text='Remove column',
        )
        remove_btn.add_css_class('flat')
        remove_btn.add_css_class('destructive-action')
        remove_btn.connect('clicked', lambda *_, rd=row_data: self._remove_col_row(rd))
        expander_row.add_action(remove_btn)

        self._cols_group.add(expander_row)
        expander_row.set_expanded(True)
        self._refresh_preview()

    def _remove_col_row(self, row_data: dict):
        if row_data in self._col_rows:
            self._col_rows.remove(row_data)
        self._cols_group.remove(row_data['expander'])
        self._refresh_preview()

    def _build_ddl(self) -> tuple[bool, str]:
        table_name = self._name_row.get_text().strip()
        if not table_name:
            return False, '-- Table name required'

        schema = self._schema
        qualified = f'"{schema}"."{table_name}"' if schema else f'"{table_name}"'

        col_defs = []
        pk_cols = []
        for rd in self._col_rows:
            name = rd['name'].get_text().strip()
            if not name:
                continue
            type_idx = rd['type'].get_selected()
            col_type = COLUMN_TYPES[type_idx]
            is_pk = rd['pk'].get_active()
            not_null = rd['not_null'].get_active()
            default = rd['default'].get_text().strip()

            parts = [f'  "{name}"', col_type]
            if is_pk:
                pk_cols.append(name)
            if not_null and not is_pk:
                parts.append('NOT NULL')
            if default:
                parts.append(f'DEFAULT {default}')
            col_defs.append(' '.join(parts))

        if not col_defs:
            return False, '-- Add at least one column'

        if pk_cols:
            pk_def = ', '.join(f'"{c}"' for c in pk_cols)
            col_defs.append(f'  PRIMARY KEY ({pk_def})')

        ddl = f'CREATE TABLE {qualified} (\n' + ',\n'.join(col_defs) + '\n);'
        return True, ddl

    def _refresh_preview(self):
        _, ddl = self._build_ddl()
        try:
            import sqlparse
            ddl = sqlparse.format(ddl, reindent=True, keyword_case='upper')
        except ImportError:
            pass
        self._preview_view.get_buffer().set_text(ddl)

    def _on_create(self, *_):
        ok, ddl = self._build_ddl()
        if not ok:
            self._status.set_label('Fix errors before creating')
            return

        self._create_btn.set_sensitive(False)
        self._status.set_label('Creating…')

        def run():
            try:
                from sqlalchemy import text
                with self._db._engine.connect() as conn:
                    conn.execute(text(ddl))
                    conn.commit()
                table_name = self._name_row.get_text().strip()
                GLib.idle_add(lambda: (
                    self._window.toast(f'Table "{table_name}" created'),
                    self._on_created(),
                    self.close(),
                ))
            except Exception as e:
                GLib.idle_add(lambda: (
                    self._status.set_label(f'Error: {e}'),
                    self._create_btn.set_sensitive(True),
                ))

        threading.Thread(target=run, daemon=True).start()
