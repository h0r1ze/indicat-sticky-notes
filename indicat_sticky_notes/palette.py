"""Окно выбора цвета: основные цвета, дизайнерская палитра и «Свой цвет…»."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from . import theme  # noqa: E402
from .popup import AnchoredPopup  # noqa: E402


class PalettePopup(AnchoredPopup):
    def __init__(self, parent, on_pick, on_custom):
        super().__init__(parent)
        self._on_pick = on_pick
        self._on_custom = on_custom
        inner = self.inner

        inner.pack_start(self.caption("Основные"), False, False, 0)
        row = Gtk.Box(spacing=6)
        for name, (_body, bar) in theme.PALETTE.items():
            row.pack_start(self._swatch(name, bar), False, False, 0)
        inner.pack_start(row, False, False, 0)

        inner.pack_start(self.caption("Палитра"), False, False, 4)
        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        for index, color in enumerate(theme.DESIGNER_PALETTE):
            col, line = index % theme.PALETTE_COLUMNS, index // theme.PALETTE_COLUMNS
            grid.attach(self._swatch(color, color), col, line, 1, 1)
        inner.pack_start(grid, False, False, 0)

        custom = Gtk.Button(label="Свой цвет…")
        custom.connect("clicked", self._on_custom_clicked)
        inner.pack_start(custom, False, False, 6)
        inner.show_all()

    def _swatch(self, value, shown_color):
        swatch = Gtk.Button()
        swatch.set_tooltip_text(value)
        swatch.get_style_context().add_class("swatch")
        theme.paint_swatch(swatch, shown_color)
        swatch.connect("clicked", self._on_swatch_clicked, value)
        return swatch

    def _on_swatch_clicked(self, _button, value):
        self.close_popup()
        self._on_pick(value)

    def _on_custom_clicked(self, _button):
        self.close_popup()
        self._on_custom()
