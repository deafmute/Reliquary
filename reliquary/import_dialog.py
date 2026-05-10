"""CSV and SQL file import."""
import csv
import io
import os
import threading
from typing import Optional, TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib, Gio

if TYPE_CHECKING:
    from .window import ReliquaryWindow
    from .database.manager import ConnectionConfig
    from .database.connection import DatabaseConnection


def open_import_csv_dialog(
    window: 'ReliquaryWindow',
    config: 'ConnectionConfig',
    db: 'DatabaseConnection',
    table: str,
    schema: Optional[str],
    on_done,
):
    """Open a file chooser then show the CSV import dialog."""
    file_dialog = Gtk.FileDialog(title='Import CSV')
    filter_ = Gtk.FileFilter()
    filter_.set_name('CSV files')
    filter_.add_pattern('*.csv')
    filter_.add_pattern('*.tsv')
    filter_.add_pattern('*.txt')
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(filter_)
    file_dialog.set_filters(filters)

    def on_file(d, result):
        try:
            f = d.open_finish(result)
        except Exception:
            return
        if not f:
            return
        path = f.get_path()
        dlg = CsvImportDialog(window, config, db, table, schema, path, on_done)
        dlg.present(window)

    file_dialog.open(window, None, on_file)


class CsvImportDialog(Adw.Dialog):
    def __init__(
        self,
        window: 'ReliquaryWindow',
        config: 'ConnectionConfig',
        db: 'DatabaseConnection',
        table: str,
        schema: Optional[str],
        path: str,
        on_done,
    ):
        super().__init__(title='Import CSV')
        self._window = window
        self._db = db
        self._table = table
        self._schema = schema
        self._path = path
        self._on_done = on_done
        self._csv_headers: list[str] = []
        self._preview_rows: list[list[str]] = []
        self._col_map_rows: list[Adw.ComboRow] = []
        self._table_cols: list[str] = []

        self.set_content_width(520)
        self.set_content_height(580)
        self._build_ui()
        self._load_file()
        self._load_table_columns()

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.add_css_class('flat')
        toolbar_view.add_top_bar(header)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda *_: self.close())
        header.pack_start(cancel_btn)

        self._import_btn = Gtk.Button(label='Import')
        self._import_btn.add_css_class('suggested-action')
        self._import_btn.set_sensitive(False)
        self._import_btn.connect('clicked', self._on_import)
        header.pack_end(self._import_btn)

        scroll = Gtk.ScrolledWindow(
            vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        toolbar_view.set_content(scroll)
        clamp = Adw.Clamp(maximum_size=480, margin_top=12, margin_bottom=12)
        scroll.set_child(clamp)

        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(self._main_box)

        # File info
        file_group = Adw.PreferencesGroup(title='File')
        self._main_box.append(file_group)

        fname_row = Adw.ActionRow(
            title=os.path.basename(self._path),
            subtitle=self._path,
        )
        fname_row.add_prefix(Gtk.Image(icon_name='text-x-generic-symbolic', pixel_size=16))
        file_group.add(fname_row)

        # Options
        opts_group = Adw.PreferencesGroup(title='Options')
        self._main_box.append(opts_group)

        self._has_header_row = Adw.SwitchRow(
            title='First row is header',
            active=True,
        )
        self._has_header_row.connect('notify::active', lambda *_: self._load_file())
        opts_group.add(self._has_header_row)

        self._skip_errors_row = Adw.SwitchRow(
            title='Skip rows with errors',
            subtitle='Continue importing even if some rows fail',
            active=True,
        )
        opts_group.add(self._skip_errors_row)

        # Column mapping placeholder — filled after loading
        self._mapping_group = Adw.PreferencesGroup(title='Column mapping')
        self._main_box.append(self._mapping_group)

        self._status = Gtk.Label(label='Reading file…', xalign=0, margin_start=12)
        self._status.add_css_class('dim-label')
        self._main_box.append(self._status)

        self._progress = Gtk.ProgressBar(visible=False)
        self._main_box.append(self._progress)

    def _load_file(self):
        path = self._path
        has_header = self._has_header_row.get_active()

        try:
            with open(path, newline='', encoding='utf-8-sig') as f:
                # Sniff delimiter
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except csv.Error:
                    dialect = csv.excel
                reader = csv.reader(f, dialect)
                rows = [row for _, row in zip(range(11), reader)]

            if not rows:
                self._status.set_label('File is empty')
                return

            if has_header:
                self._csv_headers = rows[0]
                self._preview_rows = rows[1:6]
            else:
                self._csv_headers = [f'col{i+1}' for i in range(len(rows[0]))]
                self._preview_rows = rows[:5]

            self._rebuild_mapping()
        except Exception as e:
            self._status.set_label(f'Error reading file: {e}')

    def _load_table_columns(self):
        def run():
            try:
                from sqlalchemy import inspect as sa_inspect
                insp = sa_inspect(self._db._engine)
                cols = insp.get_columns(self._table, schema=self._schema)
                col_names = [c['name'] for c in cols]
                GLib.idle_add(lambda: self._on_table_cols_loaded(col_names))
            except Exception as e:
                GLib.idle_add(lambda: self._status.set_label(f'Error loading columns: {e}'))

        threading.Thread(target=run, daemon=True).start()

    def _on_table_cols_loaded(self, cols: list[str]):
        self._table_cols = cols
        self._rebuild_mapping()

    def _rebuild_mapping(self):
        if not self._csv_headers or not self._table_cols:
            return

        # Clear old mapping rows
        while True:
            child = self._mapping_group.get_first_child()
            if child is None:
                break
            self._mapping_group.remove(child)
        self._col_map_rows.clear()

        options = Gtk.StringList()
        options.append('(skip)')
        for c in self._table_cols:
            options.append(c)

        for csv_col in self._csv_headers:
            combo = Adw.ComboRow(title=csv_col, subtitle='CSV column')
            combo.set_model(options)
            # Auto-match by name (case-insensitive)
            try:
                idx = next(
                    i + 1 for i, tc in enumerate(self._table_cols)
                    if tc.lower() == csv_col.lower()
                )
            except StopIteration:
                idx = 0
            combo.set_selected(idx)
            self._mapping_group.add(combo)
            self._col_map_rows.append(combo)

        self._status.set_label(
            f'{len(self._csv_headers)} CSV columns · '
            f'{len(self._preview_rows)} preview rows'
        )
        self._import_btn.set_sensitive(True)

    def _get_mapping(self) -> dict[int, str]:
        """Returns {csv_col_index: table_col_name} for non-skipped columns."""
        mapping = {}
        for i, combo in enumerate(self._col_map_rows):
            sel = combo.get_selected()
            if sel > 0:
                mapping[i] = self._table_cols[sel - 1]
        return mapping

    def _on_import(self, *_):
        mapping = self._get_mapping()
        if not mapping:
            self._status.set_label('No columns mapped')
            return

        has_header = self._has_header_row.get_active()
        skip_errors = self._skip_errors_row.get_active()
        path = self._path
        schema = self._schema
        table = self._table
        db = self._db

        self._import_btn.set_sensitive(False)
        self._progress.set_visible(True)
        self._status.set_label('Importing…')

        def run():
            try:
                from sqlalchemy import text
                engine = db._engine
                qualified = f'"{schema}"."{table}"' if schema else f'"{table}"'

                with open(path, newline='', encoding='utf-8-sig') as f:
                    try:
                        dialect = csv.Sniffer().sniff(f.read(4096))
                        f.seek(0)
                    except csv.Error:
                        f.seek(0)
                        dialect = csv.excel
                    reader = csv.reader(f, dialect)
                    all_rows = list(reader)

                data_rows = all_rows[1:] if has_header else all_rows
                total = len(data_rows)
                inserted = 0
                errors = 0

                col_names = [mapping[i] for i in sorted(mapping)]
                cols_sql = ', '.join(f'"{c}"' for c in col_names)
                placeholders = ', '.join(f':col{i}' for i in range(len(col_names)))
                sql = text(f'INSERT INTO {qualified} ({cols_sql}) VALUES ({placeholders})')

                with engine.connect() as conn:
                    for idx, row in enumerate(data_rows):
                        params = {}
                        for ci, col_name in zip(sorted(mapping), col_names):
                            val = row[ci] if ci < len(row) else None
                            params[f'col{list(sorted(mapping)).index(ci)}'] = val or None
                        try:
                            conn.execute(sql, params)
                            inserted += 1
                        except Exception:
                            errors += 1
                            if not skip_errors:
                                raise
                        if idx % 100 == 0:
                            progress = idx / total
                            GLib.idle_add(lambda p=progress: self._progress.set_fraction(p))

                    conn.commit()

                msg = f'Imported {inserted:,} rows'
                if errors:
                    msg += f' ({errors} skipped)'
                GLib.idle_add(lambda: (
                    self._window.toast(msg),
                    self._on_done() if self._on_done else None,
                    self.close(),
                ))
            except Exception as e:
                GLib.idle_add(lambda: (
                    self._status.set_label(f'Error: {e}'),
                    self._import_btn.set_sensitive(True),
                    self._progress.set_visible(False),
                ))

        threading.Thread(target=run, daemon=True).start()
