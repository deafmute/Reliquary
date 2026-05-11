import threading
from typing import Optional, TYPE_CHECKING

from gi.repository import Gtk, Adw, GObject, Gio, GLib, Gdk, Pango

if TYPE_CHECKING:
    from .window import ReliquaryWindow
    from .database.manager import ConnectionConfig
    from .database.connection import DatabaseConnection


# ── Tree node model object ────────────────────────────────────────────────

class TreeNode(GObject.Object):
    __gtype_name__ = 'ReliquaryTreeNode'

    NODE_CONNECTION = 'connection'
    NODE_SCHEMA     = 'schema'
    NODE_GROUP      = 'group'    # "Tables" / "Views" header
    NODE_TABLE      = 'table'
    NODE_VIEW       = 'view'
    NODE_COLUMN     = 'column'

    def __init__(self, node_type: str, label: str, icon: str, data: dict = None):
        super().__init__()
        self.node_type  = node_type
        self.label      = label
        self.icon       = icon
        self.data       = data or {}
        # children: None = not yet asked, Gio.ListStore = loaded/loading
        self._children_store: Optional[Gio.ListStore] = None
        self._loading = False

    def get_config_id(self) -> Optional[str]:
        return self.data.get('config_id')

    def get_schema(self) -> Optional[str]:
        return self.data.get('schema')

    def get_table(self) -> Optional[str]:
        return self.data.get('table')

    def is_expandable(self) -> bool:
        return self.node_type in (
            self.NODE_CONNECTION, self.NODE_SCHEMA,
            self.NODE_GROUP, self.NODE_TABLE,
        )

    def children_store(self) -> Optional[Gio.ListStore]:
        return self._children_store

    def set_children_store(self, store: Gio.ListStore):
        self._children_store = store


# ── Sidebar widget ────────────────────────────────────────────────────────

