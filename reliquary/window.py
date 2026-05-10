import threading
from gi.repository import Gtk, Adw, Gio, GLib, GObject

def _driver_icon_for(driver: str) -> str:
    return {
        'sqlite':     'drive-harddisk-symbolic',
        'postgresql': 'network-server-symbolic',
        'mysql':      'network-server-symbolic',
    }.get(driver, 'network-server-symbolic')

from .database.manager import ConnectionManager, ConnectionConfig
from .database.connection import DatabaseConnection


class ReliquaryWindow(Adw.ApplicationWindow):
    def __init__(self, manager: ConnectionManager, **kwargs):
        super().__init__(
            title='Reliquary',
            default_width=1200,
            default_height=780,
            **kwargs,
        )
        self.manager = manager
        self._connections: dict[str, DatabaseConnection] = {}

        self._build_ui()
        self._populate_sidebar()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        from .sidebar import SidebarWidget

        # Toast overlay wraps everything
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        # Split view is the direct top-level child (GNOME Files / Calendar pattern)
        self._split_view = Adw.OverlaySplitView(
            sidebar_width_fraction=0.22,
            min_sidebar_width=220,
            max_sidebar_width=380,
            show_sidebar=True,
        )
        self._toast_overlay.set_child(self._split_view)

        # ── Sidebar pane ───────────────────────────────────────────────────
        sidebar_toolbar_view = Adw.ToolbarView()

        sidebar_header = Adw.HeaderBar()
        sidebar_header.add_css_class('flat')
        sidebar_header.set_show_start_title_buttons(False)
        sidebar_header.set_show_end_title_buttons(False)
        sidebar_header.set_title_widget(
            Adw.WindowTitle(title='Reliquary', subtitle='')
        )

        search_toggle = Gtk.ToggleButton(
            icon_name='edit-find-symbolic',
            tooltip_text='Filter connections',
        )
        search_toggle.add_css_class('flat')
        sidebar_header.pack_end(search_toggle)

        add_btn = Gtk.Button(
            icon_name='list-add-symbolic',
            tooltip_text='New connection',
            action_name='app.new-connection',
        )
        add_btn.add_css_class('flat')
        sidebar_header.pack_end(add_btn)

        sidebar_toolbar_view.add_top_bar(sidebar_header)

        self._sidebar = SidebarWidget(window=self, search_toggle=search_toggle)
        sidebar_toolbar_view.set_content(self._sidebar)

        self._split_view.set_sidebar(sidebar_toolbar_view)

        # ── Content pane ───────────────────────────────────────────────────
        content_toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()

        self._sidebar_btn = Gtk.ToggleButton(
            icon_name='sidebar-show-symbolic',
            tooltip_text='Toggle sidebar',
            active=True,
        )
        header.pack_start(self._sidebar_btn)

        self._title_widget = Adw.WindowTitle(title='', subtitle='')
        header.set_title_widget(self._title_widget)

        # Slot for context-sensitive panel controls; panels fill this via get_header_widget()
        self._header_slot = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        header.pack_end(self._header_slot)

        menu_btn = Gtk.MenuButton(
            icon_name='open-menu-symbolic',
            tooltip_text='Main menu',
        )
        menu = Gio.Menu()
        menu.append('New Connection', 'app.new-connection')
        menu.append('Preferences', 'app.preferences')
        menu.append('Keyboard Shortcuts', 'app.shortcuts')
        menu.append('Quit', 'app.quit')
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        content_toolbar_view.add_top_bar(header)

        self._tab_view = Adw.TabView()
        tab_bar = Adw.TabBar()
        tab_bar.set_view(self._tab_view)
        tab_bar.set_autohide(False)
        content_toolbar_view.add_top_bar(tab_bar)

        self._tab_view.connect('close-page', self._on_close_page)
        self._tab_view.connect('notify::selected-page', self._on_tab_changed)
        self._tab_view.connect('notify::n-pages', self._on_n_pages_changed)

        content_toolbar_view.set_content(self._tab_view)
        self._split_view.set_content(content_toolbar_view)

        # Bind sidebar toggle ↔ split view
        self._sidebar_btn.bind_property(
            'active', self._split_view, 'show-sidebar',
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )

        # Welcome page shown when no tabs exist
        self._show_welcome_tab()

    def _show_welcome_tab(self):
        self._welcome_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True,
        )
        self._refresh_welcome_content()

        page = self._tab_view.append(self._welcome_scroll)
        page.set_title('Start')
        page.set_icon(Gio.ThemedIcon.new('drive-multidisk-symbolic'))
        self._welcome_page = page

    def _refresh_welcome_content(self):
        from .samples import SAMPLES

        clamp = Adw.Clamp(maximum_size=540, margin_top=20, margin_bottom=24,
                          margin_start=12, margin_end=12)
        self._welcome_scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(box)

        # ── Compact banner ────────────────────────────────────────────────
        banner = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_top=8,
            margin_bottom=4,
        )
        icon = Gtk.Image(icon_name='drive-multidisk-symbolic', pixel_size=48)
        icon.add_css_class('accent')

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                           spacing=2, valign=Gtk.Align.CENTER, hexpand=True)
        title_lbl = Gtk.Label(label='Reliquary', xalign=0)
        title_lbl.add_css_class('title-1')
        sub_lbl = Gtk.Label(
            label='A GNOME database client for SQLite, PostgreSQL and MySQL.',
            xalign=0, wrap=True,
        )
        sub_lbl.add_css_class('dim-label')
        text_box.append(title_lbl)
        text_box.append(sub_lbl)

        new_btn = Gtk.Button(
            label='New Connection',
            action_name='app.new-connection',
            valign=Gtk.Align.CENTER,
        )
        new_btn.add_css_class('suggested-action')
        new_btn.add_css_class('pill')

        banner.append(icon)
        banner.append(text_box)
        banner.append(new_btn)
        box.append(banner)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Saved connections ─────────────────────────────────────────────
        saved = [c for c in self.manager.get_all()
                 if not c.id.startswith('sample-')]
        if saved:
            saved_group = Adw.PreferencesGroup(title='Saved Connections')
            box.append(saved_group)
            for cfg in saved:
                row = Adw.ActionRow(
                    title=cfg.name,
                    subtitle=cfg.get_display_host(),
                    activatable=True,
                )
                row.add_prefix(Gtk.Image(
                    icon_name=_driver_icon_for(cfg.driver),
                    pixel_size=32,
                ))
                row.add_suffix(Gtk.Image(
                    icon_name='go-next-symbolic',
                    css_classes=['dim-label'],
                ))
                row.connect('activated', self._on_welcome_connect, cfg)
                saved_group.add(row)

        # ── Sample databases ──────────────────────────────────────────────
        samples_group = Adw.PreferencesGroup(
            title='Sample Databases',
            description='Pre-built databases to explore',
        )
        box.append(samples_group)

        for key, meta in SAMPLES.items():
            row = Adw.ActionRow(
                title=meta['name'],
                subtitle=meta['description'],
                activatable=True,
            )
            row.add_prefix(Gtk.Image(icon_name=meta['icon'], pixel_size=32))
            row.add_suffix(Gtk.Image(
                icon_name='go-next-symbolic',
                css_classes=['dim-label'],
            ))
            row.connect('activated', self._on_open_sample, key)
            samples_group.add(row)

    def _on_open_sample(self, row, key: str):
        from .samples import get_sample_path
        from .database.manager import ConnectionConfig
        path = get_sample_path(key)
        from .samples import SAMPLES
        meta = SAMPLES[key]
        cfg = self.manager.get(f'sample-{key}')
        if not cfg:
            cfg = ConnectionConfig(
                id=f'sample-{key}',
                name=f'{meta["name"]} (sample)',
                driver='sqlite',
                file_path=str(path),
            )
            self.manager.add(cfg)
            self._populate_sidebar()
        self.connect_to(cfg)
        GLib.timeout_add(400, lambda: self.open_query_editor(cfg) or False)

    def _on_welcome_connect(self, row, cfg: ConnectionConfig):
        self.connect_to(cfg)
        GLib.timeout_add(400, lambda: self.open_query_editor(cfg) or False)

    # ── Sidebar population ─────────────────────────────────────────────────

    def _populate_sidebar(self):
        self._sidebar.populate(self.manager.get_all(), self._connections)

    # ── Public interface used by sidebar & dialogs ─────────────────────────

    def open_new_connection_dialog(self, config: ConnectionConfig = None):
        from .connection_dialog import ConnectionDialog
        dialog = ConnectionDialog(
            parent=self,
            manager=self.manager,
            config=config,
            on_saved=self._on_connection_saved,
            on_deleted=self._on_connection_deleted,
        )
        dialog.present()

    def connect_to(self, config: ConnectionConfig):
        conn_id = config.id
        if conn_id in self._connections and self._connections[conn_id].is_connected:
            self.toast(f'Already connected to {config.name}')
            return

        db = DatabaseConnection(config)
        self._connections[conn_id] = db

        self._sidebar.set_connecting(conn_id, True)

        def on_connected():
            self._sidebar.set_connecting(conn_id, False)
            self._sidebar.set_connected(conn_id, True)
            self.toast(f'Connected to {config.name}')
            self._sidebar.load_schema(conn_id, db)
            return False

        def on_failed(error: str):
            self._connections.pop(conn_id, None)
            self._sidebar.set_connecting(conn_id, False)
            self.toast_error(f'Connection failed: {error}')
            return False

        def run():
            try:
                db.connect()
                GLib.idle_add(on_connected)
            except Exception as e:
                GLib.idle_add(on_failed, str(e))

        threading.Thread(target=run, daemon=True).start()

    def disconnect_from(self, config_id: str):
        db = self._connections.pop(config_id, None)
        if db:
            db.disconnect()
        self._sidebar.set_connected(config_id, False)
        cfg = self.manager.get(config_id)
        if cfg:
            self.toast(f'Disconnected from {cfg.name}')

    def open_query_editor(self, config: ConnectionConfig, schema: str = None):
        from .editor_panel import EditorPanel
        db = self._connections.get(config.id)
        if not db or not db.is_connected:
            self.connect_to(config)
            db = self._connections.get(config.id)

        panel = EditorPanel(window=self, config=config, db=db, schema=schema)
        page = self._tab_view.append(panel)
        page.set_title(f'Query — {config.name}')
        page.set_icon(Gio.ThemedIcon.new('accessories-text-editor-symbolic'))
        self._tab_view.set_selected_page(page)

        if self._welcome_page and self._tab_view.get_n_pages() > 1:
            self._tab_view.close_page(self._welcome_page)
            self._welcome_page = None

    def open_table_browser(self, config: ConnectionConfig, table: str, schema: str = None):
        from .table_panel import TablePanel
        db = self._connections.get(config.id)
        if not db or not db.is_connected:
            self.toast_error('Not connected. Please connect first.')
            return

        panel = TablePanel(window=self, config=config, db=db, table=table, schema=schema)
        tab_name = f'{schema}.{table}' if schema else table
        page = self._tab_view.append(panel)
        page.set_title(tab_name)
        page.set_icon(Gio.ThemedIcon.new('x-office-spreadsheet-symbolic'))
        self._tab_view.set_selected_page(page)

        if self._welcome_page and self._tab_view.get_n_pages() > 1:
            self._tab_view.close_page(self._welcome_page)
            self._welcome_page = None

    def open_process_panel(self, config: ConnectionConfig):
        from .process_panel import ProcessPanel
        db = self._connections.get(config.id)
        if not db or not db.is_connected:
            self.toast_error('Not connected. Please connect first.')
            return
        panel = ProcessPanel(window=self, config=config, db=db)
        page = self._tab_view.append(panel)
        page.set_title(f'Processes — {config.name}')
        page.set_icon(Gio.ThemedIcon.new('system-run-symbolic'))
        self._tab_view.set_selected_page(page)
        if self._welcome_page and self._tab_view.get_n_pages() > 1:
            self._tab_view.close_page(self._welcome_page)
            self._welcome_page = None

    def open_structure_panel(self, config: ConnectionConfig, table: str, schema: str = None):
        from .structure_panel import StructurePanel
        db = self._connections.get(config.id)
        if not db or not db.is_connected:
            self.toast_error('Not connected. Please connect first.')
            return

        panel = StructurePanel(window=self, config=config, db=db, table=table, schema=schema)
        tab_name = f'{schema}.{table}' if schema else table
        page = self._tab_view.append(panel)
        page.set_title(f'{tab_name} — Structure')
        page.set_icon(Gio.ThemedIcon.new('dialog-information-symbolic'))
        self._tab_view.set_selected_page(page)

        if self._welcome_page and self._tab_view.get_n_pages() > 1:
            self._tab_view.close_page(self._welcome_page)
            self._welcome_page = None

    def get_connection(self, config_id: str) -> DatabaseConnection | None:
        return self._connections.get(config_id)

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_connection_saved(self, config: ConnectionConfig):
        self._populate_sidebar()
        if self._welcome_page:
            self._refresh_welcome_content()

    def _on_connection_deleted(self, config_id: str):
        self.disconnect_from(config_id)
        self._populate_sidebar()
        if self._welcome_page:
            self._refresh_welcome_content()

    def _on_close_page(self, tab_view, page):
        from .editor_panel import EditorPanel
        child = page.get_child()
        if isinstance(child, EditorPanel):
            child.save_editor_content()
        return False  # allow close

    def _on_n_pages_changed(self, tab_view, _param):
        if tab_view.get_n_pages() == 0:
            self._welcome_page = None
            self._show_welcome_tab()

    def _on_tab_changed(self, tab_view, _param):
        # Clear previous panel's header controls
        slot_child = self._header_slot.get_first_child()
        while slot_child:
            nxt = slot_child.get_next_sibling()
            self._header_slot.remove(slot_child)
            slot_child = nxt

        page = tab_view.get_selected_page()
        if not page:
            self._title_widget.set_title('')
            self._title_widget.set_subtitle('')
            return

        child = page.get_child()
        cfg = getattr(child, '_config', None)

        if cfg:
            self._title_widget.set_title(cfg.name)
            tab_title = page.get_title()
            if tab_title.startswith('Query — '):
                subtitle = 'Query Editor'
            elif tab_title.startswith('Processes — '):
                subtitle = 'Processes'
            elif tab_title.endswith(' — Structure'):
                subtitle = tab_title[: -len(' — Structure')] + ' · Structure'
            else:
                subtitle = tab_title
            self._title_widget.set_subtitle(subtitle)
        else:
            self._title_widget.set_title('')
            self._title_widget.set_subtitle('')

        # Insert the active panel's header controls
        hw = None
        if hasattr(child, 'get_header_widget'):
            hw = child.get_header_widget()
        if hw is not None and hw.get_parent() is None:
            self._header_slot.append(hw)

    # ── Toast helpers ──────────────────────────────────────────────────────

    def toast(self, message: str):
        toast = Adw.Toast(title=message, timeout=3)
        self._toast_overlay.add_toast(toast)

    def toast_error(self, message: str):
        toast = Adw.Toast(title=message, timeout=6)
        self._toast_overlay.add_toast(toast)
