"""Dialog for inserting or updating a single table row."""
from typing import Optional, Callable, TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib

if TYPE_CHECKING:
    from .table_panel import _DataRow


class RowEditDialog(Adw.Dialog):
    def __init__(
        self,
        parent: Gtk.Widget,
        col_info: list[dict],
        pk_cols: list[str],
        existing_row: Optional['_DataRow'],
        on_save: Callable,
    ):
        is_edit = existing_row is not None
        super().__init__(title='Edit Row' if is_edit else 'Add Row')
        self._col_info = col_info
        self._pk_cols = pk_cols
        self._existing = existing_row
        self._on_save = on_save
        self._is_edit = is_edit
        self._entries: dict[str, Gtk.Entry] = {}

        self.set_content_width(480)
        self.set_content_height(min(80 + len(col_info) * 64, 620))

        self._build_ui()

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.add_css_class('flat')
        toolbar_view.add_top_bar(header)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda *_: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label='Update' if self._is_edit else 'Insert')
        save_btn.add_css_class('suggested-action')
        save_btn.connect('clicked', self._on_save_clicked)
        header.pack_end(save_btn)

        scroll = Gtk.ScrolledWindow(
            vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        toolbar_view.set_content(scroll)

        clamp = Adw.Clamp(maximum_size=420, margin_top=12, margin_bottom=12)
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(box)

        group = Adw.PreferencesGroup()
        box.append(group)

        for i, col in enumerate(self._col_info):
            name = col['name']
            col_type = str(col.get('type', ''))
            nullable = col.get('nullable', True)
            is_pk = name in self._pk_cols

            subtitle_parts = [col_type]
            if is_pk:
                subtitle_parts.append('PRIMARY KEY')
            if not nullable:
                subtitle_parts.append('NOT NULL')

            entry = Gtk.Entry(hexpand=True)
            entry.add_css_class('monospace')

            if self._existing is not None:
                val = self._existing.raw(i)
                entry.set_text('' if val is None else str(val))
            elif col.get('default') is not None:
                entry.set_text(str(col['default']))

            # PK columns are read-only when editing
            if self._is_edit and is_pk:
                entry.set_editable(False)
                entry.add_css_class('dim-label')

            row = Adw.ActionRow(
                title=name,
                subtitle=' · '.join(subtitle_parts),
            )
            row.add_suffix(entry)
            row.set_activatable_widget(entry)
            group.add(row)
            self._entries[name] = entry

        self._status = Gtk.Label(label='', xalign=0, margin_start=12)
        self._status.add_css_class('error')
        box.append(self._status)

    def _on_save_clicked(self, *_):
        values = {}
        for name, entry in self._entries.items():
            text = entry.get_text()
            values[name] = text if text else None

        # Basic validation: NOT NULL columns can't be empty (unless PK auto-gen)
        errors = []
        for col in self._col_info:
            name = col['name']
            nullable = col.get('nullable', True)
            is_pk = name in self._pk_cols
            if not nullable and not is_pk and not values.get(name):
                errors.append(name)

        if errors:
            self._status.set_label(f'Required: {", ".join(errors)}')
            return

        self._on_save(self._col_info, self._pk_cols, self._existing, values)
        self.close()
