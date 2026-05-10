import os
import re
import time
from typing import Optional, TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib, GObject, Pango, GtkSource

if TYPE_CHECKING:
    from .window import ReliquaryWindow
    from .database.manager import ConnectionConfig
    from .database.connection import DatabaseConnection

def _split_statements(sql: str) -> list[str]:
    """Split SQL into individual statements, respecting string literals."""
    try:
        import sqlparse
        stmts = [s.strip() for s in sqlparse.split(sql) if s.strip()]
    except ImportError:
        stmts = [s.strip() for s in sql.split(';') if s.strip()]
    return stmts


_DESTRUCTIVE_RE = re.compile(
    r'^\s*(DELETE|UPDATE|DROP|TRUNCATE)\b',
    re.IGNORECASE | re.MULTILINE,
)
_WHERE_RE = re.compile(r'\bWHERE\b', re.IGNORECASE)
_SELECT_RE = re.compile(r'^\s*SELECT\b', re.IGNORECASE)
_LIMIT_RE  = re.compile(r'\bLIMIT\b', re.IGNORECASE)


class EditorPanel(Gtk.Box):
    def __init__(
        self,
        window: 'ReliquaryWindow',
        config: 'ConnectionConfig',
        db: 'DatabaseConnection',
        schema: Optional[str] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._config = config
        self._db = db
        self._schema = schema
        self._running = False
        self._start_time: float = 0
        self._last_columns: list[str] = []
        self._last_rows: list[tuple] = []
        self._history = None

        from .settings import SettingsManager
        self._settings = SettingsManager.get_default()
        self._settings.connect('changed', self._on_settings_changed)

        self._build_ui()
        self._init_history()
        self._init_snippets()
        self._init_autocomplete()
        self.restore_editor_content()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        # Build header widget first (run btn + status live here, not in panel toolbar)
        self._header_widget = self._build_header_widget()

        # Wrap everything in Adw.ToolbarView for proper Adwaita toolbar styling
        toolbar_view = Adw.ToolbarView()
        self.append(toolbar_view)

        # ── Top toolbar ───────────────────────────────────────────────────
        toolbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            margin_start=8,
            margin_end=8,
            margin_top=4,
            margin_bottom=4,
        )

        # Schema breadcrumb (connection name is in the window header)
        if self._schema:
            schema_label = Gtk.Label(label=self._schema)
            schema_label.add_css_class('caption-heading')
            schema_label.add_css_class('dim-label')
            toolbar.append(schema_label)

        spacer = Gtk.Box(hexpand=True)
        toolbar.append(spacer)

        # Secondary action group (linked visually)
        secondary = Gtk.Box(spacing=0)
        secondary.add_css_class('linked')

        self._find_btn = Gtk.ToggleButton(
            icon_name='edit-find-symbolic',
            tooltip_text='Find and Replace (Ctrl+F)',
        )
        self._find_btn.add_css_class('flat')
        secondary.append(self._find_btn)

        open_btn = Gtk.Button(
            icon_name='document-open-symbolic',
            tooltip_text='Open SQL file (Ctrl+O)',
        )
        open_btn.add_css_class('flat')
        open_btn.connect('clicked', self._on_open_file)
        secondary.append(open_btn)

        fmt_btn = Gtk.Button(
            icon_name='format-indent-more-symbolic',
            tooltip_text='Format SQL',
        )
        fmt_btn.add_css_class('flat')
        fmt_btn.connect('clicked', self._on_format_sql)
        secondary.append(fmt_btn)

        explain_btn = Gtk.Button(
            icon_name='utilities-system-monitor-symbolic',
            tooltip_text='Explain query',
        )
        explain_btn.add_css_class('flat')
        explain_btn.connect('clicked', self._on_explain)
        secondary.append(explain_btn)

        toolbar.append(secondary)

        # Snippet / history toggles
        side_group = Gtk.Box(spacing=0, margin_start=4)

        snippet_save_btn = Gtk.Button(
            icon_name='bookmark-new-symbolic',
            tooltip_text='Save as snippet',
        )
        snippet_save_btn.add_css_class('flat')
        snippet_save_btn.connect('clicked', self._on_save_snippet)
        side_group.append(snippet_save_btn)

        self._snippets_btn = Gtk.ToggleButton(
            icon_name='user-bookmarks-symbolic',
            tooltip_text='Snippets',
        )
        self._snippets_btn.add_css_class('flat')
        self._snippets_btn.connect('toggled', self._on_snippets_toggled)
        side_group.append(self._snippets_btn)

        self._history_btn = Gtk.ToggleButton(
            icon_name='document-open-recent-symbolic',
            tooltip_text='Query history',
        )
        self._history_btn.add_css_class('flat')
        self._history_btn.connect('toggled', self._on_history_toggled)
        side_group.append(self._history_btn)

        toolbar.append(side_group)

        toolbar_view.add_top_bar(toolbar)

        # ── Content: find bar + paned ─────────────────────────────────────
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)

        # ── Find & Replace bar ────────────────────────────────────────────
        self._find_bar = self._build_find_bar()
        content_box.append(self._find_bar)

        # ── Main area: editor + history drawer ────────────────────────────
        self._main_paned = Gtk.Paned(
            orientation=Gtk.Orientation.HORIZONTAL,
            vexpand=True,
            wide_handle=False,
        )
        content_box.append(self._main_paned)
        toolbar_view.set_content(content_box)

        # Left: vertical split (editor / results)
        self._editor_results_paned = Gtk.Paned(
            orientation=Gtk.Orientation.VERTICAL,
            wide_handle=False,
            hexpand=True,
        )
        self._main_paned.set_start_child(self._editor_results_paned)
        self._main_paned.set_resize_start_child(True)
        self._main_paned.set_shrink_start_child(False)

        # ── SQL Editor ────────────────────────────────────────────────────
        editor_frame = Gtk.Frame()

        self._source_buffer = GtkSource.Buffer()
        lang_manager = GtkSource.LanguageManager.get_default()
        sql_lang = lang_manager.get_language('sql')
        if sql_lang:
            self._source_buffer.set_language(sql_lang)
        self._source_buffer.set_highlight_syntax(True)
        self._apply_source_scheme()

        adw_sm = Adw.StyleManager.get_default()
        adw_sm.connect('notify::dark', self._on_dark_mode_changed)

        self._source_view = GtkSource.View(buffer=self._source_buffer)
        self._apply_editor_settings()

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self._on_key_pressed)
        self._source_view.add_controller(key_ctrl)

        editor_scroll = Gtk.ScrolledWindow(
            vexpand=True,
            min_content_height=120,
        )
        editor_scroll.set_child(self._source_view)
        editor_frame.set_child(editor_scroll)
        self._editor_results_paned.set_start_child(editor_frame)
        self._editor_results_paned.set_resize_start_child(True)

        # ── Results area ──────────────────────────────────────────────────
        results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        results_notebook = Gtk.Notebook()
        results_notebook.set_vexpand(True)
        self._results_notebook = results_notebook

        # Results tab
        self._results_placeholder = self._make_placeholder(
            'media-playback-start-symbolic', 'Run a query to see results'
        )
        self._results_scroll = Gtk.ScrolledWindow(vexpand=True)
        self._results_stack = Gtk.Stack()
        self._results_stack.add_named(self._results_placeholder, 'placeholder')
        self._results_stack.add_named(self._results_scroll, 'table')
        self._results_stack.set_visible_child_name('placeholder')

        results_tab_box = Gtk.Box(spacing=6)
        results_tab_box.append(Gtk.Label(label='Results'))
        self._export_btn = Gtk.Button(
            icon_name='document-save-symbolic',
            tooltip_text='Export results…',
            sensitive=False,
        )
        self._export_btn.add_css_class('flat')
        self._export_btn.set_size_request(24, 24)
        self._export_btn.connect('clicked', self._on_export)
        results_tab_box.append(self._export_btn)
        results_notebook.append_page(self._results_stack, results_tab_box)

        # Messages tab
        self._messages_view = Gtk.TextView(
            editable=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            left_margin=8, right_margin=8,
            top_margin=8, bottom_margin=8,
        )
        self._messages_view.add_css_class('dim-label')
        messages_scroll = Gtk.ScrolledWindow(vexpand=True)
        messages_scroll.set_child(self._messages_view)
        results_notebook.append_page(messages_scroll, Gtk.Label(label='Messages'))

        results_box.append(results_notebook)
        self._editor_results_paned.set_end_child(results_box)
        self._editor_results_paned.set_resize_end_child(False)

        # ── Right drawer: history + snippets ──────────────────────────────
        self._right_stack = Gtk.Stack(visible=False, width_request=260)
        self._history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._snippets_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._right_stack.add_named(self._history_box, 'history')
        self._right_stack.add_named(self._snippets_box, 'snippets')

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        right_pane_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        right_pane_box.append(sep2)
        right_pane_box.append(self._right_stack)
        self._main_paned.set_end_child(right_pane_box)
        self._main_paned.set_resize_end_child(False)
        self._main_paned.set_shrink_end_child(True)

        GLib.idle_add(lambda: self._editor_results_paned.set_position(280) or False)

    def _build_header_widget(self) -> Gtk.Box:
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)

        self._status_label = Gtk.Label(label='')
        self._status_label.add_css_class('dim-label')
        self._status_label.add_css_class('caption')
        box.append(self._status_label)

        self._run_btn = Gtk.Button(
            label='Run',
            icon_name='media-playback-start-symbolic',
            tooltip_text='Run query (Ctrl+Enter / F5)',
        )
        self._run_btn.add_css_class('suggested-action')
        self._run_btn.add_css_class('pill')
        self._run_btn.connect('clicked', self._on_run)
        box.append(self._run_btn)

        return box

    def get_header_widget(self) -> Gtk.Widget:
        return self._header_widget

    def _make_placeholder(self, icon_name: str, message: str) -> Gtk.Widget:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            vexpand=True,
        )
        icon = Gtk.Image(icon_name=icon_name, pixel_size=48)
        icon.add_css_class('dim-label')
        label = Gtk.Label(label=message)
        label.add_css_class('dim-label')
        box.append(icon)
        box.append(label)
        return box

    # ── Settings ───────────────────────────────────────────────────────────

    def _apply_editor_settings(self):
        s = self._settings
        self._source_view.set_show_line_numbers(s.get_bool('editor.show_line_numbers'))
        self._source_view.set_tab_width(s.get_int('editor.tab_width'))
        self._source_view.set_auto_indent(s.get_bool('editor.auto_indent'))
        self._source_view.set_highlight_current_line(s.get_bool('editor.highlight_current_line'))
        self._source_view.set_monospace(True)
        self._source_view.set_vexpand(True)
        self._source_view.set_hexpand(True)
        self._source_view.set_margin_top(4)
        self._source_view.set_margin_bottom(4)
        self._source_view.set_margin_start(4)
        wrap = Gtk.WrapMode.WORD_CHAR if s.get_bool('editor.word_wrap') else Gtk.WrapMode.NONE
        self._source_view.set_wrap_mode(wrap)

        # Font size override via CSS provider
        size = s.get_int('editor.font_size')
        css = Gtk.CssProvider()
        css.load_from_string(f'textview {{ font-size: {size}pt; }}')
        self._source_view.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _on_settings_changed(self, manager, key: str):
        if key.startswith('editor.'):
            self._apply_editor_settings()
        if key.startswith('appearance.'):
            self._apply_source_scheme()

    def _apply_source_scheme(self):
        scheme_manager = GtkSource.StyleSchemeManager.get_default()
        adw_sm = Adw.StyleManager.get_default()
        name = 'Adwaita-dark' if adw_sm.get_dark() else 'Adwaita'
        scheme = scheme_manager.get_scheme(name) or scheme_manager.get_scheme('classic')
        if scheme:
            self._source_buffer.set_style_scheme(scheme)

    def _on_dark_mode_changed(self, *_):
        self._apply_source_scheme()

    # ── Find & Replace ────────────────────────────────────────────────────

    def _build_find_bar(self) -> Gtk.Revealer:
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)

        bar_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=0,
        )

        # Row 1: find
        find_row = Gtk.Box(
            spacing=4,
            margin_start=8, margin_end=8,
            margin_top=6, margin_bottom=3,
        )

        self._find_entry = Gtk.SearchEntry(placeholder_text='Find…', hexpand=True)
        self._find_entry.connect('search-changed', self._on_find_changed)
        self._find_entry.connect('activate', self._on_find_next)
        self._find_entry.connect('stop-search', lambda *_: self._find_btn.set_active(False))

        prev_btn = Gtk.Button(icon_name='go-up-symbolic', tooltip_text='Previous (Shift+Enter)')
        prev_btn.add_css_class('flat')
        prev_btn.connect('clicked', self._on_find_prev)

        next_btn = Gtk.Button(icon_name='go-down-symbolic', tooltip_text='Next (Enter)')
        next_btn.add_css_class('flat')
        next_btn.connect('clicked', self._on_find_next)

        self._match_label = Gtk.Label(label='', width_chars=8)
        self._match_label.add_css_class('dim-label')
        self._match_label.add_css_class('caption')

        close_btn = Gtk.Button(icon_name='window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.connect('clicked', lambda *_: self._find_btn.set_active(False))

        find_row.append(self._find_entry)
        find_row.append(prev_btn)
        find_row.append(next_btn)
        find_row.append(self._match_label)
        find_row.append(close_btn)

        # Row 2: replace
        replace_row = Gtk.Box(
            spacing=4,
            margin_start=8, margin_end=8,
            margin_top=0, margin_bottom=6,
        )

        self._replace_entry = Gtk.Entry(placeholder_text='Replace with…', hexpand=True)

        replace_btn = Gtk.Button(label='Replace')
        replace_btn.add_css_class('flat')
        replace_btn.connect('clicked', self._on_replace_one)

        replace_all_btn = Gtk.Button(label='Replace All')
        replace_all_btn.add_css_class('flat')
        replace_all_btn.connect('clicked', self._on_replace_all)

        replace_row.append(self._replace_entry)
        replace_row.append(replace_btn)
        replace_row.append(replace_all_btn)

        bar_box.append(find_row)
        bar_box.append(replace_row)
        bar_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        revealer.set_child(bar_box)

        # Bind toggle button → revealer
        self._find_btn.bind_property(
            'active', revealer, 'reveal-child',
            GObject.BindingFlags.SYNC_CREATE,
        )
        self._find_btn.connect('toggled', self._on_find_toggled)

        return revealer

    def _init_search_context(self):
        if hasattr(self, '_search_context'):
            return
        search_settings = GtkSource.SearchSettings()
        search_settings.set_wrap_around(True)
        search_settings.set_case_sensitive(False)
        self._search_settings = search_settings
        self._search_context = GtkSource.SearchContext.new(
            self._source_buffer, search_settings
        )
        self._search_context.set_highlight(True)
        self._search_context.connect('notify::occurrences-count', self._update_match_label)

    def _on_find_toggled(self, btn):
        if btn.get_active():
            self._init_search_context()
            self._find_entry.grab_focus()
        else:
            if hasattr(self, '_search_context'):
                self._search_settings.set_search_text('')
            self._match_label.set_label('')

    def _on_find_changed(self, entry):
        self._init_search_context()
        self._search_settings.set_search_text(entry.get_text())
        self._update_match_label()

    def _update_match_label(self, *_):
        if not hasattr(self, '_search_context'):
            return
        n = self._search_context.get_occurrences_count()
        self._match_label.set_label(f'{n} match{"es" if n != 1 else ""}' if n >= 0 else '')

    def _on_find_next(self, *_):
        self._init_search_context()
        insert = self._source_buffer.get_iter_at_mark(self._source_buffer.get_insert())
        found, start, end, _ = self._search_context.forward(insert)
        if found:
            self._source_buffer.select_range(start, end)
            self._source_view.scroll_to_mark(self._source_buffer.get_insert(), 0.1, False, 0, 0)

    def _on_find_prev(self, *_):
        self._init_search_context()
        insert = self._source_buffer.get_iter_at_mark(self._source_buffer.get_insert())
        found, start, end, _ = self._search_context.backward(insert)
        if found:
            self._source_buffer.select_range(start, end)
            self._source_view.scroll_to_mark(self._source_buffer.get_insert(), 0.1, False, 0, 0)

    def _on_replace_one(self, *_):
        self._init_search_context()
        replacement = self._replace_entry.get_text()
        if self._source_buffer.get_has_selection():
            start, end = self._source_buffer.get_selection_bounds()
            self._search_context.replace(start, end, replacement, -1)
        self._on_find_next()

    def _on_replace_all(self, *_):
        self._init_search_context()
        replacement = self._replace_entry.get_text()
        n = self._search_context.replace_all(replacement, -1)
        self._window.toast(f'Replaced {n} occurrence{"s" if n != 1 else ""}')

    # ── Format SQL ────────────────────────────────────────────────────────

    def _on_format_sql(self, *_):
        buf = self._source_buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            sql = buf.get_text(start, end, False)
        else:
            start = buf.get_start_iter()
            end   = buf.get_end_iter()
            sql   = buf.get_text(start, end, False)

        if not sql.strip():
            return

        try:
            import sqlparse
            formatted = sqlparse.format(
                sql,
                reindent=True,
                keyword_case='upper',
                identifier_case='lower',
                strip_comments=False,
                indent_width=self._settings.get_int('editor.tab_width'),
            )
        except Exception as e:
            self._window.toast_error(f'Format failed: {e}')
            return

        buf.begin_user_action()
        buf.delete(start, end)
        buf.insert(buf.get_iter_at_mark(buf.get_insert()), formatted)
        buf.end_user_action()

    # ── Open SQL file ─────────────────────────────────────────────────────

    def _on_open_file(self, *_):
        from gi.repository import Gio as _Gio
        file_dialog = Gtk.FileDialog(title='Open SQL File')
        filter_ = Gtk.FileFilter()
        filter_.set_name('SQL files')
        filter_.add_pattern('*.sql')
        filter_.add_pattern('*.txt')
        filters = _Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_)
        file_dialog.set_filters(filters)

        def on_response(d, result):
            try:
                f = d.open_finish(result)
            except Exception:
                return
            if not f:
                return
            path = f.get_path()
            try:
                with open(path, encoding='utf-8') as fp:
                    content = fp.read()
                self._source_buffer.set_text(content)
                self._source_view.grab_focus()
            except Exception as e:
                self._window.toast_error(f'Could not open file: {e}')

        file_dialog.open(self._window, None, on_response)

    # ── EXPLAIN ───────────────────────────────────────────────────────────

    def _on_explain(self, *_):
        buf = self._source_buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            sql = buf.get_text(start, end, False).strip()
        else:
            sql = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()

        if not sql:
            self._window.toast_error('No query to explain')
            return
        if not self._db or not self._db.is_connected:
            self._window.toast_error('Not connected')
            return

        dialect = self._db._engine.dialect.name
        if dialect == 'postgresql':
            explain_sql = f'EXPLAIN ANALYZE {sql}'
        elif dialect in ('mysql', 'mariadb'):
            explain_sql = f'EXPLAIN {sql}'
        else:
            explain_sql = f'EXPLAIN QUERY PLAN {sql}'

        self._status_label.set_label('Explaining…')
        self._db.execute_async(
            explain_sql,
            on_success=self._on_explain_success,
            on_error=lambda e: (
                self._status_label.set_label(''),
                self._window.toast_error(f'EXPLAIN failed: {e}'),
            ),
        )

    def _on_explain_success(self, columns, rows, rowcount):
        self._status_label.set_label('')
        if not columns:
            self._window.toast('EXPLAIN returned no output')
            return
        # Show in results area with an "Explain" label on the tab
        from .results_view import build_results_view
        widget = build_results_view(columns, rows, show_row_numbers=False)
        self._results_scroll.set_child(widget)
        self._results_stack.set_visible_child_name('table')
        self._results_notebook.set_current_page(0)

    # ── Snippets ─────────────────────────────────────────────────────────

    def _on_save_snippet(self, *_):
        buf = self._source_buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            sql = buf.get_text(start, end, False).strip()
        else:
            sql = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not sql:
            self._window.toast_error('Nothing to save')
            return
        from .snippets import show_save_snippet_dialog
        show_save_snippet_dialog(
            self._window, sql,
            on_saved=lambda _: (
                self._window.toast('Snippet saved'),
                self._snippets_panel.refresh() if hasattr(self, '_snippets_panel') else None,
            ),
        )

    def _on_snippets_toggled(self, btn):
        if btn.get_active():
            self._history_btn.set_active(False)
            self._right_stack.set_visible(True)
            self._right_stack.set_visible_child_name('snippets')
        else:
            if not self._history_btn.get_active():
                self._right_stack.set_visible(False)

    def _init_snippets(self):
        from .snippets import SnippetsPanel
        self._snippets_panel = SnippetsPanel(on_pick=self._insert_from_snippet)
        self._snippets_box.append(self._snippets_panel)

    def _insert_from_snippet(self, sql: str):
        self._source_buffer.set_text(sql)
        self._source_view.grab_focus()

    # ── Auto-save ─────────────────────────────────────────────────────────

    def _autosave_path(self) -> str:
        config_dir = os.path.join(
            os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')),
            'reliquary', 'autosave',
        )
        os.makedirs(config_dir, exist_ok=True)
        safe_id = self._config.id.replace('/', '_')
        return os.path.join(config_dir, f'{safe_id}.sql')

    def save_editor_content(self):
        buf = self._source_buffer
        sql = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        if sql.strip():
            try:
                with open(self._autosave_path(), 'w', encoding='utf-8') as f:
                    f.write(sql)
            except Exception:
                pass

    def restore_editor_content(self):
        path = self._autosave_path()
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    content = f.read()
                if content.strip():
                    self._source_buffer.set_text(content)
            except Exception:
                pass

    # ── History ────────────────────────────────────────────────────────────

    def _init_history(self):
        if not self._settings.get_bool('query.save_history'):
            return
        from .history import QueryHistory, HistoryPanel
        max_h = self._settings.get_int('query.max_history')
        self._history = QueryHistory(self._config.id, max_h)

        self._history_panel = HistoryPanel(
            history=self._history,
            on_pick=self._insert_from_history,
        )
        self._history_box.append(self._history_panel)

    def _on_history_toggled(self, btn):
        if btn.get_active():
            self._snippets_btn.set_active(False)
            self._right_stack.set_visible(True)
            self._right_stack.set_visible_child_name('history')
        else:
            if not self._snippets_btn.get_active():
                self._right_stack.set_visible(False)

    def _insert_from_history(self, sql: str):
        self._source_buffer.set_text(sql)
        self._source_view.grab_focus()

    # ── Auto-complete ──────────────────────────────────────────────────────

    def _init_autocomplete(self):
        from .autocomplete import attach_completion
        self._completion_provider = attach_completion(self._source_view)
        if self._db and self._db.is_connected:
            self._completion_provider.load_schema_async(self._db, self._schema)

    # ── Key handling ───────────────────────────────────────────────────────

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        from gi.repository import Gdk
        ctrl_mask = state & Gdk.ModifierType.CONTROL_MASK
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and ctrl_mask:
            self._on_run()
            return True
        if keyval == Gdk.KEY_F5:
            self._on_run()
            return True
        if keyval == Gdk.KEY_f and ctrl_mask:
            self._find_btn.set_active(not self._find_btn.get_active())
            return True
        if keyval == Gdk.KEY_o and ctrl_mask:
            self._on_open_file()
            return True
        if keyval == Gdk.KEY_Escape and self._find_btn.get_active():
            self._find_btn.set_active(False)
            return True
        return False

    # ── Run query ─────────────────────────────────────────────────────────

    def _on_run(self, *_):
        if self._running:
            return

        buf = self._source_buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            sql = buf.get_text(start, end, False)
        else:
            sql = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()

        if not sql:
            return

        if not self._db or not self._db.is_connected:
            self._window.toast_error('Not connected to database')
            return

        # Destructive query guard
        if self._settings.get_bool('query.confirm_destructive'):
            match = _DESTRUCTIVE_RE.search(sql)
            if match:
                verb = match.group(1).upper()
                is_dml = verb in ('DELETE', 'UPDATE')
                no_where = is_dml and not _WHERE_RE.search(sql)
                is_drop  = verb == 'DROP'
                is_trunc = verb == 'TRUNCATE'
                if no_where or is_drop or is_trunc:
                    self._confirm_destructive(sql, verb)
                    return

        self._execute_sql(sql)

    def _confirm_destructive(self, sql: str, verb: str):
        dialog = Adw.AlertDialog(
            heading=f'{verb} without WHERE?',
            body=f'This {verb} statement has no WHERE clause and will affect all rows. Proceed?',
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('run', f'Run {verb}')
        dialog.set_response_appearance('run', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')

        def on_response(d, response):
            if response == 'run':
                self._execute_sql(sql)

        dialog.connect('response', on_response)
        dialog.present(self._window)

    def _execute_sql(self, sql: str):
        statements = _split_statements(sql)
        if len(statements) > 1:
            self._execute_multi(statements)
        else:
            self._execute_single(sql)

    def _execute_single(self, sql: str):
        if (self._settings.get_bool('query.auto_limit')
                and _SELECT_RE.match(sql)
                and not _LIMIT_RE.search(sql)):
            limit = self._settings.get_int('query.auto_limit_rows')
            sql_to_run = sql.rstrip().rstrip(';') + f'\nLIMIT {limit}'
        else:
            sql_to_run = sql

        self._running = True
        self._start_time = time.monotonic()
        self._run_btn.set_sensitive(False)
        self._status_label.set_label('Running…')
        self._log_message(f'-- Running --\n{sql_to_run}\n')

        self._db.execute_async(
            sql_to_run,
            on_success=self._on_query_success,
            on_error=self._on_query_error,
        )

    def _execute_multi(self, statements: list[str]):
        """Run multiple statements sequentially in a thread; show final SELECT result."""
        self._running = True
        self._start_time = time.monotonic()
        self._run_btn.set_sensitive(False)
        self._status_label.set_label(f'Running {len(statements)} statements…')
        self._log_message(f'-- Running {len(statements)} statements --\n')

        def run():
            last_cols, last_rows, last_rc = [], [], 0
            errors = []
            for i, stmt in enumerate(statements, 1):
                try:
                    cols, rows, rc = self._db.execute_query(stmt)
                    msg = (f'[{i}/{len(statements)}] OK: {len(rows):,} rows\n'
                           if cols else
                           f'[{i}/{len(statements)}] OK: {rc:,} rows affected\n')
                    GLib.idle_add(self._log_message, msg)
                    if cols:
                        last_cols, last_rows, last_rc = cols, rows, rc
                    else:
                        last_rc = rc
                except Exception as e:
                    errors.append(f'[{i}/{len(statements)}] ERROR: {e}')
                    GLib.idle_add(self._log_message, errors[-1] + '\n')

            if errors:
                GLib.idle_add(self._on_query_error, errors[-1])
            else:
                GLib.idle_add(self._on_query_success, last_cols, last_rows, last_rc)

        import threading as _threading
        _threading.Thread(target=run, daemon=True).start()

    def _on_query_success(self, columns: list[str], rows: list[tuple], rowcount: int):
        elapsed_ms = int((time.monotonic() - self._start_time) * 1000)
        elapsed_s  = elapsed_ms / 1000
        self._running = False
        self._run_btn.set_sensitive(True)

        if columns:
            self._last_columns = columns
            self._last_rows = rows
            self._status_label.set_label(f'{len(rows):,} rows  {elapsed_s:.3f}s')
            self._show_results(columns, rows)
            self._results_notebook.set_current_page(0)
            self._export_btn.set_sensitive(True)
            self._log_message(f'-- OK: {len(rows):,} rows in {elapsed_s:.3f}s --\n')
        else:
            self._status_label.set_label(f'{rowcount:,} rows affected  {elapsed_s:.3f}s')
            self._results_stack.set_visible_child_name('placeholder')
            self._export_btn.set_sensitive(False)
            self._log_message(f'-- OK: {rowcount:,} rows affected in {elapsed_s:.3f}s --\n')
            self._results_notebook.set_current_page(1)

        # Record in history
        if self._history and self._settings.get_bool('query.save_history'):
            buf = self._source_buffer
            original_sql = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
            self._history.add(original_sql, elapsed_ms, len(rows) if columns else rowcount)
            if hasattr(self, '_history_panel'):
                self._history_panel.refresh()

    def _on_query_error(self, error: str):
        elapsed_s = time.monotonic() - self._start_time
        self._running = False
        self._run_btn.set_sensitive(True)
        self._status_label.set_label(f'Error  {elapsed_s:.3f}s')
        self._log_message(f'-- ERROR --\n{error}\n')
        self._results_notebook.set_current_page(1)
        self._window.toast_error(f'Query error: {error[:80]}')

        if self._history and self._settings.get_bool('query.save_history'):
            buf = self._source_buffer
            original_sql = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
            elapsed_ms = int((time.monotonic() - self._start_time) * 1000)
            self._history.add(original_sql, elapsed_ms, 0, error=error[:200])
            if hasattr(self, '_history_panel'):
                self._history_panel.refresh()

    # ── Results grid ───────────────────────────────────────────────────────

    def _show_results(self, columns: list[str], rows: list[tuple]):
        from .results_view import build_results_view
        from .settings import SettingsManager
        show_row_nums = SettingsManager.get_default().get_bool('appearance.show_row_numbers')
        widget = build_results_view(columns, rows, show_row_numbers=show_row_nums)
        self._results_scroll.set_child(widget)
        self._results_stack.set_visible_child_name('table')

    # ── Export ────────────────────────────────────────────────────────────

    def _on_export(self, *_):
        if not self._last_columns:
            return
        from .export import export_results
        export_results(
            parent=self,
            columns=self._last_columns,
            rows=self._last_rows,
            suggested_name=f'query_{self._config.name}',
        )

    # ── Messages log ──────────────────────────────────────────────────────

    def _log_message(self, text: str):
        buf = self._messages_view.get_buffer()
        end = buf.get_end_iter()
        buf.insert(end, text)
        adj = self._messages_view.get_vadjustment()
        if adj:
            GLib.idle_add(lambda: adj.set_value(adj.get_upper()) or False)
