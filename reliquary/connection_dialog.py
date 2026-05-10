from typing import Callable, Optional, TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib, Gio

if TYPE_CHECKING:
    from .database.manager import ConnectionConfig, ConnectionManager


DRIVERS = [
    ('SQLite',      'sqlite'),
    ('PostgreSQL',  'postgresql'),
    ('MySQL / MariaDB', 'mysql'),
]


class ConnectionDialog(Adw.Dialog):
    """Add or edit a database connection."""

    def __init__(
        self,
        parent: Gtk.Widget,
        manager: 'ConnectionManager',
        config: Optional['ConnectionConfig'],
        on_saved: Callable,
        on_deleted: Callable,
    ):
        super().__init__(title='Connection' if config else 'New Connection')
        self._manager = manager
        self._config = config
        self._on_saved = on_saved
        self._on_deleted = on_deleted
        self._is_edit = config is not None

        self.set_content_width(480)
        self.set_content_height(560)

        self._build_ui()
        if config:
            self._populate_from_config(config)
        else:
            self._on_driver_changed(self._driver_row)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        # Header
        header = Adw.HeaderBar()
        header.add_css_class('flat')
        toolbar_view.add_top_bar(header)

        title = Adw.WindowTitle(
            title='Edit Connection' if self._is_edit else 'New Connection'
        )
        header.set_title_widget(title)

        # Cancel button
        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda *_: self.close())
        header.pack_start(cancel_btn)

        # Save button
        self._save_btn = Gtk.Button(label='Save')
        self._save_btn.add_css_class('suggested-action')
        self._save_btn.connect('clicked', self._on_save)
        header.pack_end(self._save_btn)

        # Scrolled content
        scroll = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        toolbar_view.set_content(scroll)

        clamp = Adw.Clamp(maximum_size=420, margin_top=12, margin_bottom=12)
        scroll.set_child(clamp)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        clamp.set_child(main_box)

        # ── General group ─────────────────────────────────────────────────
        general_group = Adw.PreferencesGroup(title='General')
        main_box.append(general_group)

        self._name_row = Adw.EntryRow(title='Connection name')
        self._name_row.set_text(self._config.name if self._config else '')
        general_group.add(self._name_row)

        # Driver selector (combo row)
        self._driver_row = Adw.ComboRow(title='Database type')
        driver_model = Gtk.StringList()
        for label, _ in DRIVERS:
            driver_model.append(label)
        self._driver_row.set_model(driver_model)
        self._driver_row.connect('notify::selected', self._on_driver_changed)
        general_group.add(self._driver_row)

        # ── SQLite group ──────────────────────────────────────────────────
        self._sqlite_group = Adw.PreferencesGroup(title='SQLite File')
        main_box.append(self._sqlite_group)

        # "Create new database" row — prominent, listed first
        create_row = Adw.ActionRow(
            title='Create new database',
            subtitle='Start with a blank SQLite file',
            activatable=True,
        )
        create_row.add_prefix(Gtk.Image(
            icon_name='document-new-symbolic', pixel_size=16,
        ))
        create_row.add_suffix(Gtk.Image(
            icon_name='go-next-symbolic', css_classes=['dim-label'],
        ))
        create_row.connect('activated', self._new_file)
        self._sqlite_group.add(create_row)

        # "Open existing file" row
        open_row = Adw.ActionRow(
            title='Open existing file',
            subtitle='Connect to an existing SQLite database',
            activatable=True,
        )
        open_row.add_prefix(Gtk.Image(
            icon_name='document-open-symbolic', pixel_size=16,
        ))
        open_row.add_suffix(Gtk.Image(
            icon_name='go-next-symbolic', css_classes=['dim-label'],
        ))
        open_row.connect('activated', self._browse_file)
        self._sqlite_group.add(open_row)

        # File path entry (shown after a file is chosen)
        self._file_entry = Gtk.Entry(
            hexpand=True,
            placeholder_text='No file selected',
            editable=False,
        )
        self._file_entry.add_css_class('monospace')
        file_path_row = Adw.ActionRow(title='Selected file')
        file_path_row.add_suffix(self._file_entry)
        self._file_row = file_path_row
        self._sqlite_group.add(file_path_row)

        # ── Network group ─────────────────────────────────────────────────
        self._network_group = Adw.PreferencesGroup(title='Server')
        main_box.append(self._network_group)

        self._host_row = Adw.EntryRow(title='Host', text='localhost')
        self._network_group.add(self._host_row)

        self._port_row = Adw.SpinRow.new_with_range(1, 65535, 1)
        self._port_row.set_title('Port')
        self._port_row.set_value(5432)
        self._network_group.add(self._port_row)

        self._database_row = Adw.EntryRow(title='Database')
        self._network_group.add(self._database_row)

        self._create_db_row = Adw.SwitchRow(
            title='Create database if it does not exist',
        )
        self._network_group.add(self._create_db_row)

        # ── Auth group ────────────────────────────────────────────────────
        self._auth_group = Adw.PreferencesGroup(title='Authentication')
        main_box.append(self._auth_group)

        self._user_row = Adw.EntryRow(title='Username')
        self._auth_group.add(self._user_row)

        self._pass_row = Adw.PasswordEntryRow(title='Password')
        self._auth_group.add(self._pass_row)

        # ── Test / Delete ─────────────────────────────────────────────────
        actions_group = Adw.PreferencesGroup()
        main_box.append(actions_group)

        test_row = Adw.ActionRow(title='Test connection')
        test_btn = Gtk.Button(label='Test', valign=Gtk.Align.CENTER)
        test_btn.add_css_class('flat')
        test_btn.connect('clicked', self._on_test)
        test_row.add_suffix(test_btn)
        test_row.set_activatable_widget(test_btn)
        actions_group.add(test_row)

        self._test_status = Gtk.Label(label='', xalign=0, margin_start=12, margin_bottom=4)
        self._test_status.add_css_class('dim-label')
        main_box.append(self._test_status)

        if self._is_edit:
            delete_group = Adw.PreferencesGroup()
            main_box.append(delete_group)
            delete_row = Adw.ActionRow(title='Remove connection')
            delete_row.add_css_class('error')
            del_btn = Gtk.Button(label='Remove', valign=Gtk.Align.CENTER)
            del_btn.add_css_class('destructive-action')
            del_btn.connect('clicked', self._on_delete)
            delete_row.add_suffix(del_btn)
            delete_row.set_activatable_widget(del_btn)
            delete_group.add(delete_row)

    # ── Driver switching ───────────────────────────────────────────────────

    def _on_driver_changed(self, row, *_):
        idx = row.get_selected() if hasattr(row, 'get_selected') else 0
        _, driver = DRIVERS[idx]
        is_sqlite = driver == 'sqlite'

        self._sqlite_group.set_visible(is_sqlite)
        self._network_group.set_visible(not is_sqlite)
        self._auth_group.set_visible(not is_sqlite)
        # Only show "create DB" switch for new connections, not edits
        self._create_db_row.set_visible(not is_sqlite and not self._is_edit)

        if not is_sqlite:
            default_ports = {'postgresql': 5432, 'mysql': 3306}
            self._port_row.set_value(default_ports.get(driver, 5432))

    # ── Populate from existing config ──────────────────────────────────────

    def _populate_from_config(self, cfg):
        self._name_row.set_text(cfg.name)

        driver_map = {d: i for i, (_, d) in enumerate(DRIVERS)}
        idx = driver_map.get(cfg.driver, 0)
        self._driver_row.set_selected(idx)

        if cfg.driver == 'sqlite':
            self._file_entry.set_text(cfg.file_path or '')
        else:
            self._host_row.set_text(cfg.host)
            self._port_row.set_value(cfg.port)
            self._database_row.set_text(cfg.database)
            self._user_row.set_text(cfg.username)
            self._pass_row.set_text(cfg.password)

    # ── Collect config from form ───────────────────────────────────────────

    def _collect_config(self) -> tuple[bool, str, dict]:
        name = self._name_row.get_text().strip()
        if not name:
            return False, 'Connection name is required', {}

        idx = self._driver_row.get_selected()
        _, driver = DRIVERS[idx]

        data = dict(name=name, driver=driver)

        if driver == 'sqlite':
            fp = self._file_entry.get_text().strip()
            if not fp:
                return False, 'File path is required', {}
            data['file_path'] = fp
        else:
            data['host'] = self._host_row.get_text().strip() or 'localhost'
            data['port'] = int(self._port_row.get_value())
            data['database'] = self._database_row.get_text().strip()
            data['username'] = self._user_row.get_text().strip()
            data['password'] = self._pass_row.get_text()

        return True, '', data

    # ── File browser ──────────────────────────────────────────────────────

    def _new_file(self, *_):
        dialog = Gtk.FileDialog(title='Create New SQLite Database')
        dialog.set_initial_name('database.sqlite')
        filter_ = Gtk.FileFilter()
        filter_.set_name('SQLite databases')
        filter_.add_pattern('*.sqlite')
        filter_.add_pattern('*.db')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_)
        dialog.set_filters(filters)

        def on_response(d, result):
            try:
                f = d.save_finish(result)
                if f:
                    path = f.get_path()
                    self._file_entry.set_text(path)
                    if not self._name_row.get_text().strip():
                        import os
                        self._name_row.set_text(
                            os.path.splitext(os.path.basename(path))[0]
                        )
            except Exception:
                pass
        dialog.save(self.get_root(), None, on_response)

    def _browse_file(self, *_):
        dialog = Gtk.FileDialog(title='Open SQLite Database')
        filter_ = Gtk.FileFilter()
        filter_.set_name('SQLite databases')
        filter_.add_pattern('*.sqlite')
        filter_.add_pattern('*.db')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_)
        dialog.set_filters(filters)

        def on_response(d, result):
            try:
                f = d.open_finish(result)
                if f:
                    self._file_entry.set_text(f.get_path())
            except Exception:
                pass
        dialog.open(self.get_root(), None, on_response)

    # ── Test connection ────────────────────────────────────────────────────

    def _on_test(self, *_):
        ok, err, data = self._collect_config()
        if not ok:
            self._test_status.set_label(f'⚠ {err}')
            self._test_status.remove_css_class('success')
            self._test_status.add_css_class('error')
            return

        self._test_status.set_label('Testing…')
        self._test_status.remove_css_class('success')
        self._test_status.remove_css_class('error')

        from .database.manager import ConnectionConfig
        from .database.connection import DatabaseConnection
        import threading

        cfg = ConnectionConfig.make_new(**data)

        def run():
            try:
                db = DatabaseConnection(cfg)
                db.connect()
                db.disconnect()
                GLib.idle_add(lambda: (
                    self._test_status.set_label('✓ Connection successful'),
                    self._test_status.add_css_class('success'),
                    self._test_status.remove_css_class('error'),
                ) and False)
            except Exception as e:
                msg = str(e)[:120]
                GLib.idle_add(lambda m=msg: (
                    self._test_status.set_label(f'✗ {m}'),
                    self._test_status.add_css_class('error'),
                    self._test_status.remove_css_class('success'),
                ) and False)

        threading.Thread(target=run, daemon=True).start()

    # ── Save ───────────────────────────────────────────────────────────────

    def _on_save(self, *_):
        ok, err, data = self._collect_config()
        if not ok:
            self._test_status.set_label(f'⚠ {err}')
            self._test_status.add_css_class('error')
            return

        should_create = (
            not self._is_edit
            and data.get('driver') in ('postgresql', 'mysql')
            and self._create_db_row.get_active()
        )

        if should_create:
            self._save_btn.set_sensitive(False)
            self._test_status.set_label('Creating database…')
            self._test_status.remove_css_class('error')
            import threading

            def run():
                err_msg = self._create_server_database(data)
                GLib.idle_add(lambda: self._finish_save(data, err_msg))

            threading.Thread(target=run, daemon=True).start()
        else:
            self._finish_save(data, None)

    def _create_server_database(self, data: dict) -> str | None:
        """Connect to the server's admin database and run CREATE DATABASE. Returns error string or None."""
        from sqlalchemy import create_engine, text
        driver   = data['driver']
        host     = data['host']
        port     = data['port']
        db_name  = data['database']
        username = data['username']
        password = data['password']

        try:
            if driver == 'postgresql':
                url = f'postgresql+psycopg2://{username}:{password}@{host}:{port}/postgres'
                engine = create_engine(url, isolation_level='AUTOCOMMIT')
                with engine.connect() as conn:
                    conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            elif driver in ('mysql', 'mariadb', 'mysql'):
                url = f'mysql+pymysql://{username}:{password}@{host}:{port}/'
                engine = create_engine(url)
                with engine.connect() as conn:
                    conn.execute(text(f'CREATE DATABASE `{db_name}`'))
                    conn.commit()
            return None
        except Exception as e:
            return str(e)

    def _finish_save(self, data: dict, create_error: str | None):
        self._save_btn.set_sensitive(True)
        if create_error:
            self._test_status.set_label(f'✗ {create_error[:120]}')
            self._test_status.add_css_class('error')
            return

        from .database.manager import ConnectionConfig
        if self._is_edit:
            cfg = ConnectionConfig(id=self._config.id, **data)
            self._manager.update(cfg)
        else:
            cfg = ConnectionConfig.make_new(**data)
            self._manager.add(cfg)

        self._on_saved(cfg)
        self.close()

    # ── Delete ─────────────────────────────────────────────────────────────

    def _on_delete(self, *_):
        dialog = Adw.AlertDialog(
            heading='Remove Connection?',
            body=f'"{self._config.name}" will be removed. This cannot be undone.',
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('delete', 'Remove')
        dialog.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')

        def on_response(d, response):
            if response == 'delete':
                self._manager.remove(self._config.id)
                self._on_deleted(self._config.id)
                self.close()

        dialog.connect('response', on_response)
        dialog.present(self)
