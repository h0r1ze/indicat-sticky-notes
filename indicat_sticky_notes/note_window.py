"""Окно одной заметки."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .storage import COLORS, Note  # noqa: E402

SAVE_DELAY_MS = 500


class NoteWindow(Gtk.Window):
    def __init__(self, note: Note, store, on_new, on_deleted):
        super().__init__(title="Заметка")
        self.note = note
        self.store = store
        self._on_new = on_new
        self._on_deleted = on_deleted
        self._save_source = None

        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_default_size(note.width, note.height)
        self.set_resizable(True)

        self._css = Gtk.CssProvider()
        self.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self._build_bar(), False, False, 0)

        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(8)
        self.view.set_right_margin(8)
        self.view.set_top_margin(6)
        # Провайдер окна не наследуется вложенными виджетами.
        self.view.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.view.get_buffer().set_text(note.text)
        self.view.get_buffer().connect("changed", self._on_text_changed)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.view)
        root.pack_start(scroll, True, True, 0)

        root.pack_start(self._build_grip(), False, False, 0)
        self.add(root)

        self._apply_color()
        self.move(note.x, note.y)
        self.connect("configure-event", self._on_configure)
        self.connect("delete-event", self._on_close)

    # --- построение интерфейса ---

    def _build_bar(self):
        bar = Gtk.EventBox()
        bar.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        bar.connect("button-press-event", self._on_bar_press)
        box = Gtk.Box(spacing=2)
        box.set_border_width(2)

        add = self._flat_button("list-add-symbolic", "Новая заметка")
        add.connect("clicked", lambda _b: self._on_new())
        box.pack_start(add, False, False, 0)

        palette = Gtk.MenuButton()
        palette.set_relief(Gtk.ReliefStyle.NONE)
        palette.set_tooltip_text("Цвет")
        palette.set_image(Gtk.Image.new_from_icon_name("applications-graphics-symbolic", Gtk.IconSize.MENU))
        palette.set_popup(self._build_color_menu())
        box.pack_start(palette, False, False, 0)

        delete = self._flat_button("edit-delete-symbolic", "Удалить заметку")
        delete.connect("clicked", lambda _b: self._confirm_delete())
        box.pack_end(delete, False, False, 0)

        bar.add(box)
        return bar

    def _build_color_menu(self):
        menu = Gtk.Menu()
        for name in COLORS:
            item = Gtk.MenuItem(label=name)
            item.connect("activate", self._on_color_chosen, name)
            menu.append(item)
        menu.show_all()
        return menu

    def _build_grip(self):
        grip = Gtk.EventBox()
        grip.set_size_request(-1, 14)
        grip.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        grip.connect("button-press-event", self._on_grip_press)
        label = Gtk.Label(label="◢", halign=Gtk.Align.END)
        label.set_opacity(0.4)
        grip.add(label)
        grip.connect(
            "realize",
            lambda w: w.get_window().set_cursor(
                Gdk.Cursor.new_from_name(w.get_display(), "se-resize")
            ),
        )
        return grip

    @staticmethod
    def _flat_button(icon, tooltip):
        button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.MENU)
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

    def _on_color_chosen(self, _item, name):
        self.note.color = name
        self._apply_color()
        self._schedule_save()

    def _on_text_changed(self, buffer):
        start, end = buffer.get_bounds()
        self.note.text = buffer.get_text(start, end, True)
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

    def _apply_color(self):
        color = COLORS.get(self.note.color, COLORS["yellow"])
        css = (
            f"window {{ background-color: {color}; border: 1px solid rgba(0,0,0,0.25); }}"
            f"textview, textview text {{ background-color: {color}; color: #222; }}"
        )
        self._css.load_from_data(css.encode())

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
