"""Keyboard shortcuts reference dialog."""
from gi.repository import Gtk, Adw

SHORTCUTS = [
    ('Query Editor', [
        ('Ctrl+Enter / F5', 'Run query'),
        ('Ctrl+F',          'Find and Replace'),
        ('Ctrl+O',          'Open SQL file'),
        ('Escape',          'Close Find bar'),
    ]),
    ('Application', [
        ('Ctrl+N',  'New connection'),
        ('Ctrl+,',  'Preferences'),
        ('Ctrl+F1', 'Keyboard shortcuts'),
        ('Ctrl+Q',  'Quit'),
    ]),
    ('Table Browser', [
        ('Double-click row', 'Edit row'),
        ('Ctrl+F',           'Filter rows (WHERE clause)'),
    ]),
]


def show_shortcuts_dialog(parent: Gtk.Widget):
    dialog = Adw.Dialog(title='Keyboard Shortcuts')
    dialog.set_content_width(460)
    dialog.set_content_height(500)

    toolbar_view = Adw.ToolbarView()
    dialog.set_child(toolbar_view)

    header = Adw.HeaderBar()
    header.add_css_class('flat')
    toolbar_view.add_top_bar(header)

    close_btn = Gtk.Button(label='Close')
    close_btn.connect('clicked', lambda *_: dialog.close())
    header.pack_end(close_btn)

    scroll = Gtk.ScrolledWindow(
        vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
    )
    toolbar_view.set_content(scroll)

    clamp = Adw.Clamp(maximum_size=400, margin_top=12, margin_bottom=16)
    scroll.set_child(clamp)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
    clamp.set_child(box)

    for section_name, items in SHORTCUTS:
        group = Adw.PreferencesGroup(title=section_name)
        box.append(group)
        for shortcut, description in items:
            row = Adw.ActionRow(title=description)
            lbl = Gtk.Label(label=shortcut)
            lbl.add_css_class('monospace')
            lbl.add_css_class('dim-label')
            row.add_suffix(lbl)
            group.add(row)

    dialog.present(parent)
