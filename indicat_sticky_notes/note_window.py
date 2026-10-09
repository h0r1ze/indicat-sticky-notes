"""Окно одной заметки."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import theme  # noqa: E402
from .storage import Note  # noqa: E402

SAVE_DELAY_MS = 500


class NoteWindow(Gtk.Window):
    def __init__(self, note: Note, store, on_new, on_deleted):
        super().__init__(title="Заметка")
        self.note = note
        self.store = store
        self._on_new = on_new
        self._on_deleted = on_deleted
        self._save_source = None

        theme.install()
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_default_size(note.width, note.height)
        self.set_size_request(200, 140)
        self.get_style_context().add_class("sticky")

        # Скруглённые углы и тень нужны прозрачному окну (есть композитор).
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        self._rounded = visual is not None and screen.is_composited()
        if self._rounded:
            self.set_visual(visual)
            self.set_app_paintable(True)
        margin = theme.SHADOW_MARGIN if self._rounded else 0

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=margin)
        card_style = self.card.get_style_context()
        card_style.add_class("note")
        if not self._rounded:
            card_style.add_class("flat")

        self.card.pack_start(self._build_bar(), False, False, 0)
        self.card.pack_start(self._build_body(), True, True, 0)
        self.card.pack_start(self._build_grip(), False, False, 0)
        self.add(self.card)

        self._apply_color()
        self._update_placeholder()
        self.move(note.x, note.y)
        self.connect("configure-event", self._on_configure)
        self.connect("delete-event", self._on_close)

    # --- построение интерфейса ---

    def _build_bar(self):
        handle = Gtk.EventBox()
        handle.set_visible_window(False)
        handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        handle.connect("button-press-event", self._on_bar_press)

        bar = Gtk.Box(spacing=2)
        bar.get_style_context().add_class("bar")

        add = self._flat_button("+", "Новая заметка")
        add.connect("clicked", lambda _b: self._on_new())
        bar.pack_start(add, False, False, 0)

        palette = Gtk.MenuButton()
        palette.set_label("●")
        palette.set_tooltip_text("Цвет")
        palette.set_popover(self._build_color_popover(palette))
        bar.pack_start(palette, False, False, 0)

        delete = self._flat_button("×", "Удалить заметку")
        delete.get_style_context().add_class("danger")
        delete.connect("clicked", lambda _b: self._confirm_delete())
        bar.pack_end(delete, False, False, 0)

        handle.add(bar)
        return handle

    def _build_color_popover(self, relative_to):
        popover = Gtk.Popover.new(relative_to)
        row = Gtk.Box(spacing=6, margin=10)
        for name in theme.PALETTE:
            swatch = Gtk.Button()
            swatch.set_tooltip_text(name)
            ctx = swatch.get_style_context()
            ctx.add_class("swatch")
            ctx.add_class(name)
            swatch.connect("clicked", self._on_color_chosen, name, popover)
            row.pack_start(swatch, False, False, 0)
        row.show_all()
        popover.add(row)
        return popover

    def _build_body(self):
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(14)
        self.view.set_right_margin(14)
        self.view.set_top_margin(10)
        self.view.set_bottom_margin(6)
        self.view.set_pixels_below_lines(3)
        self.view.get_buffer().set_text(self.note.text)
        self.view.get_buffer().connect("changed", self._on_text_changed)

        scroll = Gtk.ScrolledWindow()
        # EXTERNAL, а не NEVER: иначе минимальная ширина окна равна самой
        # длинной строке текста без переносов.
        scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.view)

        self.placeholder = Gtk.Label(label="Напишите что-нибудь…")
        self.placeholder.get_style_context().add_class("placeholder")
        self.placeholder.set_halign(Gtk.Align.START)
        self.placeholder.set_valign(Gtk.Align.START)
        self.placeholder.set_margin_start(14)
        self.placeholder.set_margin_top(10)
        self.placeholder.set_no_show_all(True)  # видимостью управляет _update_placeholder

        overlay = Gtk.Overlay()
        overlay.add(scroll)
        overlay.add_overlay(self.placeholder)
        overlay.set_overlay_pass_through(self.placeholder, True)
        return overlay

    def _build_grip(self):
        grip = Gtk.EventBox()
        grip.set_visible_window(False)
        grip.set_size_request(-1, 16)
        grip.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        grip.connect("button-press-event", self._on_grip_press)
        label = Gtk.Label(label="◢", halign=Gtk.Align.END, margin_end=6)
        label.get_style_context().add_class("grip")
        grip.add(label)
        grip.connect(
            "realize",
            lambda w: w.get_window().set_cursor(
                Gdk.Cursor.new_from_name(w.get_display(), "se-resize")
            ),
        )
        return grip

    @staticmethod
    def _flat_button(label, tooltip):
        button = Gtk.Button(label=label)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(tooltip)
        return button

    # --- события ---

    def _on_bar_press(self, _widget, event):
        if event.button == 1:
            self.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )
        return False

    def _on_grip_press(self, _widget, event):
        if event.button == 1:
            self.begin_resize_drag(
                Gdk.WindowEdge.SOUTH_EAST,
                event.button,
                int(event.x_root),
                int(event.y_root),
                event.time,
            )
        return True

    def _on_color_chosen(self, _button, name, popover):
        popover.popdown()
        self.set_color(name)

    def _on_text_changed(self, buffer):
        start, end = buffer.get_bounds()
        self.note.text = buffer.get_text(start, end, True)
        self._update_placeholder()
        self._schedule_save()

    def _on_configure(self, _widget, _event):
        x, y = self.get_position()
        width, height = self.get_size()
        self.note.x, self.note.y = x, y
        self.note.width, self.note.height = width, height
        self._schedule_save()
        return False

    def _on_close(self, _widget, _event):
        # Закрытие окна только прячет заметку; удаляется она кнопкой.
        self.hide()
        return True

    def _confirm_delete(self):
        if self.note.text.strip():
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text="Удалить заметку?",
            )
            answer = dialog.run()
            dialog.destroy()
            if answer != Gtk.ResponseType.YES:
                return
        self.flush()
        self._on_deleted(self)

    # --- оформление и сохранение ---

    def set_color(self, name):
        self.note.color = name
        self._apply_color()
        self._schedule_save()

    def _apply_color(self):
        if self.note.color not in theme.PALETTE:
            self.note.color = theme.DEFAULT_COLOR
        ctx = self.card.get_style_context()
        for name in theme.PALETTE:
            ctx.remove_class(name)
        ctx.add_class(self.note.color)

    def _update_placeholder(self):
        self.placeholder.set_visible(not self.note.text)

    def _schedule_save(self):
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(SAVE_DELAY_MS, self._save_now)

    def _save_now(self):
        self._save_source = None
        self.store.save()
        return False

    def flush(self):
        """Сохранить немедленно, если есть отложенная запись."""
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
            self._save_source = None
        self.store.save()
