import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GtkSource', '5')
import os
from gi.repository import Gtk, Adw, Gio, GLib, GtkSource, Gdk

from .database.manager import ConnectionManager
from .window import ReliquaryWindow
from .settings import apply_saved_color_scheme

_CSS_PATH = os.path.join(os.path.dirname(__file__), 'style.css')
_ICON_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'icons')


class ReliquaryApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id='io.github.reliquary',
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        GtkSource.init()
        self.manager = ConnectionManager()

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._register_icons()
        self._load_css()
        self._setup_actions()
        apply_saved_color_scheme()

    def _register_icons(self):
        icon_dir = os.path.realpath(_ICON_DIR)
        if os.path.isdir(icon_dir):
            Gtk.IconTheme.get_for_display(
                Gdk.Display.get_default()
            ).add_search_path(icon_dir)

    def _load_css(self):
        css = Gtk.CssProvider()
        css.load_from_path(_CSS_PATH)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def do_activate(self):
        win = self.get_active_window()
        if not win:
            win = ReliquaryWindow(application=self, manager=self.manager)
        win.present()

    def _setup_actions(self):
        quit_action = Gio.SimpleAction.new('quit', None)
        quit_action.connect('activate', lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action('app.quit', ['<Primary>q'])

        new_conn_action = Gio.SimpleAction.new('new-connection', None)
        new_conn_action.connect('activate', self._on_new_connection)
        self.add_action(new_conn_action)
        self.set_accels_for_action('app.new-connection', ['<Primary>n'])

        prefs_action = Gio.SimpleAction.new('preferences', None)
        prefs_action.connect('activate', self._on_preferences)
        self.add_action(prefs_action)
        self.set_accels_for_action('app.preferences', ['<Primary>comma'])

        shortcuts_action = Gio.SimpleAction.new('shortcuts', None)
        shortcuts_action.connect('activate', self._on_shortcuts)
        self.add_action(shortcuts_action)
        self.set_accels_for_action('app.shortcuts', ['<Primary>F1'])

    def _on_new_connection(self, *_):
        win = self.get_active_window()
        if win:
            win.open_new_connection_dialog()

    def _on_preferences(self, *_):
        from .settings import PreferencesWindow
        win = self.get_active_window()
        if win:
            PreferencesWindow(win)

    def _on_shortcuts(self, *_):
        from .shortcuts_dialog import show_shortcuts_dialog
        win = self.get_active_window()
        if win:
            show_shortcuts_dialog(win)
