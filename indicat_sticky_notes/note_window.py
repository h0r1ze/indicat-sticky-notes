"""Окно одной заметки."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import checklist, colors, theme  # noqa: E402
from .keys import is_key  # noqa: E402
from .palette import PalettePopup  # noqa: E402
from .storage import Note  # noqa: E402

SAVE_DELAY_MS = 500
MIN_WIDTH, MIN_HEIGHT = 240, 140
FONT_RANGE = (8, 40)
OPACITIES = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4)

# Теги форматирования: имя -> свойства Gtk.TextTag. Их диапазоны сохраняются в note.formats.
FORMAT_TAGS = {
    "bold": {"weight": Pango.Weight.BOLD},
    "italic": {"style": Pango.Style.ITALIC},
    "underline": {"underline": Pango.Underline.SINGLE},
    "strike": {"strikethrough": True},
}
FORMAT_LABELS = {
    "bold": "Жирный   Ctrl+B",
    "italic": "Курсив   Ctrl+I",
    "underline": "Подчёркнутый   Ctrl+U",
    "strike": "Зачёркнутый   Ctrl+Shift+X",
}


class NoteWindow(Gtk.Window):
    def __init__(self, note: Note, app):
        super().__init__(title="Заметка")
        self.note = note
        self.app = app
        self.store = app.store
        self._save_source = None
        self._color_class = None
        self._busy = False  # идёт программная правка текста
        self._loading = False  # загрузка/обновление из данных: ничего не сохранять
        self._press = None  # нажатие на шапке: ждём, будет ли это перетаскиванием
        self._typing = {}  # формат для следующих набранных символов: имя -> включён
        self._typing_pos = None
        self._cursors = {}
        self._font_provider = Gtk.CssProvider()
        self._placeholder_provider = Gtk.CssProvider()

        theme.install()
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_default_size(note.width, note.height)
        self.set_size_request(MIN_WIDTH, MIN_HEIGHT)
        self.set_keep_above(note.pinned)
        self.set_opacity(self._valid_opacity())
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
        self.connect("destroy", self._on_destroy)
        self.connect("hide", lambda _w: self._palette.close_popup())

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=margin)
        card_style = self.card.get_style_context()
        card_style.add_class("note")
        if not self._rounded:
            card_style.add_class("flat")

        self.card.pack_start(self._build_bar(), False, False, 0)
        self.body = self._build_body()
        self.card.pack_start(self.body, True, True, 0)
        self.grip = self._build_grip()
        self.card.pack_start(self.grip, False, False, 0)
        self.add(self.card)

        self.view.get_style_context().add_provider(
            self._font_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self.placeholder.get_style_context().add_provider(
            self._placeholder_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self._apply_color()
        self._apply_font()
        self._update_collapsed_class()
        self._update_placeholder()
        self._update_pin_button()
        self._update_title_label()
        self._refresh_done_style()
        self.move(note.x, note.y)
        self.connect("configure-event", self._on_configure)
        self.connect("delete-event", self._on_close)
        self.connect("map", lambda _w: self._apply_collapsed())

    # --- построение интерфейса ---

    def _build_bar(self):
        handle = Gtk.EventBox()
        handle.set_visible_window(False)
        handle.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
        )
        handle.connect("button-press-event", self._on_bar_press)
        handle.connect("button-release-event", lambda *_a: setattr(self, "_press", None))
        handle.connect("motion-notify-event", self._on_bar_motion)

        bar = Gtk.Box(spacing=2)
        bar.get_style_context().add_class("bar")

        add = self._flat_button("+", "Новая заметка")
        add.connect("clicked", lambda _b: self.app.new_note())
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

        self.title_label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.title_label.get_style_context().add_class("title")
        bar.pack_start(self.title_label, True, True, 0)

        delete = self._flat_button("×", "В корзину")
        delete.get_style_context().add_class("danger")
        delete.connect("clicked", lambda _b: self.app.delete_note(self.note.id))
        bar.pack_end(delete, False, False, 0)

        self.menu_button = self._flat_button("⋯", "Меню заметки")
        self.menu_button.connect("clicked", lambda _b: self.popup_menu())
        bar.pack_end(self.menu_button, False, False, 0)

        handle.add(bar)
        return handle

    def _build_body(self):
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(14)
        self.view.set_right_margin(14)
        self.view.set_top_margin(10)
        self.view.set_bottom_margin(6)
        self.view.set_pixels_below_lines(3)
        self.view.add_events(Gdk.EventMask.SCROLL_MASK)
        buffer = self.view.get_buffer()
        self._loading = True
        buffer.set_text(self.note.text)
        self.done_tag = buffer.create_tag("done", strikethrough=True)
        for name, props in FORMAT_TAGS.items():
            buffer.create_tag(name, **props)
        self.found_tag = buffer.create_tag(
            "found", background_rgba=Gdk.RGBA(1.0, 0.84, 0.0, 0.6), foreground="#000000"
        )
        self._apply_saved_formats()
        self._loading = False
        buffer.connect("changed", self._on_text_changed)
        buffer.connect("apply-tag", self._on_tags_changed)
        buffer.connect("remove-tag", self._on_tags_changed)
        buffer.connect_after("insert-text", self._on_insert_text)
        self.view.connect("key-press-event", self._on_key_press)
        self.view.connect("button-press-event", self._on_view_press)
        self.view.connect_after("motion-notify-event", self._on_view_motion)
        self.view.connect("scroll-event", self._on_scroll)

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
        grip.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        grip.connect("button-press-event", self._on_grip_press)
        # У EventBox без видимого окна нет своего GdkWindow, поэтому курсор ставим на
        # окно заметки по входу/выходу: иначе он остался бы на всей заметке.
        grip.connect("enter-notify-event", lambda *_a: self._set_window_cursor("se-resize"))
        grip.connect("leave-notify-event", lambda *_a: self._set_window_cursor(None))
        label = Gtk.Label(label="◢", halign=Gtk.Align.END, margin_end=6)
        label.get_style_context().add_class("grip")
        grip.add(label)
        return grip

    def _cursor(self, name):
        if name not in self._cursors:
            self._cursors[name] = Gdk.Cursor.new_from_name(self.get_display(), name)
        return self._cursors[name]

    def _set_window_cursor(self, name):
        gdk_window = self.get_window()
        if gdk_window is not None:
            gdk_window.set_cursor(self._cursor(name) if name else None)

    @staticmethod
    def _flat_button(label, tooltip):
        button = Gtk.Button(label=label)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(tooltip)
        return button

    # --- события окна ---

    def _on_bar_press(self, _widget, event):
        if event.button == 3:
            self.popup_menu()
            return True
        if event.button != 1:
            return False
        if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self._press = None
            self.set_collapsed(not self.note.collapsed)
            return True
        self._press = (event.x_root, event.y_root)
        return False

    def _on_bar_motion(self, _widget, event):
        # Перетаскивание начинаем только когда мышь сдвинулась: иначе двойной щелчок
        # по шапке не дойдёт до нас (оконный менеджер перехватит нажатие).
        if self._press is None:
            return False
        if abs(event.x_root - self._press[0]) + abs(event.y_root - self._press[1]) > 4:
            self._press = None
            self.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)
        return True

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
        self.note.width = width
        if not self.note.collapsed:  # высота свёрнутой заметки — не её настоящий размер
            self.note.height = height
        self._schedule_save(touch=False)
        return False

    def _on_destroy(self, _widget):
        # Отложенную запись отменяем: заметка уже могла уйти в корзину.
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
            self._save_source = None
        self._palette.destroy()

    def _on_close(self, _widget, _event):
        # Закрытие окна только прячет заметку; удаляется она кнопкой.
        self.hide_note()
        return True

    # --- показать / спрятать / закрепить / свернуть ---

    def show_note(self, highlight=None):
        was_hidden = self.note.hidden
        self.note.hidden = False
        self.show_all()
        self.present()
        if was_hidden:
            self._schedule_save(touch=False)
        if highlight is not None:
            self.highlight(highlight)

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

    def set_collapsed(self, collapsed):
        self.note.collapsed = bool(collapsed)
        self._apply_collapsed()
        self._update_title_label()
        self._schedule_save(touch=False)

    def _apply_collapsed(self):
        collapsed = self.note.collapsed
        self._update_collapsed_class()
        self.body.set_visible(not collapsed)
        self.grip.set_visible(not collapsed)
        self.set_size_request(MIN_WIDTH, 1 if collapsed else MIN_HEIGHT)
        if collapsed:
            self.resize(max(self.note.width, MIN_WIDTH), 1)
        else:
            self.resize(max(self.note.width, MIN_WIDTH), max(self.note.height, MIN_HEIGHT))

    def _update_collapsed_class(self):
        """У свёрнутой заметки скруглены все углы шапки, а не только верхние."""
        ctx = self.card.get_style_context()
        if self.note.collapsed:
            ctx.add_class("collapsed")
        else:
            ctx.remove_class("collapsed")

    # --- заголовок, прозрачность, размер шрифта, группа ---

    def _update_title_label(self):
        text = self.note.title.strip()
        if not text and self.note.collapsed:
            text = self.note.preview(40)
        self.title_label.set_text(text)

    def _ask_text(self, title, placeholder, initial=""):
        """Небольшое окно с одним полем ввода. Возвращает строку или None при отмене."""
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Готово", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=initial, activates_default=True, width_chars=32,
                          placeholder_text=placeholder)
        for side in ("start", "end", "top"):
            getattr(entry, f"set_margin_{side}")(12)
        entry.set_margin_bottom(6)
        dialog.get_content_area().add(entry)
        dialog.show_all()
        answer = entry.get_text() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return answer

    def edit_title(self):
        title = self._ask_text("Заголовок заметки", "Заголовок", self.note.title)
        if title is not None:
            self.set_title_text(title)

    def set_title_text(self, title):
        self.note.title = title.strip()
        self._update_title_label()
        self._schedule_save()

    def ask_new_group(self):
        group = self._ask_text("Новая группа", "Название группы")
        if group and group.strip():
            self.set_group(group)

    def _valid_opacity(self):
        value = self.note.opacity
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0.2 <= value <= 1.0
        return float(value) if ok else 1.0

    def set_note_opacity(self, value):
        self.note.opacity = float(value)
        self.set_opacity(self._valid_opacity())  # нужен композитор; без него не виден
        self._schedule_save()

    def effective_font_size(self):
        return self.note.font_size or self.app.default_font_size()

    def change_font(self, delta):
        """delta=0 — вернуть размер по умолчанию."""
        if delta == 0:
            self.note.font_size = 0
        else:
            size = self.effective_font_size() + delta
            self.note.font_size = max(FONT_RANGE[0], min(FONT_RANGE[1], size))
        self._apply_font()
        self._schedule_save()

    def _apply_font(self):
        size = int(self.note.font_size or 0)
        if size:
            view_css = f"textview, textview text {{ font-size: {size}pt; }}"
            placeholder_css = f"label {{ font-size: {size}pt; }}"
        else:
            view_css = placeholder_css = ""
        self._font_provider.load_from_data(view_css.encode())
        self._placeholder_provider.load_from_data(placeholder_css.encode())

    def set_group(self, group):
        self.note.group = group.strip()
        self._schedule_save()

    # --- меню «⋯» ---

    def popup_menu(self):
        menu = self.build_menu()
        menu.popup_at_widget(
            self.menu_button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None
        )

    def build_menu(self):
        menu = Gtk.Menu()

        def item(parent, label, callback, check=None):
            if check is None:
                entry = Gtk.MenuItem(label=label)
                entry.connect("activate", lambda _i: callback())
            else:
                entry = Gtk.CheckMenuItem(label=label)
                entry.set_active(check)
                entry.connect("toggled", lambda _i: callback())
            parent.append(entry)
            return entry

        def submenu(label):
            sub = Gtk.Menu()
            head = Gtk.MenuItem(label=label)
            head.set_submenu(sub)
            menu.append(head)
            return sub

        item(menu, "Заголовок…", self.edit_title)
        item(menu, "Развернуть" if self.note.collapsed else "Свернуть",
             lambda: self.set_collapsed(not self.note.collapsed))
        menu.append(Gtk.SeparatorMenuItem())

        formats = submenu("Формат")
        for name, label in FORMAT_LABELS.items():
            item(formats, label, lambda n=name: self.toggle_format(n),
                 check=self.format_state(name))
        formats.append(Gtk.SeparatorMenuItem())
        item(formats, "Чекбокс   Ctrl+L", self.toggle_checklist)

        font = submenu("Размер шрифта")
        item(font, "Крупнее   Ctrl++", lambda: self.change_font(+1))
        item(font, "Мельче   Ctrl+−", lambda: self.change_font(-1))
        item(font, f"По умолчанию ({self.app.default_font_size()} пт)   Ctrl+0",
             lambda: self.change_font(0))

        opacity = submenu("Прозрачность")
        for value in OPACITIES:
            item(opacity, f"{int(value * 100)}%", lambda v=value: self.set_note_opacity(v),
                 check=abs(self._valid_opacity() - value) < 0.01)

        groups = submenu("Группа")
        item(groups, "Без группы", lambda: self.set_group(""), check=not self.note.group)
        for name in self.store.groups():
            item(groups, name, lambda n=name: self.set_group(n), check=self.note.group == name)
        groups.append(Gtk.SeparatorMenuItem())
        item(groups, "Новая группа…", self.ask_new_group)

        menu.append(Gtk.SeparatorMenuItem())
        item(menu, "Сохранить как файл…", lambda: self.app.export_note(self.note, self))
        item(menu, "В корзину", lambda: self.app.delete_note(self.note.id))
        menu.show_all()
        return menu

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

    # --- текст ---

    def _on_text_changed(self, buffer):
        if self._loading:
            return
        start, end = buffer.get_bounds()
        self.note.text = buffer.get_text(start, end, True)
        self._update_placeholder()
        self._update_title_label()
        if not self._busy:
            GLib.idle_add(self._convert_checkbox_prefix)
        self._refresh_done_style()
        self._clear_highlight()
        self._schedule_save()

    def _update_placeholder(self):
        self.placeholder.set_visible(not self.note.text)

    def _text(self):
        buffer = self.view.get_buffer()
        return buffer.get_text(*buffer.get_bounds(), True)

    # --- форматирование ---

    def _apply_saved_formats(self):
        buffer = self.view.get_buffer()
        length = buffer.get_char_count()
        for item in self.note.formats or []:
            try:
                start, end, name = item
            except (TypeError, ValueError):
                continue
            if (name in FORMAT_TAGS and isinstance(start, int) and isinstance(end, int)
                    and 0 <= start < end <= length):
                buffer.apply_tag_by_name(
                    name, buffer.get_iter_at_offset(start), buffer.get_iter_at_offset(end)
                )

    def collect_formats(self):
        """Диапазоны всех тегов форматирования: [[начало, конец, имя], ...]."""
        buffer = self.view.get_buffer()
        result = []
        for name in FORMAT_TAGS:
            tag = buffer.get_tag_table().lookup(name)
            it = buffer.get_start_iter()
            while True:
                if it.has_tag(tag):
                    begin = it.get_offset()
                    if not it.forward_to_tag_toggle(tag):
                        result.append([begin, buffer.get_char_count(), name])
                        break
                    result.append([begin, it.get_offset(), name])
                elif not it.forward_to_tag_toggle(tag):
                    break
        return sorted(result)

    def _on_tags_changed(self, _buffer, tag, *_rest):
        if not self._loading and tag.get_property("name") in FORMAT_TAGS:
            self._schedule_save()

    @staticmethod
    def _range_fully_tagged(tag, start, end):
        it = start.copy()
        while it.compare(end) < 0:
            if not it.has_tag(tag):
                return False
            it.forward_char()
        return True

    def format_state(self, name):
        """Включён ли формат: на всём выделении или в точке ввода."""
        buffer = self.view.get_buffer()
        tag = buffer.get_tag_table().lookup(name)
        if buffer.get_has_selection():
            return self._range_fully_tagged(tag, *buffer.get_selection_bounds())
        if name in self._typing:
            return self._typing[name]
        before = buffer.get_iter_at_mark(buffer.get_insert())
        return before.backward_char() and before.has_tag(tag)

    def toggle_format(self, name):
        buffer = self.view.get_buffer()
        tag = buffer.get_tag_table().lookup(name)
        if buffer.get_has_selection():
            start, end = buffer.get_selection_bounds()
            if self._range_fully_tagged(tag, start, end):
                buffer.remove_tag(tag, start, end)
            else:
                buffer.apply_tag(tag, start, end)
        else:
            # Без выделения формат действует на то, что пользователь напечатает дальше.
            self._typing[name] = not self.format_state(name)
            self._typing_pos = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
        self.view.grab_focus()

    def _on_insert_text(self, buffer, location, text, _length):
        if not self._typing or self._loading or self._busy:
            return
        end = location.get_offset()
        start = end - len(text)
        if start != self._typing_pos:
            self._typing.clear()  # курсор ушёл в другое место
            return
        begin_iter, end_iter = buffer.get_iter_at_offset(start), buffer.get_iter_at_offset(end)
        for name, enabled in self._typing.items():
            if enabled:
                buffer.apply_tag_by_name(name, begin_iter, end_iter)
            else:
                buffer.remove_tag_by_name(name, begin_iter, end_iter)
        self._typing_pos = end

    # --- поиск: подсветка найденного ---

    def highlight(self, query):
        """Подсветить все вхождения query и прокрутить к первому. Возвращает их число."""
        self._clear_highlight()
        query = (query or "").strip().lower()
        if not query:
            return 0
        buffer = self.view.get_buffer()
        text = self._text().lower()
        first, count, pos = None, 0, text.find(query)
        while pos != -1:
            start = buffer.get_iter_at_offset(pos)
            end = buffer.get_iter_at_offset(pos + len(query))
            buffer.apply_tag(self.found_tag, start, end)
            first = pos if first is None else first
            count += 1
            pos = text.find(query, pos + len(query))
        if first is not None:
            self.view.scroll_to_iter(buffer.get_iter_at_offset(first), 0.1, False, 0, 0)
        return count

    def _clear_highlight(self):
        buffer = self.view.get_buffer()
        buffer.remove_tag(self.found_tag, *buffer.get_bounds())

    # --- чекбоксы ---

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
        shift = event.state & Gdk.ModifierType.SHIFT_MASK
        if ctrl:
            if is_key(event, Gdk.KEY_a):
                buffer = self.view.get_buffer()
                buffer.select_range(buffer.get_start_iter(), buffer.get_end_iter())
                return True
            if is_key(event, Gdk.KEY_l):
                self.toggle_checklist()
                return True
            if is_key(event, Gdk.KEY_b):
                self.toggle_format("bold")
                return True
            if is_key(event, Gdk.KEY_i):
                self.toggle_format("italic")
                return True
            if is_key(event, Gdk.KEY_u):
                self.toggle_format("underline")
                return True
            if shift and is_key(event, Gdk.KEY_x):
                self.toggle_format("strike")
                return True
            if event.keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.change_font(+1)
                return True
            if event.keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract, Gdk.KEY_underscore):
                self.change_font(-1)
                return True
            if event.keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
                self.change_font(0)
                return True
        plain_enter = event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (ctrl or shift)
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

    def _on_scroll(self, _widget, event):
        """Ctrl + колесо мыши меняет размер шрифта."""
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            self.change_font(+1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.change_font(-1)
        elif event.direction == Gdk.ScrollDirection.SMOOTH and event.delta_y:
            self.change_font(-1 if event.delta_y > 0 else +1)
        return True

    def _checkbox_at(self, x, y):
        """Начало строки с чекбоксом, если точка (x, y) окна текста попала на квадратик."""
        buffer = self.view.get_buffer()
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(x), int(y))
        found = self.view.get_iter_at_location(bx, by)
        if isinstance(found, tuple):  # (есть ли текст под курсором, позиция)
            found, it = found
            if not found:
                return None
        else:
            it = found
        if it is None:
            return None
        start, end = self._line_bounds(it)
        if not checklist.is_item(buffer.get_text(start, end, False)):
            return None
        after = start.copy()
        after.forward_char()
        if self.view.get_iter_location(start).x <= bx < self.view.get_iter_location(after).x:
            return start
        return None

    def _on_view_press(self, _widget, event):
        """Клик по квадратику ☐/☑ переключает галочку."""
        if event.button != 1 or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        start = self._checkbox_at(event.x, event.y)
        if start is None:
            return False
        buffer = self.view.get_buffer()
        line = buffer.get_text(*self._line_bounds(start), False)
        self._replace_prefix(start, 2, checklist.toggled(line)[:2])
        return True

    def _on_view_motion(self, _widget, event):
        """Над квадратиком чекбокса курсор обычная стрелка, над остальным текстом — «текст»."""
        text_window = self.view.get_window(Gtk.TextWindowType.TEXT)
        if text_window is not None:
            over_box = self._checkbox_at(event.x, event.y) is not None
            text_window.set_cursor(self._cursor("default" if over_box else "text"))
        return False

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

    # --- обновление из данных (синхронизация, восстановление) ---

    def refresh_from_note(self):
        """Подтянуть показанное в окне из self.note после внешнего изменения."""
        self._loading = True
        try:
            buffer = self.view.get_buffer()
            if self._text() != self.note.text:
                cursor = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
                buffer.set_text(self.note.text)
                buffer.place_cursor(buffer.get_iter_at_offset(min(cursor, buffer.get_char_count())))
            for name in FORMAT_TAGS:
                buffer.remove_tag_by_name(name, *buffer.get_bounds())
            self._apply_saved_formats()
        finally:
            self._loading = False
        self._apply_color()
        self._apply_font()
        self._update_placeholder()
        self._update_title_label()
        self._refresh_done_style()
        self.set_opacity(self._valid_opacity())

    # --- сохранение ---

    def _schedule_save(self, touch=True):
        """Отложенная запись. touch=False — правка не меняет «изменено»."""
        if self._loading:
            return
        if touch:
            self.store.touch(self.note)
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(SAVE_DELAY_MS, self._save_now)

    def _save_now(self):
        self._save_source = None
        self.note.formats = self.collect_formats()
        self.store.save()
        return False

    def flush(self):
        """Сохранить немедленно, если есть отложенная запись."""
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
            self._save_source = None
        self.note.formats = self.collect_formats()
        self.store.save()
