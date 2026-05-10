"""Application-wide settings — persisted to ~/.config/reliquary/settings.json."""

import json
from pathlib import Path
from typing import Any

from gi.repository import GObject, Adw, Gtk

from .database.manager import CONFIG_DIR

SETTINGS_FILE = CONFIG_DIR / 'settings.json'

DEFAULTS: dict[str, Any] = {
    # Editor
    'editor.font_size':             11,
    'editor.tab_width':             4,
    'editor.show_line_numbers':     True,
    'editor.highlight_current_line': True,
    'editor.word_wrap':             False,
    'editor.auto_indent':           True,
    # Query
    'query.auto_limit':             True,
    'query.auto_limit_rows':        1000,
    'query.confirm_destructive':    True,
    'query.save_history':           True,
    'query.max_history':            200,
    # Appearance
    'appearance.color_scheme':      'system',   # 'system' | 'light' | 'dark'
    'appearance.show_row_numbers':  True,
}


class SettingsManager(GObject.Object):
    __gtype_name__ = 'ReliquarySettingsManager'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    _instance: 'SettingsManager | None' = None

    @classmethod
    def get_default(cls) -> 'SettingsManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._load()

    def _load(self):
        if not SETTINGS_FILE.exists():
            return
        try:
            saved = json.loads(SETTINGS_FILE.read_text())
            for k, v in saved.items():
                if k in DEFAULTS:
                    self._data[k] = v
        except Exception:
            pass

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self._data, indent=2))

    def get(self, key: str) -> Any:
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value: Any):
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self.save()
        self.emit('changed', key)

    # Typed convenience helpers
    def get_bool(self, key: str) -> bool:
        return bool(self.get(key))

    def get_int(self, key: str) -> int:
        return int(self.get(key))

    def get_str(self, key: str) -> str:
        return str(self.get(key))


# ── Preferences window ────────────────────────────────────────────────────

