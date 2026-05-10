#!/usr/bin/env bash
# build.sh — Build RPM, DEB, and AppImage packages for Reliquary
# Run from the project root:   bash packaging/build.sh
set -euo pipefail

VERSION="0.1.0"
APPID="io.github.reliquary"
APPNAME="reliquary"
DISPLAY_NAME="Reliquary"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKGDIR="$ROOT/packaging"
DISTDIR="$ROOT/dist"
TMPDIR_BASE="$ROOT/build/pkg"

DESKTOP="$PKGDIR/$APPID.desktop"
ICON_SVG="$ROOT/data/icons/hicolor/scalable/apps/$APPID.svg"

banner() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

die() { echo "ERROR: $*" >&2; exit 1; }

mkdir -p "$DISTDIR" "$TMPDIR_BASE"

# ── SVG → PNG helper (for AppImage icon) ─────────────────────────────────
svg_to_png() {
    local src="$1" dst="$2" size="${3:-256}"
    if command -v rsvg-convert &>/dev/null; then
        rsvg-convert -w "$size" -h "$size" "$src" -o "$dst"
    elif command -v inkscape &>/dev/null; then
        inkscape --export-type=png --export-width="$size" \
                 --export-height="$size" -o "$dst" "$src" 2>/dev/null
    elif command -v convert &>/dev/null; then
        convert -background none -resize "${size}x${size}" "$src" "$dst"
    else
        echo "  WARNING: No SVG→PNG converter found (install librsvg2-tools or inkscape)."
        echo "           AppImage icon will be missing."
        return 1
    fi
}

# ════════════════════════════════════════════════════════════════════════
banner "1/3  Building RPM"
# ════════════════════════════════════════════════════════════════════════
command -v rpmbuild &>/dev/null || die "rpmbuild not found. Install rpm-build."

RPMTMP="$TMPDIR_BASE/rpm"
rm -rf "$RPMTMP"
mkdir -p "$RPMTMP"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

# Create source tarball
echo "  Creating source tarball..."
SRCTREE="$RPMTMP/SOURCES/$APPNAME-$VERSION"
mkdir -p "$SRCTREE"
cp -r "$ROOT/reliquary"   "$SRCTREE/"
cp -r "$ROOT/data"        "$SRCTREE/"
cp    "$ROOT/pyproject.toml" "$SRCTREE/"
cp    "$ROOT/main.py"     "$SRCTREE/"
mkdir -p "$SRCTREE/packaging"
cp    "$DESKTOP"          "$SRCTREE/packaging/"
cp -r "$PKGDIR/rpm"       "$SRCTREE/packaging/"
tar -czf "$RPMTMP/SOURCES/$APPNAME-$VERSION.tar.gz" \
    -C "$RPMTMP/SOURCES" "$APPNAME-$VERSION"

# Resolve sitelib for noarch packages (used to patch the %files glob if needed)
PY3_SITELIB="$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"

cp "$PKGDIR/rpm/$APPNAME.spec" "$RPMTMP/SPECS/"

echo "  Running rpmbuild..."
rpmbuild \
    --define "_topdir $RPMTMP" \
    --define "python3_sitelib $PY3_SITELIB" \
    -bb "$RPMTMP/SPECS/$APPNAME.spec" 2>&1 | sed 's/^/    /'

find "$RPMTMP/RPMS" -name "*.rpm" -exec cp {} "$DISTDIR/" \;
RPM_OUT="$(find "$DISTDIR" -name "${APPNAME}-${VERSION}*.rpm" | head -1)"
echo "  ✓ RPM → $RPM_OUT"

# ════════════════════════════════════════════════════════════════════════
banner "2/3  Building DEB"
# ════════════════════════════════════════════════════════════════════════
command -v dpkg-deb &>/dev/null || die "dpkg-deb not found. Install dpkg."

DEBTMP="$TMPDIR_BASE/deb"
DEBPKG="${APPNAME}_${VERSION}_all"
DEBROOT="$DEBTMP/$DEBPKG"
rm -rf "$DEBTMP"
mkdir -p "$DEBROOT"

# Debian uses /usr/lib/python3/dist-packages for arch-independent packages
DEB_SITELIB="usr/lib/python3/dist-packages"

echo "  Copying Python package..."
mkdir -p "$DEBROOT/$DEB_SITELIB"
cp -r "$ROOT/reliquary" "$DEBROOT/$DEB_SITELIB/"

# Entry point wrapper
echo "  Creating launcher..."
mkdir -p "$DEBROOT/usr/bin"
cat > "$DEBROOT/usr/bin/$APPNAME" << 'LAUNCHER'
#!/usr/bin/env python3
import sys
from reliquary.application import ReliquaryApp
app = ReliquaryApp()
sys.exit(app.run(sys.argv))
LAUNCHER
chmod 755 "$DEBROOT/usr/bin/$APPNAME"

