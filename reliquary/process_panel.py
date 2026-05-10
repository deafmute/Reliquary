"""Running queries / process list panel for PostgreSQL and MySQL."""
import threading
from typing import TYPE_CHECKING

from gi.repository import Gtk, Adw, GLib, Pango

if TYPE_CHECKING:
    from .window import ReliquaryWindow
    from .database.manager import ConnectionConfig
    from .database.connection import DatabaseConnection


class ProcessPanel(Gtk.Box):
    """Shows active queries/connections for PostgreSQL or MySQL."""

    def __init__(
        self,
        window: 'ReliquaryWindow',
        config: 'ConnectionConfig',
        db: 'DatabaseConnection',
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._config = config
        self._db = db
        self._dialect = db._engine.dialect.name

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        toolbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=8, margin_end=8,
            margin_top=6, margin_bottom=6,
        )
        toolbar.add_css_class('toolbar')

        lbl = Gtk.Label(label='Running Queries', xalign=0, hexpand=True)
        lbl.add_css_class('heading')
        toolbar.append(lbl)

        self._spinner = Gtk.Spinner()
        toolbar.append(self._spinner)

        refresh_btn = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Refresh')
        refresh_btn.add_css_class('flat')
        refresh_btn.connect('clicked', lambda *_: self._refresh())
        toolbar.append(refresh_btn)

        self._kill_btn = Gtk.Button(
            icon_name='process-stop-symbolic',
            tooltip_text='Terminate selected query',
            sensitive=False,
        )
        self._kill_btn.add_css_class('flat')
        self._kill_btn.add_css_class('destructive-action')
        self._kill_btn.connect('clicked', self._on_kill)
        toolbar.append(self._kill_btn)

        self.append(toolbar)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._scroll = Gtk.ScrolledWindow(vexpand=True)
        self.append(self._scroll)

        self._store = Gtk.ListStore(str, str, str, str, str)  # pid, user, db, state, query
        self._tree = Gtk.TreeView(model=self._store, vexpand=True)
        self._tree.set_headers_visible(True)

        headers = ['PID', 'User', 'Database', 'State', 'Query']
        for i, h in enumerate(headers):
            renderer = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(h, renderer, text=i)
            col.set_resizable(True)
            col.set_min_width(60)
            if i == 4:
                col.set_expand(True)
            self._tree.append_column(col)

        self._tree.get_selection().connect('changed', self._on_selection_changed)
        self._scroll.set_child(self._tree)

    def _refresh(self):
        self._spinner.set_spinning(True)

        def run():
            try:
                rows = self._fetch_processes()
                GLib.idle_add(lambda: self._populate(rows))
            except Exception as e:
                GLib.idle_add(lambda: (
                    self._spinner.set_spinning(False),
                    self._window.toast_error(f'Could not fetch processes: {e}'),
                ))

        threading.Thread(target=run, daemon=True).start()

    def _fetch_processes(self) -> list[tuple]:
        from sqlalchemy import text
        engine = self._db._engine
        dialect = self._dialect

        with engine.connect() as conn:
            if dialect == 'postgresql':
                result = conn.execute(text("""
                    SELECT pid::text, usename, datname, state,
                           LEFT(query, 200)
                    FROM pg_stat_activity
                    WHERE pid <> pg_backend_pid()
                      AND query <> '<insufficient privilege>'
                    ORDER BY query_start DESC NULLS LAST
                """))
            elif dialect in ('mysql', 'mariadb'):
                result = conn.execute(text("""
                    SELECT ID, USER, DB, COMMAND,
                           LEFT(INFO, 200)
                    FROM information_schema.PROCESSLIST
                    WHERE ID <> CONNECTION_ID()
                    ORDER BY TIME DESC
                """))
            else:
                return []
            return result.fetchall()

    def _populate(self, rows: list):
        self._spinner.set_spinning(False)
        self._store.clear()
        for row in rows:
            self._store.append([str(v) if v is not None else '' for v in row])

    def _on_selection_changed(self, selection):
        model, it = selection.get_selected()
        self._kill_btn.set_sensitive(it is not None)

    def _on_kill(self, *_):
        selection = self._tree.get_selection()
        model, it = selection.get_selected()
        if not it:
            return
        pid = model.get_value(it, 0)

        dialog = Adw.AlertDialog(
            heading='Terminate query?',
            body=f'Process {pid} will be terminated.',
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('kill', 'Terminate')
        dialog.set_response_appearance('kill', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')

        def on_response(d, response):
            if response == 'kill':
                self._execute_kill(pid)

        dialog.connect('response', on_response)
        dialog.present(self._window)

    def _execute_kill(self, pid: str):
        def run():
            try:
                from sqlalchemy import text
                engine = self._db._engine
                dialect = self._dialect
                with engine.connect() as conn:
                    if dialect == 'postgresql':
                        conn.execute(text(f'SELECT pg_terminate_backend({pid})'))
                    elif dialect in ('mysql', 'mariadb'):
                        conn.execute(text(f'KILL {pid}'))
                    conn.commit()
                GLib.idle_add(lambda: (
                    self._window.toast(f'Process {pid} terminated'),
                    self._refresh(),
                ))
            except Exception as e:
                GLib.idle_add(lambda: self._window.toast_error(f'Kill failed: {e}'))

        threading.Thread(target=run, daemon=True).start()
