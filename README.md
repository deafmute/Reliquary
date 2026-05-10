Reliquary

A native GNOME database client for SQLite, PostgreSQL, and MySQL/MariaDB — built with GTK4 and libadwaita.

!GNOME
!Python
!License

Features

Connections
- Connect to SQLite, PostgreSQL, and MySQL/MariaDB
- Create a new local SQLite database or a new database on a remote server
- Saved connections persist across sessions
- Collapsible sidebar showing the connection tree with schemas, tables, views, and columns
- Built-in sample databases (Northwind Traders, Music Store) to explore immediately

Query Editor
- Syntax-highlighted SQL editor powered by GtkSourceView 5
- Run queries with Ctrl+Enter or F5; run the current selection only
- Guard against accidental destructive statements (DELETE/UPDATE without WHERE, DROP, TRUNCATE)
- Auto-limit SELECT results to keep the UI responsive
- Find & Replace with match count and wrap-around (Ctrl+F)
- Format SQL — re-indents and uppercases keywords via sqlparse
- EXPLAIN / EXPLAIN ANALYZE — shows the query plan in the results panel
- Open SQL file directly into the editor (Ctrl+O)
- Export results to CSV
- Query history — last 200 queries per connection, searchable, click-to-restore
- Snippets — save and recall frequently used queries
- Auto-save — editor content is restored automatically on next launch

Table Browser
- Browse table data with server-side sorting and filtering (WHERE clause)
- Add, edit, and delete rows with a form-based dialog
- Primary-key-aware UPDATE/DELETE — safe even on tables without a unique visible column
- Pagination (500 rows per page)
- CSV import with column mapping, delimiter auto-detection, header row toggle, and error skipping
- Open in Query Editor with a pre-filled SELECT statement

Schema Tools
- Structure view — column names, types, nullability, defaults, primary keys, and indexes
- Create Table wizard — add columns with type, PK, NOT NULL, and default; live DDL preview
- Drop Table/View with confirmation
- Running Queries panel (PostgreSQL pg_stat_activity / MySQL PROCESSLIST) with kill support

GNOME Integration
- Follows the Adwaita design language — native split-view layout, header bar controls, tab bar
- Context-sensitive primary actions in the header bar (Run for the editor, Add/Edit/Delete for the table browser)
- Respects the system light/dark preference; override available in Preferences
- Desktop entry and app icon registered in the icon theme

Screenshots

> Add screenshots here once the app is running on your system.

Requirements

| Dependency | Version |
|---|---|
| Python | ≥ 3.11 |
| GTK4 | ≥ 4.12 |
| libadwaita | ≥ 1.4 |
| GtkSourceView | 5 |
| PyGObject | ≥ 3.44 |
| SQLAlchemy | ≥ 2.0 |
| psycopg2 | ≥ 2.9 (PostgreSQL) |
| PyMySQL | ≥ 1.0 (MySQL/MariaDB) |

Installation

AppImage (any Linux distro)

The AppImage bundles the Python database drivers. GTK4, libadwaita, GtkSourceView 5, and Python 3 must be installed on the host.

```bash
chmod +x Reliquary-0.1.0-x86_64.AppImage
./Reliquary-0.1.0-x86_64.AppImage
```

RPM (Fedora / RHEL / openSUSE)

```bash
sudo dnf install reliquary-0.1.0-1.fc44.noarch.rpm
```

The package declares all GTK and Python dependencies so dnf will pull them in automatically.

DEB (Debian / Ubuntu / Linux Mint)

```bash
sudo apt install ./reliquary_0.1.0_all.deb
```

Required system packages installed automatically:
python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gtksource-5 python3-sqlalchemy python3-psycopg2 python3-pymysql

Run from source

```bash
# Clone and install Python dependencies
git clone https://github.com/deafmute/reliquary.git
cd reliquary
pip install sqlalchemy psycopg2-binary pymysql

# Install GTK stack (Fedora example)
sudo dnf install python3-gobject gtk4 libadwaita gtksourceview5

# Run
python3 main.py
```

Building packages

All three distribution packages can be built from source with a single script:

```bash
bash packaging/build.sh
```

Output is written to dist/. Requirements: rpmbuild, dpkg-deb, and an internet connection to download appimagetool on the first run. An SVG→PNG converter (rsvg-convert, inkscape, or convert) is needed for the AppImage icon.

Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Run query | Ctrl+Enter or F5 |
| Find & Replace | Ctrl+F |
| Open SQL file | Ctrl+O |
| New connection | — (menu or sidebar button) |
| Keyboard shortcuts | Ctrl+F1 |

Configuration

Settings are stored at ~/.config/reliquary/settings.json and can be changed in Preferences (main menu → Preferences):

| Setting | Default |
|---|---|
| Font size | 11 pt |
| Tab width | 4 spaces |
| Line numbers | On |
| Highlight current line | On |
| Word wrap | Off |
| Auto-limit SELECT | 1000 rows |
| Confirm destructive statements | On |
| Save query history | On (last 200) |
| Color scheme | Follow system |
| Show row numbers | On |

Connection configurations are stored at ~/.config/reliquary/connections.json.
Query history is stored per connection at ~/.config/reliquary/history/.
Snippets are stored at ~/.config/reliquary/snippets.json.
Auto-saved editor content is stored at ~/.config/reliquary/autosave/.

Project structure

```
reliquary/
  application.py        — Adw.Application, actions, icon registration
  window.py             — Main window layout (split view, tab bar)
  sidebar.py            — Connection tree, context menus
  editor_panel.py       — SQL editor, results, history, snippets
  table_panel.py        — Table data browser with CRUD
  structure_panel.py    — Table structure viewer
  process_panel.py      — Running queries / process list
  connection_dialog.py  — New/edit connection dialog
  create_table_dialog.py — Create table wizard
  row_edit_dialog.py    — Add / edit row dialog
  import_dialog.py      — CSV import dialog
  shortcuts_dialog.py   — Keyboard shortcuts reference
  snippets.py           — Snippet store and panel
  history.py            — Query history store and panel
  export.py             — Results CSV export
  settings.py           — Preferences storage and dialog
  samples.py            — Built-in sample database generator
  database/
    manager.py          — Connection config persistence
    connection.py       — Database connection + async query execution
    introspect.py       — Schema introspection via SQLAlchemy
packaging/
  build.sh              — Builds RPM, DEB, and AppImage
  rpm/reliquary.spec    — RPM spec
  appimage/AppRun       — AppImage launcher
  io.github.reliquary.desktop
data/
  icons/hicolor/scalable/apps/io.github.reliquary.svg
```

License

Reliquary is released under the GNU General Public License v3.0. See LICENSE for details.