# Data files
echo "  Installing data files..."
mkdir -p "$DEBROOT/usr/share/icons/hicolor/scalable/apps"
cp "$ICON_SVG" "$DEBROOT/usr/share/icons/hicolor/scalable/apps/"

mkdir -p "$DEBROOT/usr/share/applications"
cp "$DESKTOP" "$DEBROOT/usr/share/applications/"

# Installed-Size (KB)
INSTALLED_SIZE=$(du -sk "$DEBROOT" | cut -f1)

# DEBIAN/ control files
mkdir -p "$DEBROOT/DEBIAN"

cat > "$DEBROOT/DEBIAN/control" << EOF
Package: $APPNAME
Version: $VERSION
Architecture: all
Maintainer: Joshua Jahoda <deafmute86@gmail.com>
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-gtksource-5, python3-sqlalchemy, python3-psycopg2, python3-pymysql
Section: database
Priority: optional
Homepage: https://github.com/jjahoda/reliquary
Description: A GNOME database client for SQLite, PostgreSQL and MySQL
 Reliquary is a native GNOME database client supporting SQLite,
 PostgreSQL, and MySQL/MariaDB. It features a sidebar for schema
 browsing, SQL query editor with syntax highlighting, table browsing
 and editing, CSV import, and EXPLAIN viewer.
EOF

cat > "$DEBROOT/DEBIAN/postinst" << 'EOF'
#!/bin/sh
set -e
gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database -q /usr/share/applications 2>/dev/null || true
EOF
chmod 755 "$DEBROOT/DEBIAN/postinst"

cat > "$DEBROOT/DEBIAN/postrm" << 'EOF'
#!/bin/sh
set -e
gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database -q /usr/share/applications 2>/dev/null || true
EOF
chmod 755 "$DEBROOT/DEBIAN/postrm"

echo "  Running dpkg-deb..."
dpkg-deb --build --root-owner-group "$DEBROOT" "$DISTDIR/${DEBPKG}.deb" 2>&1 | sed 's/^/    /'
echo "  ✓ DEB → $DISTDIR/${DEBPKG}.deb"

# ════════════════════════════════════════════════════════════════════════
banner "3/3  Building AppImage"
# ════════════════════════════════════════════════════════════════════════

APPTMP="$TMPDIR_BASE/appimage"
rm -rf "$APPTMP"
mkdir -p "$APPTMP"

# Download appimagetool if not cached
APPIMAGETOOL="$TMPDIR_BASE/appimagetool-x86_64.AppImage"
if [ ! -x "$APPIMAGETOOL" ]; then
    echo "  Downloading appimagetool..."
    TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    curl -sL --fail -o "$APPIMAGETOOL" "$TOOL_URL" \
        || die "Failed to download appimagetool from GitHub releases."
    chmod +x "$APPIMAGETOOL"
    echo "  appimagetool downloaded."
fi

# Build AppDir
APPDIR="$APPTMP/AppDir"
mkdir -p "$APPDIR/opt/reliquary/lib"
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"

# Copy the app package
echo "  Copying reliquary package..."
cp -r "$ROOT/reliquary" "$APPDIR/opt/reliquary/"

# Bundle pip-installable dependencies (those not guaranteed to be on host GTK systems)
# GTK4, libadwaita, GtkSourceView5, and python3-gi must come from the host.
echo "  Bundling Python dependencies (sqlalchemy, psycopg2-binary, pymysql)..."
python3 -m pip install --quiet --no-deps \
    --target="$APPDIR/opt/reliquary/lib" \
    sqlalchemy psycopg2-binary pymysql 2>&1 | sed 's/^/    /'

# AppRun
cp "$PKGDIR/appimage/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

# Desktop file (must be at AppDir root for AppImage)
cp "$DESKTOP" "$APPDIR/$APPID.desktop"

# Icon (PNG required at AppDir root; SVG also in hicolor tree)
echo "  Converting icon to PNG..."
svg_to_png "$ICON_SVG" "$APPDIR/$APPID.png" 256 \
    && echo "  Icon converted." \
    || echo "  Skipping PNG icon (no converter available)."
cp "$ICON_SVG" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"

# Build AppImage
APPIMAGE_OUT="$DISTDIR/${DISPLAY_NAME}-${VERSION}-x86_64.AppImage"
echo "  Running appimagetool..."
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_OUT" 2>&1 | sed 's/^/    /'
chmod +x "$APPIMAGE_OUT"
echo "  ✓ AppImage → $APPIMAGE_OUT"

# ════════════════════════════════════════════════════════════════════════
banner "All packages built"
# ════════════════════════════════════════════════════════════════════════
echo ""
ls -lh "$DISTDIR"/
echo ""
