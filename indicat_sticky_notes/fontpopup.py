"""Окно с ползунком размера шрифта заметки."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .popup import AnchoredPopup  # noqa: E402

FONT_MIN, FONT_MAX = 8, 40


class FontPopup(AnchoredPopup):
    def __init__(self, parent, get_size, get_default, on_change, on_reset):
        super().__init__(parent)
        self._get_size = get_size
        self._get_default = get_default
        self._on_change = on_change
        self._on_reset = on_reset
        self._updating = False
        inner = self.inner

        inner.pack_start(self.caption("Размер шрифта"), False, False, 0)
        row = Gtk.Box(spacing=8)
        small = Gtk.Label(label="A")
        small.set_markup('<span size="small">A</span>')
        row.pack_start(small, False, False, 0)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, FONT_MIN, FONT_MAX, 1)
        self.scale.set_draw_value(False)
        self.scale.set_size_request(220, -1)
        self.scale.set_tooltip_text("Потяните, чтобы изменить размер")
        self.scale.connect("value-changed", self._on_scale)
        row.pack_start(self.scale, True, True, 0)
        big = Gtk.Label()
        big.set_markup('<span size="x-large">A</span>')
        row.pack_start(big, False, False, 0)
        inner.pack_start(row, False, False, 0)

        self.value_label = Gtk.Label(halign=Gtk.Align.CENTER)
        inner.pack_start(self.value_label, False, False, 0)

        self.reset_button = Gtk.Button()
        self.reset_button.connect("clicked", lambda _b: self._on_reset())
        inner.pack_start(self.reset_button, False, False, 4)
        inner.show_all()

    def before_show(self):
        self.sync()

    def sync(self):
        """Показать текущий размер (вызывается и при изменении размера не ползунком)."""
        size = int(self._get_size())
        self._updating = True
        self.scale.set_value(size)
        self._updating = False
        self.value_label.set_text(f"{size} пт")
        self.reset_button.set_label(f"По умолчанию ({self._get_default()} пт)")

    def _on_scale(self, scale):
        if self._updating:
            return
        size = int(round(scale.get_value()))
        self.value_label.set_text(f"{size} пт")
        self._on_change(size)
