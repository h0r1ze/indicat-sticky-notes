"""Окно одной заметки."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import checklist, colors, theme  # noqa: E402
from .palette import PalettePopup  # noqa: E402
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
        self._color_class = None
        self._busy = False  # идёт программная правка текста

        theme.install()
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_default_size(note.width, note.height)
        self.set_size_request(200, 140)
        self.set_keep_above(note.pinned)
        self.get_style_context().add_class("sticky")

        # Скруглённые углы и тень нужны прозрачному окну (есть композитор).
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        self._rounded = visual is not None and screen.is_composited()
        if self._rounded:
            self.set_visual(visual)
            self.set_app_paintable(True)
        margin = theme.SHADOW_MARGIN if self._rounded else 0

        self._palette = PalettePopup(self, self.set_color, self._choose_custom_color)
        self.connect("destroy", lambda _w: self._palette.destroy())
        self.connect("hide", lambda _w: self._palette.close_popup())

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
        self._update_pin_button()
        self._refresh_done_style()
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

        palette = self._flat_button("●", "Цвет")
        palette.connect("clicked", lambda button: self._palette.toggle(button))
        bar.pack_start(palette, False, False, 0)

        self.pin_button = self._flat_button("📌", "Закрепить поверх всех окон")
        self.pin_button.get_style_context().add_class("pin")
        self.pin_button.connect("clicked", lambda _b: self.set_pinned(not self.note.pinned))
        bar.pack_start(self.pin_button, False, False, 0)

        check = self._flat_button("☑", "Чекбокс в строке (Ctrl+L)")
        check.connect("clicked", lambda _b: self.toggle_checklist())
        bar.pack_start(check, False, False, 0)

        delete = self._flat_button("×", "Удалить заметку")
        delete.get_style_context().add_class("danger")
        delete.connect("clicked", lambda _b: self._confirm_delete())
        bar.pack_end(delete, False, False, 0)

        handle.add(bar)
        return handle

    def _build_body(self):
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(14)
        self.view.set_right_margin(14)
        self.view.set_top_margin(10)
        self.view.set_bottom_margin(6)
        self.view.set_pixels_below_lines(3)
        buffer = self.view.get_buffer()
        buffer.set_text(self.note.text)
        self.done_tag = buffer.create_tag("done", strikethrough=True)
        buffer.connect("changed", self._on_text_changed)
        self.view.connect("key-press-event", self._on_key_press)
        self.view.connect("button-press-event", self._on_view_press)

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

    # --- события окна ---

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

    def _on_configure(self, _widget, _event):
        x, y = self.get_position()
        width, height = self.get_size()
        self.note.x, self.note.y = x, y
        self.note.width, self.note.height = width, height
        self._schedule_save(touch=False)
        return False

    def _on_close(self, _widget, _event):
        # Закрытие окна только прячет заметку; удаляется она кнопкой.
        self.hide_note()
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

    # --- показать / спрятать / закрепить ---

    def show_note(self):
        was_hidden = self.note.hidden
        self.note.hidden = False
        self.show_all()
        self.present()
        if was_hidden:
            self._schedule_save(touch=False)

    def hide_note(self):
        self.note.hidden = True
        self.hide()
        self.flush()

    def set_pinned(self, pinned):
        self.note.pinned = bool(pinned)
        self.set_keep_above(self.note.pinned)
        self._update_pin_button()
        self._schedule_save()

    def _update_pin_button(self):
        ctx = self.pin_button.get_style_context()
        if self.note.pinned:
            ctx.add_class("active")
        else:
            ctx.remove_class("active")
        self.pin_button.set_tooltip_text(
            "Открепить" if self.note.pinned else "Закрепить поверх всех окон"
        )

    # --- цвет ---

    def _choose_custom_color(self):
        dialog = Gtk.ColorChooserDialog(title="Свой цвет", transient_for=self)
        dialog.set_use_alpha(False)
        dialog.set_property("show-editor", True)
        current = Gdk.RGBA()
        current.parse(self._current_body())
        dialog.set_rgba(current)
        if dialog.run() == Gtk.ResponseType.OK:
            rgba = dialog.get_rgba()
            self.set_color(colors.to_hex((rgba.red * 255, rgba.green * 255, rgba.blue * 255)))
        dialog.destroy()

    def set_color(self, name):
        self.note.color = name
        self._apply_color()
        self._schedule_save()

    def _current_body(self):
        color = theme.style_class(self.note.color)
        return theme.PALETTE[color][0] if color in theme.PALETTE else color

    def _apply_color(self):
        self.note.color = theme.style_class(self.note.color)
        ctx = self.card.get_style_context()
        if self._color_class:
            ctx.remove_class(self._color_class)
        self._color_class = theme.css_class_for(self.note.color)
        ctx.add_class(self._color_class)
        # Выполненные пункты бледнеют относительно цвета текста на этом фоне.
        text = Gdk.RGBA()
        text.parse(colors.text_color_for(self._current_body()))
        text.alpha = 0.5
        self.done_tag.set_property("foreground-rgba", text)

    # --- текст и чекбоксы ---

    def _on_text_changed(self, buffer):
        start, end = buffer.get_bounds()
        self.note.text = buffer.get_text(start, end, True)
        self._update_placeholder()
        if not self._busy:
            GLib.idle_add(self._convert_checkbox_prefix)
        self._refresh_done_style()
        self._schedule_save()

    def _update_placeholder(self):
        self.placeholder.set_visible(not self.note.text)

    @staticmethod
    def _line_bounds(iter_):
        start = iter_.copy()
        start.set_line_offset(0)
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        return start, end

    def _replace_prefix(self, start, old_len, new_prefix):
        """Заменить первые old_len символов строки; курсор остаётся на месте."""
        buffer = self.view.get_buffer()
        cursor = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
        line_start = start.get_offset()
        self._busy = True
        try:
            if old_len:
                end = start.copy()
                end.forward_chars(old_len)
                buffer.delete(start, end)
            if new_prefix:
                buffer.insert(buffer.get_iter_at_offset(line_start), new_prefix)
        finally:
            self._busy = False
        if cursor > line_start:
            cursor = max(line_start, cursor + len(new_prefix) - old_len)
        buffer.place_cursor(buffer.get_iter_at_offset(cursor))

    def _convert_checkbox_prefix(self):
        """Набранное «[ ] » на текущей строке превращается в ☐."""
        buffer = self.view.get_buffer()
        start, end = self._line_bounds(buffer.get_iter_at_mark(buffer.get_insert()))
        line = buffer.get_text(start, end, False)
        converted = checklist.converted(line)
        if converted != line:
            self._replace_prefix(start, 4, converted[:2])
        return False

    def toggle_checklist(self):
        """Добавить чекбокс к выделенным строкам или убрать, если он уже везде."""
        buffer = self.view.get_buffer()
        if buffer.get_has_selection():
            first, last = buffer.get_selection_bounds()
            lines = range(first.get_line(), last.get_line() + 1)
        else:
            line = buffer.get_iter_at_mark(buffer.get_insert()).get_line()
            lines = range(line, line + 1)
        texts = [
            buffer.get_text(*self._line_bounds(buffer.get_iter_at_line(n)), False)
            for n in lines
        ]
        all_items = all(checklist.is_item(t) for t in texts)
        # С конца, чтобы смещения предыдущих строк не менялись.
        for n, text in reversed(list(zip(lines, texts))):
            start = buffer.get_iter_at_line(n)
            if all_items:
                self._replace_prefix(start, 2, "")
            elif not checklist.is_item(text):
                self._replace_prefix(start, 0, checklist.OFF)
        self.view.grab_focus()

    def _on_key_press(self, _widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and event.keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self.toggle_checklist()
            return True
        plain_enter = event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (
            event.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK)
        )
        if not plain_enter:
            return False
        buffer = self.view.get_buffer()
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        start, end = self._line_bounds(cursor)
        line = buffer.get_text(start, end, False)
        follow = checklist.on_enter(line)
        if follow is None or cursor.get_line_offset() < len(checklist.OFF):
            return False
        if follow == "":  # Enter на пустом пункте завершает список
            self._replace_prefix(start, len(line), "")
        else:
            buffer.insert_at_cursor("\n" + follow)
            self.view.scroll_mark_onscreen(buffer.get_insert())
        return True

    def _on_view_press(self, _widget, event):
        """Клик по квадратику ☐/☑ переключает галочку."""
        if event.button != 1 or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        buffer = self.view.get_buffer()
        bx, by = self.view.window_to_buffer_coords(
            Gtk.TextWindowType.TEXT, int(event.x), int(event.y)
        )
        found = self.view.get_iter_at_location(bx, by)
        if isinstance(found, tuple):  # (есть ли текст под курсором, позиция)
            found, it = found
            if not found:
                return False
        else:
            it = found
        if it is None:
            return False
        start, end = self._line_bounds(it)
        line = buffer.get_text(start, end, False)
        if not checklist.is_item(line):
            return False
        after = start.copy()
        after.forward_char()
        if not (self.view.get_iter_location(start).x <= bx < self.view.get_iter_location(after).x):
            return False
        self._replace_prefix(start, 2, checklist.toggled(line)[:2])
        return True

    def _refresh_done_style(self):
        """Выполненные пункты зачёркиваются и бледнеют."""
        buffer = self.view.get_buffer()
        begin, finish = buffer.get_bounds()
        buffer.remove_tag(self.done_tag, begin, finish)
        if checklist.ON.strip() not in self.note.text:
            return
        it = buffer.get_start_iter()
        while True:
            start, end = self._line_bounds(it)
            if checklist.is_done(buffer.get_text(start, end, False)):
                text_start = start.copy()
                text_start.forward_chars(2)
                buffer.apply_tag(self.done_tag, text_start, end)
            if not it.forward_line():
                break

    # --- сохранение ---

    def _schedule_save(self, touch=True):
        """Отложенная запись. touch=False — правка не меняет «изменено»."""
        if touch:
            self.store.touch(self.note)
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
