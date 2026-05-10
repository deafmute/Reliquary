"""Export query results to CSV, JSON or TSV."""

import csv
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib

if TYPE_CHECKING:
    pass

FORMATS = {
    'csv':  ('CSV',  '.csv',  'text/csv'),
    'tsv':  ('TSV',  '.tsv',  'text/tab-separated-values'),
    'json': ('JSON', '.json', 'application/json'),
}


def export_results(
    parent: Gtk.Widget,
    columns: list[str],
    rows: list[tuple],
    suggested_name: str = 'results',
):
    """Open a file-save dialog and write the results in the chosen format."""
    dialog = Gtk.FileDialog(title='Export Results')
    dialog.set_initial_name(f'{suggested_name}.csv')

    filters = Gio_ListStore_for_filters()
    dialog.set_filters(filters)

    def on_response(d, result):
        try:
            file = d.save_finish(result)
        except Exception:
            return
        if not file:
            return

        path = Path(file.get_path())
        ext = path.suffix.lower().lstrip('.')
        fmt = ext if ext in FORMATS else 'csv'

        try:
            content = _serialize(columns, rows, fmt)
            path.write_text(content, encoding='utf-8')

            toast = Adw.Toast(title=f'Exported {len(rows):,} rows to {path.name}', timeout=4)
            root = parent.get_root()
            if hasattr(root, '_toast_overlay'):
                root._toast_overlay.add_toast(toast)
        except Exception as e:
            root = parent.get_root()
            if hasattr(root, 'toast_error'):
                root.toast_error(f'Export failed: {e}')

    from gi.repository import Gio
    dialog.save(parent.get_root(), None, on_response)


def _serialize(columns: list[str], rows: list[tuple], fmt: str) -> str:
    if fmt == 'json':
        data = [
            {col: (row[i] if row[i] is not None else None) for i, col in enumerate(columns)}
            for row in rows
        ]
        return json.dumps(data, indent=2, default=str)

    delim = '\t' if fmt == 'tsv' else ','
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delim, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(['' if v is None else str(v) for v in row])
    return buf.getvalue()


def Gio_ListStore_for_filters():
    from gi.repository import Gio
    store = Gio.ListStore(item_type=Gtk.FileFilter)

    f_all = Gtk.FileFilter()
    f_all.set_name('All supported formats')
    f_all.add_mime_type('text/csv')
    f_all.add_mime_type('text/tab-separated-values')
    f_all.add_mime_type('application/json')
    store.append(f_all)

    f_csv = Gtk.FileFilter()
    f_csv.set_name('CSV — Comma Separated Values (*.csv)')
    f_csv.add_pattern('*.csv')
    store.append(f_csv)

    f_tsv = Gtk.FileFilter()
    f_tsv.set_name('TSV — Tab Separated Values (*.tsv)')
    f_tsv.add_pattern('*.tsv')
    store.append(f_tsv)

    f_json = Gtk.FileFilter()
    f_json.set_name('JSON (*.json)')
    f_json.add_pattern('*.json')
    store.append(f_json)

    return store
