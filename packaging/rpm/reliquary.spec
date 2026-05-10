%global appid  io.github.reliquary
%global srcname reliquary

Name:           %{srcname}
Version:        0.1.0
Release:        1%{?dist}
Summary:        A GNOME database client for SQLite, PostgreSQL and MySQL

License:        GPL-3.0-or-later
URL:            https://github.com/jjahoda/reliquary
BuildArch:      noarch

Source0:        %{srcname}-%{version}.tar.gz

BuildRequires:  python3

Requires:       python3 >= 3.11
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       gtksourceview5
Requires:       python3-sqlalchemy >= 2.0
Requires:       python3-psycopg2
Requires:       python3-PyMySQL

%description
Reliquary is a native GNOME database client supporting SQLite,
PostgreSQL, and MySQL/MariaDB.

It features a sidebar for browsing schemas and tables, a SQL query
editor with syntax highlighting and history, a table data browser
with inline editing, CSV import, EXPLAIN viewer, and snippet support.

%prep
%autosetup

%build
# pure Python — nothing to compile

%install
# Python package
install -dm755 %{buildroot}%{python3_sitelib}
cp -rp reliquary %{buildroot}%{python3_sitelib}/

# Entry point wrapper
mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/%{srcname} << 'LAUNCHER'
#!/usr/bin/env python3
import sys
from reliquary.application import ReliquaryApp
app = ReliquaryApp()
sys.exit(app.run(sys.argv))
LAUNCHER
chmod 755 %{buildroot}%{_bindir}/%{srcname}

# Icon
install -Dm644 data/icons/hicolor/scalable/apps/%{appid}.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg

# Desktop file
install -Dm644 packaging/%{appid}.desktop \
    %{buildroot}%{_datadir}/applications/%{appid}.desktop

%post
gtk-update-icon-cache -f %{_datadir}/icons/hicolor &>/dev/null || :
update-desktop-database -q %{_datadir}/applications &>/dev/null || :

%postun
gtk-update-icon-cache -f %{_datadir}/icons/hicolor &>/dev/null || :
update-desktop-database -q %{_datadir}/applications &>/dev/null || :

%files
%{python3_sitelib}/%{srcname}/
%{_bindir}/%{srcname}
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
%{_datadir}/applications/%{appid}.desktop