class PreferencesWindow(Adw.PreferencesDialog):
    def __init__(self, parent: Gtk.Widget):
        super().__init__()
        self._s = SettingsManager.get_default()
        self._build_ui()
        self.present(parent)

    def _build_ui(self):
        self.add(self._editor_page())
        self.add(self._query_page())
        self.add(self._appearance_page())

    # ── Editor page ───────────────────────────────────────────────────────

    def _editor_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Editor', icon_name='accessories-text-editor-symbolic')

        # Font group
        font_group = Adw.PreferencesGroup(title='Font and Layout')
        page.add(font_group)

        font_size_row = Adw.SpinRow.new_with_range(8, 24, 1)
        font_size_row.set_title('Font Size')
        font_size_row.set_subtitle('Editor font size in points')
        font_size_row.set_value(self._s.get_int('editor.font_size'))
        font_size_row.connect('notify::value', lambda r, _:
            self._s.set('editor.font_size', int(r.get_value())))
        font_group.add(font_size_row)

        tab_width_model = Gtk.StringList()
        for w in ('2', '4', '8'):
            tab_width_model.append(w)
        tab_row = Adw.ComboRow(title='Tab Width', subtitle='Spaces per indent level')
        tab_row.set_model(tab_width_model)
        current_tab = {2: 0, 4: 1, 8: 2}.get(self._s.get_int('editor.tab_width'), 1)
        tab_row.set_selected(current_tab)
        tab_row.connect('notify::selected', lambda r, _:
            self._s.set('editor.tab_width', [2, 4, 8][r.get_selected()]))
        font_group.add(tab_row)

        # Features group
        features_group = Adw.PreferencesGroup(title='Features')
        page.add(features_group)

        features_group.add(self._switch_row(
            'Show Line Numbers', 'Display line numbers in the gutter',
            'editor.show_line_numbers',
        ))
        features_group.add(self._switch_row(
            'Highlight Current Line', 'Highlight the line the cursor is on',
            'editor.highlight_current_line',
        ))
        features_group.add(self._switch_row(
            'Word Wrap', 'Wrap long lines in the editor',
            'editor.word_wrap',
        ))
        features_group.add(self._switch_row(
            'Auto Indent', 'Automatically indent new lines',
            'editor.auto_indent',
        ))

        return page

    # ── Query page ────────────────────────────────────────────────────────

    def _query_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Queries', icon_name='media-playback-start-symbolic')

        limits_group = Adw.PreferencesGroup(
            title='Result Limits',
            description='Prevent accidentally fetching millions of rows.',
        )
        page.add(limits_group)

        limits_group.add(self._switch_row(
            'Auto-Limit SELECT Results',
            'Append LIMIT automatically when no LIMIT clause is present',
            'query.auto_limit',
        ))

        limit_model = Gtk.StringList()
        limit_options = [100, 500, 1000, 5000, 10000]
        for n in limit_options:
            limit_model.append(f'{n:,} rows')
        limit_row = Adw.ComboRow(title='Default Limit', subtitle='Rows fetched per query')
        limit_row.set_model(limit_model)
        current_limit = self._s.get_int('query.auto_limit_rows')
        limit_row.set_selected(limit_options.index(current_limit) if current_limit in limit_options else 2)
        limit_row.connect('notify::selected', lambda r, _:
            self._s.set('query.auto_limit_rows', limit_options[r.get_selected()]))
        limits_group.add(limit_row)

        safety_group = Adw.PreferencesGroup(
            title='Safety',
            description='Protect against accidental data modification.',
        )
        page.add(safety_group)

        safety_group.add(self._switch_row(
            'Warn on Destructive Queries',
            'Confirm before running UPDATE or DELETE without a WHERE clause',
            'query.confirm_destructive',
        ))

        history_group = Adw.PreferencesGroup(title='History')
        page.add(history_group)

        history_group.add(self._switch_row(
            'Save Query History', 'Record executed queries per connection',
            'query.save_history',
        ))

        max_history_row = Adw.SpinRow.new_with_range(50, 1000, 50)
        max_history_row.set_title('Max History Entries')
        max_history_row.set_subtitle('Per connection')
        max_history_row.set_value(self._s.get_int('query.max_history'))
        max_history_row.connect('notify::value', lambda r, _:
            self._s.set('query.max_history', int(r.get_value())))
        history_group.add(max_history_row)

        return page

    # ── Appearance page ───────────────────────────────────────────────────

    def _appearance_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Appearance', icon_name='preferences-desktop-appearance-symbolic')

        theme_group = Adw.PreferencesGroup(title='Color Scheme')
        page.add(theme_group)

        scheme_model = Gtk.StringList()
        for label in ('Follow System', 'Light', 'Dark'):
            scheme_model.append(label)
        scheme_row = Adw.ComboRow(title='Color Scheme')
        scheme_row.set_model(scheme_model)
        scheme_map = {'system': 0, 'light': 1, 'dark': 2}
        scheme_row.set_selected(scheme_map.get(self._s.get_str('appearance.color_scheme'), 0))

        def on_scheme_changed(row, _):
            value = ['system', 'light', 'dark'][row.get_selected()]
            self._s.set('appearance.color_scheme', value)
            _apply_color_scheme(value)

        scheme_row.connect('notify::selected', on_scheme_changed)
        theme_group.add(scheme_row)

        results_group = Adw.PreferencesGroup(title='Results Grid')
        page.add(results_group)

        results_group.add(self._switch_row(
            'Show Row Numbers', 'Display a row number column in query results',
            'appearance.show_row_numbers',
        ))

        return page

    # ── Helper ────────────────────────────────────────────────────────────

    def _switch_row(self, title: str, subtitle: str, key: str) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.set_active(self._s.get_bool(key))
        row.connect('notify::active', lambda r, _: self._s.set(key, r.get_active()))
        return row


def _apply_color_scheme(scheme: str):
    style_manager = Adw.StyleManager.get_default()
    mapping = {
        'system': Adw.ColorScheme.DEFAULT,
        'light':  Adw.ColorScheme.FORCE_LIGHT,
        'dark':   Adw.ColorScheme.FORCE_DARK,
    }
    style_manager.set_color_scheme(mapping.get(scheme, Adw.ColorScheme.DEFAULT))


def apply_saved_color_scheme():
    """Call at startup to restore the saved color scheme."""
    _apply_color_scheme(SettingsManager.get_default().get_str('appearance.color_scheme'))
