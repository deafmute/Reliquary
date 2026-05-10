"""Query history — per-connection storage and sidebar panel."""

import json
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from gi.repository import Gtk, Adw, GObject, Gio, GLib, Pango

from .database.manager import CONFIG_DIR

HISTORY_DIR = CONFIG_DIR / 'history'

if TYPE_CHECKING:
    pass


# ── Storage ───────────────────────────────────────────────────────────────

class HistoryEntry:
    __slots__ = ('sql', 'timestamp', 'duration_ms', 'row_count', 'error')

    def __init__(self, sql: str, timestamp: float, duration_ms: int,
                 row_count: int, error: str = ''):
        self.sql = sql
        self.timestamp = timestamp
        self.duration_ms = duration_ms
        self.row_count = row_count
        self.error = error

    def to_dict(self) -> dict:
        return {
            'sql': self.sql,
            'timestamp': self.timestamp,
            'duration_ms': self.duration_ms,
            'row_count': self.row_count,
            'error': self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'HistoryEntry':
        return cls(
            sql=d.get('sql', ''),
            timestamp=d.get('timestamp', 0.0),
            duration_ms=d.get('duration_ms', 0),
            row_count=d.get('row_count', 0),
            error=d.get('error', ''),
        )


class QueryHistory:
    def __init__(self, connection_id: str, max_entries: int = 200):
        self._id = connection_id
        self._max = max_entries
        self._path = HISTORY_DIR / f'{connection_id}.json'
        self._entries: list[HistoryEntry] = []
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._entries = [HistoryEntry.from_dict(e) for e in data]
        except Exception:
            self._entries = []

    def save(self):
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([e.to_dict() for e in self._entries], indent=2)
        )

    def add(self, sql: str, duration_ms: int, row_count: int, error: str = ''):
        sql = sql.strip()
        if not sql:
            return
        # Deduplicate: remove same SQL from history (move to top)
        self._entries = [e for e in self._entries if e.sql != sql]
        entry = HistoryEntry(
            sql=sql,
            timestamp=time.time(),
            duration_ms=duration_ms,
            row_count=row_count,
            error=error,
        )
        self._entries.insert(0, entry)
        if len(self._entries) > self._max:
            self._entries = self._entries[:self._max]
        self.save()

    def get_all(self) -> list[HistoryEntry]:
        return list(self._entries)

    def clear(self):
        self._entries = []
        if self._path.exists():
            self._path.unlink()

    @classmethod
    def clear_for_connection(cls, connection_id: str):
        path = HISTORY_DIR / f'{connection_id}.json'
        if path.exists():
            path.unlink()


# ── GObject list item ─────────────────────────────────────────────────────

class HistoryItem(GObject.Object):
    __gtype_name__ = 'ReliquaryHistoryItem'

    def __init__(self, entry: HistoryEntry):
        super().__init__()
        self.entry = entry


# ── History panel widget (shows as a side drawer inside editor) ───────────

class HistoryPanel(Gtk.Box):
    def __init__(self, history: QueryHistory, on_pick: callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._history = history
        self._on_pick = on_pick
        self._store = Gio.ListStore(item_type=HistoryItem)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        # Header
        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=8,
            margin_end=4,
            margin_top=6,
            margin_bottom=6,
        )
        title = Gtk.Label(label='Query History', xalign=0, hexpand=True)
        title.add_css_class('heading')
        header.append(title)

        clear_btn = Gtk.Button(icon_name='edit-clear-all-symbolic', tooltip_text='Clear history')
        clear_btn.add_css_class('flat')
        clear_btn.add_css_class('destructive-action')
        clear_btn.connect('clicked', self._on_clear)
        header.append(clear_btn)
        self.append(header)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(sep)

        # Search
        search = Gtk.SearchEntry(
            placeholder_text='Search history…',
            margin_start=8,
            margin_end=8,
            margin_top=6,
            margin_bottom=4,
        )
        search.connect('search-changed', self._on_search)
        self.append(search)

        # List
        self._filter_model = Gtk.FilterListModel(model=self._store)
        self._filter = Gtk.CustomFilter.new(None, None)
        self._filter_model.set_filter(self._filter)
        self._search_text = ''

        selection = Gtk.NoSelection(model=self._filter_model)

        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._setup_item)
        factory.connect('bind', self._bind_item)
        factory.connect('unbind', self._unbind_item)

        self._list_view = Gtk.ListView(model=selection, factory=factory)
        self._list_view.add_css_class('navigation-sidebar')
        self._list_view.connect('activate', self._on_activate)

        scroll = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        scroll.set_child(self._list_view)

        # Empty state
        self._stack = Gtk.Stack(vexpand=True)
        empty = Adw.StatusPage(
            title='No History',
            description='Executed queries will appear here',
            icon_name='document-open-recent-symbolic',
        )
        empty.add_css_class('compact')
        self._stack.add_named(empty, 'empty')
        self._stack.add_named(scroll, 'list')
        self.append(self._stack)

    def _setup_item(self, factory, list_item):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            margin_start=8,
            margin_end=8,
            margin_top=6,
            margin_bottom=6,
        )
        sql_label = Gtk.Label(
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=30,
        )
        sql_label.add_css_class('monospace')

        meta_label = Gtk.Label(xalign=0)
        meta_label.add_css_class('dim-label')
        meta_label.add_css_class('caption')

        box.append(sql_label)
        box.append(meta_label)
        list_item.set_child(box)

    def _bind_item(self, factory, list_item):
        item: HistoryItem = list_item.get_item()
        entry = item.entry
        box: Gtk.Box = list_item.get_child()
        children = list(box)
        sql_label: Gtk.Label = children[0]
        meta_label: Gtk.Label = children[1]

        # Show first line of SQL
        first_line = entry.sql.split('\n')[0].strip()
        sql_label.set_label(first_line)

        ts = time.strftime('%b %d  %H:%M', time.localtime(entry.timestamp))
        if entry.error:
            meta_label.set_label(f'{ts}  ✗ Error')
            sql_label.add_css_class('error')
        else:
            meta_label.set_label(f'{ts}  {entry.row_count:,} rows  {entry.duration_ms}ms')
            sql_label.remove_css_class('error')

    def _unbind_item(self, factory, list_item):
        pass

    def _on_activate(self, list_view, position):
        item: HistoryItem = self._filter_model.get_item(position)
        if item and self._on_pick:
            self._on_pick(item.entry.sql)

    def _on_search(self, entry):
        self._search_text = entry.get_text().lower()

        def filter_func(item: HistoryItem, _data):
            if not self._search_text:
                return True
            return self._search_text in item.entry.sql.lower()

        self._filter = Gtk.CustomFilter.new(filter_func, None)
        self._filter_model.set_filter(self._filter)

    def _on_clear(self, *_):
        self._history.clear()
        self.refresh()

    def refresh(self):
        self._store.remove_all()
        entries = self._history.get_all()
        for entry in entries:
            self._store.append(HistoryItem(entry))
        if entries:
            self._stack.set_visible_child_name('list')
        else:
            self._stack.set_visible_child_name('empty')
