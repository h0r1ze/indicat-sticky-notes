"""Небольшое окно под кнопкой (палитра, ползунок размера шрифта).

Это отдельное окно, а не Gtk.Popover: в GTK3 на X11 поповер обрезается границами
окна заметки, а такие окна бывают шире маленькой заметки. Окно закрывается при потере
фокуса и по Esc.
"""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import theme  # noqa: E402

_REOPEN_GUARD_MS = 250  # клик по кнопке закрывает окно через потерю фокуса


class AnchoredPopup(Gtk.Window):
    """Окно-карточка. Содержимое добавляют в self.inner."""

    def __init__(self, parent):
        super().__init__(transient_for=parent)
        self._closed_at = 0
        self.close_on_focus_out = True  # тесты без оконного менеджера это отключают

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_keep_above(True)
        self.get_style_context().add_class("palette-popup")

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        rounded = visual is not None and screen.is_composited()
        self._margin = theme.SHADOW_MARGIN if rounded else 0
        if rounded:
            self.set_visual(visual)
            self.set_app_paintable(True)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=self._margin)
        self._card_style = card.get_style_context()
        self._card_style.add_class("palette-card")
        if not rounded:
            self._card_style.add_class("flat")
        self.inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        card.pack_start(self.inner, True, True, 0)
        self.add(card)
        card.show_all()

        self.connect("focus-out-event", self._on_focus_out)
        self.connect("key-press-event", self._on_key)
        self.connect("delete-event", lambda *_: self.close_popup() or True)

    def _on_focus_out(self, *_args):
        if self.close_on_focus_out:
            self.close_popup()
        return False

    @staticmethod
    def caption(text):
        label = Gtk.Label(label=text, halign=Gtk.Align.START)
        label.get_style_context().add_class("palette-caption")
        return label

    def before_show(self):
        """Подготовить содержимое к показу (подклассы переопределяют)."""

    def toggle(self, anchor):
        """Показать окно под кнопкой anchor или скрыть, если оно открыто."""
        if self.get_visible():
            self.close_popup()
            return
        if GLib.get_monotonic_time() / 1000 - self._closed_at < _REOPEN_GUARD_MS:
            return  # это тот же клик, что только что закрыл окно
        if theme.is_dark():
            self._card_style.add_class("dark")
        else:
            self._card_style.remove_class("dark")
        self.before_show()
        self.show_all()
        self._place_under(anchor)
        self.present()

    def close_popup(self):
        if self.get_visible():
            self._closed_at = GLib.get_monotonic_time() / 1000
            self.hide()

    def _place_under(self, anchor):
        gdk_window = anchor.get_window()
        _ok, ox, oy = gdk_window.get_origin()
        alloc = anchor.get_allocation()
        x, y = ox + alloc.x, oy + alloc.y + alloc.height
        natural = self.get_preferred_size()[1]
        width, height = natural.width, natural.height
        monitor = anchor.get_display().get_monitor_at_window(gdk_window).get_workarea()
        x = max(monitor.x, min(x - self._margin, monitor.x + monitor.width - width))
        y = max(monitor.y, min(y - self._margin, monitor.y + monitor.height - height))
        self.move(x, y)

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_popup()
            return True
        return False
