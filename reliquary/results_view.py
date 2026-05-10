from gi.repository import Gtk, GObject, Gio, Pango


class ResultRow(GObject.Object):
    __gtype_name__ = 'ReliquaryResultRow'

    def __init__(self, values: list):
        super().__init__()
        self._values = ['' if v is None else str(v) for v in values]

    def get(self, index: int) -> str:
        if 0 <= index < len(self._values):
            return self._values[index]
        return ''


def build_results_view(
    columns: list[str],
    rows: list[tuple],
    show_row_numbers: bool = True,
) -> Gtk.Widget:
    """Return a GtkColumnView widget populated with the given result set."""
    store = Gio.ListStore(item_type=ResultRow)
    for row in rows:
        store.append(ResultRow(list(row)))

    sort_model = Gtk.SortListModel(model=store)
    selection = Gtk.NoSelection(model=sort_model)

    column_view = Gtk.ColumnView(model=selection)
    column_view.set_show_row_separators(True)
    column_view.set_show_column_separators(True)
    column_view.set_reorderable(True)
    column_view.set_vexpand(True)
    column_view.set_hexpand(True)
    column_view.add_css_class('data-table')

    # Row number column
    if show_row_numbers:
        num_factory = Gtk.SignalListItemFactory()
        num_factory.connect('setup', _setup_num_cell)
        num_factory.connect('bind', _bind_num_cell)
        num_col = Gtk.ColumnViewColumn(title='#', factory=num_factory)
        num_col.set_fixed_width(52)
        column_view.append_column(num_col)

    # Data columns
    sorter = Gtk.ColumnView.get_sorter(column_view)
    sort_model.set_sorter(sorter)

    for i, col_name in enumerate(columns):
        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', _setup_data_cell)
        factory.connect('bind', _make_bind_func(i))

        col_sorter = Gtk.CustomSorter.new(_make_sort_func(i), None)
        col = Gtk.ColumnViewColumn(
            title=col_name,
            factory=factory,
            sorter=col_sorter,
        )
        col.set_resizable(True)
        col.set_expand(i == len(columns) - 1)
        column_view.append_column(col)

    scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroll.set_child(column_view)
    return scroll


# ── Cell factories ────────────────────────────────────────────────────────

def _setup_num_cell(factory, list_item):
    label = Gtk.Label(xalign=1, margin_start=8, margin_end=8)
    label.add_css_class('dim-label')
    label.add_css_class('numeric')
    list_item.set_child(label)


def _bind_num_cell(factory, list_item):
    label = list_item.get_child()
    pos = list_item.get_position()
    label.set_label(str(pos + 1))


def _setup_data_cell(factory, list_item):
    label = Gtk.Label(
        xalign=0,
        ellipsize=Pango.EllipsizeMode.END,
        max_width_chars=40,
        margin_start=8,
        margin_end=8,
        margin_top=4,
        margin_bottom=4,
    )
    label.set_selectable(True)
    list_item.set_child(label)


def _make_bind_func(col_index: int):
    def on_bind(factory, list_item, idx=col_index):
        row: ResultRow = list_item.get_item()
        label: Gtk.Label = list_item.get_child()
        value = row.get(idx)
        label.set_label(value)
        # Style NULL values distinctly
        if value == '':
            label.add_css_class('dim-label')
        else:
            label.remove_css_class('dim-label')
    return on_bind


def _make_sort_func(col_index: int):
    def compare(a: ResultRow, b: ResultRow, _data, idx=col_index):
        va, vb = a.get(idx), b.get(idx)
        # Try numeric sort first
        try:
            fa, fb = float(va), float(vb)
            if fa < fb: return -1
            if fa > fb: return 1
            return 0
        except ValueError:
            if va < vb: return -1
            if va > vb: return 1
            return 0
    return compare
