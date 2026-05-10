"""Saved query snippets — storage and panel widget."""
import json
import os
import time
import threading
from typing import Callable, Optional

from gi.repository import Gtk, Adw, GLib, GObject, Gio, Pango

_SNIPPETS_DIR = os.path.join(
    os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')),
    'reliquary',
)
_SNIPPETS_FILE = os.path.join(_SNIPPETS_DIR, 'snippets.json')


# ── Storage ───────────────────────────────────────────────────────────────

class SnippetStore:
    _instance: Optional['SnippetStore'] = None

    @classmethod
    def get_default(cls) -> 'SnippetStore':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._snippets: list[dict] = []
        self._load()

    def _load(self):
        try:
            with open(_SNIPPETS_FILE) as f:
                self._snippets = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._snippets = []

    def _save(self):
        os.makedirs(_SNIPPETS_DIR, exist_ok=True)
        with open(_SNIPPETS_FILE, 'w') as f:
            json.dump(self._snippets, f, indent=2)

    def get_all(self) -> list[dict]:
        return list(self._snippets)

    def add(self, name: str, sql: str) -> dict:
        snippet = {
            'id': str(int(time.time() * 1000)),
            'name': name,
            'sql': sql,
            'created': int(time.time()),
        }
        self._snippets.insert(0, snippet)
        self._save()
        return snippet

    def remove(self, snippet_id: str):
        self._snippets = [s for s in self._snippets if s['id'] != snippet_id]
        self._save()

    def update_name(self, snippet_id: str, name: str):
        for s in self._snippets:
            if s['id'] == snippet_id:
                s['name'] = name
                break
        self._save()


# ── Panel widget ──────────────────────────────────────────────────────────

class SnippetsPanel(Gtk.Box):
    def __init__(self, on_pick: Callable[[str], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_pick = on_pick
        self._store = SnippetStore.get_default()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            margin_start=8, margin_end=4,
            margin_top=6, margin_bottom=6,
        )
        lbl = Gtk.Label(label='Snippets', xalign=0, hexpand=True)
        lbl.add_css_class('heading')
        header.append(lbl)
        self.append(header)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Search
        self._search = Gtk.SearchEntry(
            placeholder_text='Filter snippets…',
            margin_start=8, margin_end=8,
            margin_top=6, margin_bottom=6,
        )
        self._search.connect('search-changed', lambda *_: self.refresh())
        self.append(self._search)

        scroll = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        self.append(scroll)

        self._list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list_box.add_css_class('boxed-list')
        self._list_box.set_margin_start(8)
        self._list_box.set_margin_end(8)
        self._list_box.set_margin_top(6)
        self._list_box.set_margin_bottom(6)
        scroll.set_child(self._list_box)

        self._empty = Gtk.Label(
            label='No saved snippets',
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            vexpand=True,
        )
        self._empty.add_css_class('dim-label')
        self.append(self._empty)

    def refresh(self):
        query = self._search.get_text().lower() if hasattr(self, '_search') else ''
        snippets = [
            s for s in self._store.get_all()
            if not query or query in s['name'].lower() or query in s['sql'].lower()
        ]

        while self._list_box.get_first_child():
            self._list_box.remove(self._list_box.get_first_child())

        self._empty.set_visible(not snippets)
        self._list_box.set_visible(bool(snippets))

        for snippet in snippets:
            row = self._make_row(snippet)
            self._list_box.append(row)

    def _make_row(self, snippet: dict) -> Gtk.Widget:
        row = Adw.ActionRow(
            title=snippet['name'],
            subtitle=snippet['sql'][:80].replace('\n', ' '),
            activatable=True,
        )
        row.add_prefix(Gtk.Image(icon_name='accessories-text-editor-symbolic', pixel_size=16))

        delete_btn = Gtk.Button(icon_name='edit-delete-symbolic', valign=Gtk.Align.CENTER)
        delete_btn.add_css_class('flat')
        delete_btn.add_css_class('destructive-action')
        delete_btn.set_tooltip_text('Delete snippet')
        sid = snippet['id']
        delete_btn.connect('clicked', lambda *_, s=sid: self._on_delete(s))
        row.add_suffix(delete_btn)

        sql = snippet['sql']
        row.connect('activated', lambda *_, q=sql: self._on_pick(q))
        return row

    def _on_delete(self, snippet_id: str):
        self._store.remove(snippet_id)
        self.refresh()


# ── Save snippet dialog ───────────────────────────────────────────────────

def show_save_snippet_dialog(parent: Gtk.Widget, sql: str, on_saved):
    dialog = Adw.Dialog(title='Save Snippet')
    dialog.set_content_width(360)
    dialog.set_content_height(180)

    toolbar_view = Adw.ToolbarView()
    dialog.set_child(toolbar_view)

    header = Adw.HeaderBar()
    header.add_css_class('flat')
    toolbar_view.add_top_bar(header)

    cancel_btn = Gtk.Button(label='Cancel')
    cancel_btn.connect('clicked', lambda *_: dialog.close())
    header.pack_start(cancel_btn)

    save_btn = Gtk.Button(label='Save')
    save_btn.add_css_class('suggested-action')
    header.pack_end(save_btn)

    clamp = Adw.Clamp(maximum_size=320, margin_top=16, margin_bottom=16,
                      margin_start=12, margin_end=12)
    toolbar_view.set_content(clamp)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    clamp.set_child(box)

    group = Adw.PreferencesGroup()
    box.append(group)

    name_row = Adw.EntryRow(title='Snippet name')
    group.add(name_row)

    def on_save(*_):
        name = name_row.get_text().strip()
        if not name:
            return
        snippet = SnippetStore.get_default().add(name, sql)
        on_saved(snippet)
        dialog.close()

    save_btn.connect('clicked', on_save)
    name_row.connect('entry-activated', on_save)
    dialog.present(parent)
