"""Приложение: значок в трее и набор окон заметок."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .note_window import NoteWindow  # noqa: E402
from .storage import NoteStore  # noqa: E402

APP_ID = "io.github.h0r1ze.IndicatStickyNotes"


class StickyApp(Gtk.Application):
    def __init__(self, store: NoteStore = None):
        super().__init__(application_id=APP_ID)
        self.store = store or NoteStore()
        self.windows = {}
        self.notes_visible = True
        self.tray = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.store.load()
        self.hold()  # живём в трее, даже когда все заметки скрыты
        for note in self.store.notes:
            self._open_window(note)
        self._build_tray()

    def do_activate(self):
        # Повторный запуск показывает заметки (или создаёт первую).
        if not self.store.notes:
            self.new_note()
        else:
            self.set_notes_visible(True)

    def do_shutdown(self):
        for window in self.windows.values():
            window.flush()
        Gtk.Application.do_shutdown(self)

    # --- заметки ---

    def _open_window(self, note):
        window = NoteWindow(note, self.store, self.new_note, self._delete_window)
        self.windows[note.id] = window
        if self.notes_visible:
            window.show_all()
        return window

    def new_note(self):
        # Каждая следующая заметка немного смещается, чтобы не лечь ровно поверх.
        offset = 30 * (len(self.store.notes) % 8)
        note = self.store.add(x=120 + offset, y=120 + offset)
        self.set_notes_visible(True)
        window = self._open_window(note)
        window.present()
        window.view.grab_focus()

    def _delete_window(self, window):
        self.store.remove(window.note.id)
        self.windows.pop(window.note.id, None)
        window.destroy()

    def set_notes_visible(self, visible):
        self.notes_visible = visible
        for window in self.windows.values():
            if visible:
                window.show_all()
                window.present()
            else:
                window.hide()

    # --- трей ---

    def _build_tray(self):
        self.tray = Gtk.StatusIcon.new_from_icon_name("accessories-text-editor")
        self.tray.set_tooltip_text("Стикеры")
        self.tray.connect("activate", lambda _i: self.set_notes_visible(not self.notes_visible))
        self.tray.connect("popup-menu", self._on_tray_menu)

    def _on_tray_menu(self, icon, button, time):
        menu = Gtk.Menu()
        for label, callback in (
            ("Новая заметка", lambda _i: self.new_note()),
            ("Показать все", lambda _i: self.set_notes_visible(True)),
            ("Скрыть все", lambda _i: self.set_notes_visible(False)),
            (None, None),
            ("Выход", lambda _i: self.quit()),
        ):
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem(label=label)
            item.connect("activate", callback)
            menu.append(item)
        menu.show_all()
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)