class SidebarWidget(Gtk.Box):
    def __init__(self, window: 'ReliquaryWindow', search_toggle: Gtk.ToggleButton = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._root_store = Gio.ListStore(item_type=TreeNode)
        self._connection_nodes: dict[str, TreeNode] = {}
        self._search_toggle = search_toggle

        self._build_ui()

    # ── Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Search bar (revealed by the toggle in the sidebar header bar)
        self._search_bar = Gtk.SearchBar(show_close_button=False)
        self._search_entry = Gtk.SearchEntry(placeholder_text='Filter…', hexpand=True)
        self._search_entry.connect('search-changed', self._on_search_changed)
        if self._search_toggle:
            self._search_entry.connect(
                'stop-search', lambda *_: self._search_toggle.set_active(False)
            )
        self._search_bar.set_child(self._search_entry)
        self._search_bar.set_key_capture_widget(self._list_view if hasattr(self, '_list_view') else None)
        if self._search_toggle:
            self._search_toggle.bind_property(
                'active', self._search_bar, 'search-mode-enabled',
                GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
            )
            self._search_toggle.connect('toggled', self._on_search_toggled)
        self.append(self._search_bar)

        # Scrolled tree
        scroll = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        self.append(scroll)

        # Tree model
        self._tree_model = Gtk.TreeListModel.new(
            root=self._root_store,
            passthrough=False,
            autoexpand=False,
            create_func=self._create_child_model,
            user_data=None,
        )

        self._filter_model = Gtk.FilterListModel(model=self._tree_model)
        self._selection = Gtk.SingleSelection(model=self._filter_model)

        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._on_item_setup)
        factory.connect('bind', self._on_item_bind)
        factory.connect('unbind', self._on_item_unbind)

        self._list_view = Gtk.ListView(
            model=self._selection,
            factory=factory,
            single_click_activate=False,
        )
        self._list_view.add_css_class('navigation-sidebar')
        self._list_view.connect('activate', self._on_activate)

        scroll.set_child(self._list_view)

    # ── Tree model creation function ───────────────────────────────────────

    def _create_child_model(self, item: TreeNode, _data) -> Optional[Gio.ListStore]:
        if not item.is_expandable():
            return None

        if item.children_store() is not None:
            return item.children_store()

        store = Gio.ListStore(item_type=TreeNode)
        item.set_children_store(store)

        node_type = item.node_type

        if node_type == TreeNode.NODE_CONNECTION:
            config_id = item.get_config_id()
            db = self._window.get_connection(config_id)
            if db and db.is_connected:
                self._load_schemas_async(item, store, db, config_id)
            else:
                # Not yet connected; prompt will open on activate
                pass

        elif node_type == TreeNode.NODE_SCHEMA:
            config_id = item.get_config_id()
            schema = item.get_schema()
            db = self._window.get_connection(config_id)
            if db and db.is_connected:
                self._load_tables_schema_async(item, store, db, config_id, schema)

        elif node_type == TreeNode.NODE_GROUP:
            # Children were added when the group was created
            pass

        elif node_type == TreeNode.NODE_TABLE:
            config_id = item.get_config_id()
            table = item.get_table()
            schema = item.get_schema()
            db = self._window.get_connection(config_id)
            if db and db.is_connected:
                self._load_columns_async(store, db, table, schema)

        return store

    # ── Async loaders ──────────────────────────────────────────────────────

    def _load_schemas_async(self, conn_node, store, db, config_id):
        def run():
            from .database.introspect import get_schemas, get_tables
            try:
                schemas = get_schemas(db._engine)
                if schemas:
                    def on_done(schemas=schemas):
                        for schema in schemas:
                            node = TreeNode(
                                TreeNode.NODE_SCHEMA,
                                schema,
                                'folder-symbolic',
                                {'config_id': config_id, 'schema': schema},
                            )
                            store.append(node)
                        return False
                    GLib.idle_add(on_done)
                else:
                    # SQLite or DB with no separate schemas — load tables directly
                    tables = get_tables(db._engine)
                    def on_done(tables=tables):
                        _populate_table_group(store, tables, config_id, None)
                        return False
                    GLib.idle_add(on_done)
            except Exception as e:
                GLib.idle_add(lambda: None)
        threading.Thread(target=run, daemon=True).start()

    def _load_tables_schema_async(self, schema_node, store, db, config_id, schema):
        def run():
            from .database.introspect import get_tables
            try:
                tables = get_tables(db._engine, schema)
                def on_done(tables=tables):
                    _populate_table_group(store, tables, config_id, schema)
                    return False
                GLib.idle_add(on_done)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _load_columns_async(self, store, db, table, schema):
        def run():
            from .database.introspect import get_columns
            try:
                cols = get_columns(db._engine, table, schema)
                def on_done(cols=cols):
                    for col in cols:
                        nullable_mark = '?' if col['nullable'] else ''
                        label = f"{col['name']}  {col['type']}{nullable_mark}"
                        node = TreeNode(
                            TreeNode.NODE_COLUMN,
                            label,
                            'input-dialpad-symbolic',
                            {},
                        )
                        store.append(node)
                    return False
                GLib.idle_add(on_done)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    # ── Item factory ───────────────────────────────────────────────────────

    def _on_item_setup(self, factory, list_item):
        expander = Gtk.TreeExpander()
        expander.add_css_class('sidebar-row-expander')

        row_box = Gtk.Box(spacing=8, margin_top=2, margin_bottom=2)

        spinner = Gtk.Spinner()
        spinner.set_visible(False)

        icon = Gtk.Image()
        icon.set_pixel_size(16)

        label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)

        status_icon = Gtk.Image()
        status_icon.set_pixel_size(10)
        status_icon.set_visible(False)

        row_box.append(spinner)
        row_box.append(icon)
        row_box.append(label)
        row_box.append(status_icon)

        expander.set_child(row_box)
        list_item.set_child(expander)

        # Right-click / long-press to show context menu
        gesture = Gtk.GestureClick(button=3)
        gesture.connect('pressed', self._on_row_right_click)
        expander.add_controller(gesture)

    def _on_item_bind(self, factory, list_item):
        tree_row: Gtk.TreeListRow = list_item.get_item()
        node: TreeNode = tree_row.get_item()

        expander: Gtk.TreeExpander = list_item.get_child()
        expander.set_list_row(tree_row)

        row_box: Gtk.Box = expander.get_child()
        children = list(row_box)
        spinner: Gtk.Spinner = children[0]
        icon_widget: Gtk.Image = children[1]
        label_widget: Gtk.Label = children[2]
        status_icon: Gtk.Image = children[3]

        icon_widget.set_from_icon_name(node.icon)
        label_widget.set_label(node.label)

        if node.node_type == TreeNode.NODE_CONNECTION:
            db = self._window.get_connection(node.get_config_id())
            if db and db.is_connected:
                status_icon.set_from_icon_name('emblem-ok-symbolic')
                status_icon.set_visible(True)
                label_widget.add_css_class('bold')
            else:
                status_icon.set_visible(False)
                label_widget.remove_css_class('bold')
        else:
            status_icon.set_visible(False)

        if node.node_type == TreeNode.NODE_COLUMN:
            label_widget.add_css_class('dim-label')
            label_widget.set_use_markup(False)

        # Store node on expander so the right-click handler can retrieve it
        expander._sidebar_node = node

    def _on_item_unbind(self, factory, list_item):
        expander: Gtk.TreeExpander = list_item.get_child()
        expander.set_list_row(None)
        expander._sidebar_node = None

    # ── Activation ────────────────────────────────────────────────────────

    def _on_activate(self, list_view, position):
        tree_row: Gtk.TreeListRow = self._selection.get_selected_item()
        if not tree_row:
            return
        node: TreeNode = tree_row.get_item()
        config_id = node.get_config_id()

        if node.node_type == TreeNode.NODE_CONNECTION:
            cfg = self._window.manager.get(config_id)
            if not cfg:
                return
            db = self._window.get_connection(config_id)
            if db and db.is_connected:
                self._window.open_query_editor(cfg)
            else:
                self._window.connect_to(cfg)

        elif node.node_type == TreeNode.NODE_TABLE:
            cfg = self._window.manager.get(config_id)
            if cfg:
                self._window.open_table_browser(
                    cfg, node.get_table(), node.get_schema()
                )

        elif node.node_type == TreeNode.NODE_VIEW:
            cfg = self._window.manager.get(config_id)
            if cfg:
                self._window.open_table_browser(
                    cfg, node.get_table(), node.get_schema()
                )

        elif node.node_type == TreeNode.NODE_SCHEMA:
            cfg = self._window.manager.get(config_id)
            if cfg:
                self._window.open_query_editor(cfg, node.get_schema())

    # ── Right-click context menu ──────────────────────────────────────────

    def _on_row_right_click(self, gesture, n_press, x, y):
        expander = gesture.get_widget()
        node: TreeNode = getattr(expander, '_sidebar_node', None)
        if node is None:
            return

        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        if node.node_type == TreeNode.NODE_CONNECTION:
            self._show_connection_menu(node, expander, x, y)
        elif node.node_type in (TreeNode.NODE_TABLE, TreeNode.NODE_VIEW):
            self._show_table_menu(node, expander, x, y)

    def _show_connection_menu(self, node: TreeNode, anchor: Gtk.Widget, x: float, y: float):
        config_id = node.get_config_id()
        cfg = self._window.manager.get(config_id)
        if not cfg:
            return

        db = self._window.get_connection(config_id)
        is_connected = db and db.is_connected

        popover = Gtk.Popover(has_arrow=False, autohide=True)
        popover.set_parent(anchor)
        popover.set_pointing_to(_rect(x, y))

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_top=4, margin_bottom=4,
            margin_start=4, margin_end=4,
            spacing=2,
        )
        popover.set_child(box)

        if is_connected:
            box.append(_menu_item(
                'New Query', 'accessories-text-editor-symbolic',
                lambda: (popover.popdown(), self._window.open_query_editor(cfg)),
            ))
            box.append(_menu_item(
                'Create Table…', 'list-add-symbolic',
                lambda: (popover.popdown(), self._show_create_table_dialog(cfg, db, None)),
            ))
            if cfg.driver in ('postgresql', 'mysql'):
                box.append(_menu_item(
                    'Running Queries…', 'system-run-symbolic',
                    lambda: (popover.popdown(), self._window.open_process_panel(cfg)),
                ))
                box.append(_menu_item(
                    'Create Database…', 'folder-new-symbolic',
                    lambda: (popover.popdown(), self._show_create_database_dialog(cfg, db)),
                ))
            box.append(_menu_separator())
            box.append(_menu_item(
                'Disconnect', 'network-offline-symbolic',
                lambda: (popover.popdown(), self._window.disconnect_from(config_id)),
            ))
        else:
            box.append(_menu_item(
                'Connect', 'network-transmit-receive-symbolic',
                lambda: (popover.popdown(), self._window.connect_to(cfg)),
            ))

        box.append(_menu_separator())
        box.append(_menu_item(
            'Edit Connection…', 'document-edit-symbolic',
            lambda: (popover.popdown(), self._window.open_new_connection_dialog(cfg)),
        ))
        box.append(_menu_item(
            'Remove Connection', 'user-trash-symbolic',
            lambda: (popover.popdown(), self._confirm_remove(cfg)),
            destructive=True,
        ))

        popover.popup()

    def _show_table_menu(self, node: TreeNode, anchor: Gtk.Widget, x: float, y: float):
        config_id = node.get_config_id()
        cfg = self._window.manager.get(config_id)
        if not cfg:
            return
        db     = self._window.get_connection(config_id)
        table  = node.get_table()
        schema = node.get_schema()
        qualified = f'"{schema}"."{table}"' if schema else f'"{table}"'

        popover = Gtk.Popover(has_arrow=False, autohide=True)
        popover.set_parent(anchor)
        popover.set_pointing_to(_rect(x, y))

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_top=4, margin_bottom=4,
            margin_start=4, margin_end=4,
            spacing=2,
        )
        popover.set_child(box)

        box.append(_menu_item(
            'Browse Data', 'x-office-spreadsheet-symbolic',
            lambda: (popover.popdown(), self._window.open_table_browser(cfg, table, schema)),
        ))
        box.append(_menu_item(
            'View Structure', 'dialog-information-symbolic',
            lambda: (popover.popdown(), self._window.open_structure_panel(cfg, table, schema)),
        ))
        box.append(_menu_item(
            'Open in Query Editor', 'accessories-text-editor-symbolic',
            lambda t=table, s=schema, q=qualified: (
                popover.popdown(),
                self._open_table_in_editor(cfg, t, s, q),
            ),
        ))
        box.append(_menu_separator())
        box.append(_menu_item(
            'Copy Name', 'edit-copy-symbolic',
            lambda q=qualified: (popover.popdown(), _copy_to_clipboard(anchor, q)),
        ))
        box.append(_menu_separator())
        kind = 'view' if node.node_type == TreeNode.NODE_VIEW else 'table'
        box.append(_menu_item(
            f'Drop {kind.capitalize()}…', 'edit-delete-symbolic',
            lambda t=table, s=schema, k=kind: (
                popover.popdown(),
                self._confirm_drop(cfg, db, t, s, k),
            ),
            destructive=True,
        ))

        popover.popup()

    def _open_table_in_editor(self, cfg, table, schema, qualified):
        self._window.open_query_editor(cfg, schema)
        def inject():
            from .editor_panel import EditorPanel
            tab_view = self._window._tab_view
            page = tab_view.get_selected_page()
            if page:
                child = page.get_child()
                if isinstance(child, EditorPanel):
                    child._source_buffer.set_text(
                        f'SELECT *\nFROM {qualified}\nLIMIT 500;'
                    )
            return False
        GLib.idle_add(inject)

    def _show_create_table_dialog(self, cfg, db, schema):
        from .create_table_dialog import CreateTableDialog
        def on_created():
            self._refresh_connection_node(cfg.id)
        dialog = CreateTableDialog(
            window=self._window,
            db=db,
            schema=schema,
            on_created=on_created,
        )
        dialog.present(self._window)

    def _confirm_drop(self, cfg, db, table: str, schema, kind: str):
        qualified = f'"{schema}"."{table}"' if schema else f'"{table}"'
        dialog = Adw.AlertDialog(
            heading=f'Drop {kind.capitalize()}?',
            body=f'{qualified} and all its data will be permanently deleted.',
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('drop', f'Drop {kind.capitalize()}')
        dialog.set_response_appearance('drop', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')

        def on_response(d, response):
            if response == 'drop':
                self._execute_drop(cfg, db, qualified, kind)

        dialog.connect('response', on_response)
        dialog.present(self._window)

    def _execute_drop(self, cfg, db, qualified: str, kind: str):
        def run():
            try:
                from sqlalchemy import text
                with db._engine.connect() as conn:
                    conn.execute(text(f'DROP {kind.upper()} {qualified}'))
                    conn.commit()
                GLib.idle_add(lambda: (
                    self._refresh_connection_node(cfg.id),
                    self._window.toast(f'Dropped {qualified}'),
                ))
            except Exception as e:
                GLib.idle_add(lambda: self._window.toast_error(f'Drop failed: {e}'))

        threading.Thread(target=run, daemon=True).start()

    def _refresh_connection_node(self, config_id: str):
        node = self._connection_nodes.get(config_id)
        if not node:
            return
        found, pos = self._root_store.find(node)
        if found:
            node.set_children_store(None)
            self._root_store.remove(pos)
            self._root_store.insert(pos, node)

    def _show_create_database_dialog(self, cfg, db):
        dialog = Adw.Dialog(title='Create Database')
        dialog.set_content_width(360)
        dialog.set_content_height(200)

        toolbar_view = Adw.ToolbarView()
        dialog.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.add_css_class('flat')
        toolbar_view.add_top_bar(header)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda *_: dialog.close())
        header.pack_start(cancel_btn)

        create_btn = Gtk.Button(label='Create')
        create_btn.add_css_class('suggested-action')
        header.pack_end(create_btn)

        clamp = Adw.Clamp(maximum_size=320, margin_top=16, margin_bottom=16,
                          margin_start=12, margin_end=12)
        toolbar_view.set_content(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        clamp.set_child(box)

        group = Adw.PreferencesGroup()
        box.append(group)

        name_row = Adw.EntryRow(title='Database name')
        group.add(name_row)

        status = Gtk.Label(label='', xalign=0)
        status.add_css_class('dim-label')
        box.append(status)

        def on_create(*_):
            db_name = name_row.get_text().strip()
            if not db_name:
                status.set_label('⚠ Name is required')
                return

            create_btn.set_sensitive(False)
            status.set_label('Creating…')

            def run():
                try:
                    from sqlalchemy import text
                    dialect = db._engine.dialect.name
                    if dialect == 'postgresql':
                        with db._engine.connect().execution_options(
                            isolation_level='AUTOCOMMIT'
                        ) as conn:
                            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                    elif dialect in ('mysql', 'mariadb'):
                        with db._engine.connect() as conn:
                            conn.execute(text(f'CREATE DATABASE `{db_name}`'))
                            conn.commit()

                    GLib.idle_add(lambda: (
                        self._window.toast(f'Database "{db_name}" created'),
                        dialog.close(),
                    ) and False)
                except Exception as e:
                    msg = str(e)[:100]
                    GLib.idle_add(lambda m=msg: (
                        status.set_label(f'✗ {m}'),
                        create_btn.set_sensitive(True),
                    ) and False)

            threading.Thread(target=run, daemon=True).start()

        create_btn.connect('clicked', on_create)
        name_row.connect('entry-activated', on_create)

        dialog.present(self._window)

    def _confirm_remove(self, cfg):
        dialog = Adw.AlertDialog(
            heading='Remove Connection?',
            body=f'"{cfg.name}" will be removed. Active tabs for this connection will still work until closed.',
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('remove', 'Remove')
        dialog.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')

        def on_response(d, response):
            if response == 'remove':
                self._window.manager.remove(cfg.id)
                self._window._on_connection_deleted(cfg.id)

        dialog.connect('response', on_response)
        dialog.present(self._window)

    # ── Search / filter ───────────────────────────────────────────────────

    def _on_search_toggled(self, btn):
        if not btn.get_active():
            self._search_entry.set_text('')
            self._filter_model.set_filter(None)

    def _on_search_changed(self, entry):
        text = entry.get_text().strip().lower()
        if not text:
            self._filter_model.set_filter(None)
            return

        def match(tree_row, _data):
            if not isinstance(tree_row, Gtk.TreeListRow):
                return True
            node = tree_row.get_item()
            if node is None:
                return True
            # Always show connection-level rows that match, plus all their children
            if node.node_type == TreeNode.NODE_CONNECTION:
                return text in node.label.lower()
            # For deeper nodes, show if the label matches or if parent connection matches
            return text in node.label.lower()

        self._filter_model.set_filter(
            Gtk.CustomFilter.new(match, None)
        )

    # ── Public interface ──────────────────────────────────────────────────

    def populate(self, configs, connections: dict):
        self._root_store.remove_all()
        self._connection_nodes.clear()

        for cfg in configs:
            node = TreeNode(
                TreeNode.NODE_CONNECTION,
                cfg.name,
                _driver_icon(cfg.driver),
                {'config_id': cfg.id},
            )
            self._root_store.append(node)
            self._connection_nodes[cfg.id] = node

    def set_connecting(self, config_id: str, value: bool):
        # Refresh the row (spin indicator) — simple approach: force redraw
        pass

    def set_connected(self, config_id: str, value: bool):
        node = self._connection_nodes.get(config_id)
        if node:
            # Reset children so schema reloads on next expand
            node.set_children_store(None)
        # Force list view to re-bind by invalidating
        self._list_view.queue_draw()

    def load_schema(self, config_id: str, db: 'DatabaseConnection'):
        node = self._connection_nodes.get(config_id)
        if node:
            # Reset so the child model function reloads
            node.set_children_store(None)
            # If the node is currently expanded, collapse and re-expand
            # The user will see the schema when they expand


# ── Helpers ───────────────────────────────────────────────────────────────

def _populate_table_group(store: Gio.ListStore, tables: list[dict], config_id: str, schema):
    tables_only = [t for t in tables if t['kind'] == 'table']
    views_only  = [t for t in tables if t['kind'] == 'view']

    for item in tables_only:
        node = TreeNode(
            TreeNode.NODE_TABLE,
            item['name'],
            'x-office-spreadsheet-symbolic',
            {'config_id': config_id, 'schema': schema, 'table': item['name']},
        )
        store.append(node)

    for item in views_only:
        node = TreeNode(
            TreeNode.NODE_VIEW,
            item['name'],
            'view-list-symbolic',
            {'config_id': config_id, 'schema': schema, 'table': item['name']},
        )
        store.append(node)


def _driver_icon(driver: str) -> str:
    return {
        'sqlite':     'drive-harddisk-symbolic',
        'postgresql': 'network-server-symbolic',
        'mysql':      'network-server-symbolic',
    }.get(driver, 'network-server-symbolic')


# ── Context menu helpers ──────────────────────────────────────────────────

def _menu_item(label: str, icon_name: str, callback, destructive: bool = False) -> Gtk.Button:
    btn = Gtk.Button(has_frame=False)
    btn.add_css_class('flat')
    if destructive:
        btn.add_css_class('destructive-action')

    box = Gtk.Box(spacing=10, margin_start=4, margin_end=8)
    icon = Gtk.Image(icon_name=icon_name, pixel_size=16)
    lbl  = Gtk.Label(label=label, xalign=0, hexpand=True)
    box.append(icon)
    box.append(lbl)
    btn.set_child(box)
    btn.connect('clicked', lambda *_: callback())
    return btn


def _menu_separator() -> Gtk.Separator:
    sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    sep.set_margin_top(4)
    sep.set_margin_bottom(4)
    return sep


def _rect(x: float, y: float) -> Gdk.Rectangle:
    r = Gdk.Rectangle()
    r.x, r.y, r.width, r.height = int(x), int(y), 1, 1
    return r


def _copy_to_clipboard(widget: Gtk.Widget, text: str):
    display = widget.get_display()
    clipboard = display.get_clipboard()
    clipboard.set(text)
