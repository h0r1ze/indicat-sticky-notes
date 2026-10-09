"""Приложение: значок в трее, окна заметок, менеджер и резервные копии."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import autostart, backup  # noqa: E402
from .manager import ManagerWindow  # noqa: E402
from .note_window import NoteWindow  # noqa: E402
from .storage import NoteStore  # noqa: E402

APP_ID = "io.github.h0r1ze.IndicatStickyNotes"


class StickyApp(Gtk.Application):
    def __init__(self, store: NoteStore = None, backup_dir=None):
        super().__init__(application_id=APP_ID)
        self.store = store or NoteStore()
        self.backup_dir = backup_dir  # None — папка по умолчанию
        self.windows = {}
        self.manager = None
        self.tray = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # живём в трее, даже когда все заметки скрыты
        self.setup()

    def setup(self):
        """Загрузить заметки, сделать автокопию, открыть окна и значок в трее."""
        self.store.load()
        backup.auto_if_due(self.store.notes, self.backup_dir)
        for note in self.store.notes:
            self._open_window(note)
        self._build_tray()

    def do_activate(self):
        # Повторный запуск показывает заметки (или создаёт первую).
        if not self.store.notes:
            self.new_note()
        else:
            self.show_all()

    def do_shutdown(self):
        for window in self.windows.values():
            window.flush()
        Gtk.Application.do_shutdown(self)

    # --- заметки ---

    def _open_window(self, note):
        window = NoteWindow(note, self.store, self.new_note, self._delete_window)
        self.windows[note.id] = window
        if not note.hidden:
            window.show_all()
        return window

    def new_note(self):
        # Каждая следующая заметка немного смещается, чтобы не лечь ровно поверх.
        offset = 30 * (len(self.store.notes) % 8)
        note = self.store.add(x=120 + offset, y=120 + offset)
        window = self._open_window(note)
        window.show_note()
        window.view.grab_focus()

    def _delete_window(self, window):
        self.delete_note(window.note.id)

    def delete_note(self, note_id):
        window = self.windows.pop(note_id, None)
        self.store.remove(note_id)
        if window is not None:
            window.destroy()

    def show_note(self, note_id):
        if note_id in self.windows:
            self.windows[note_id].show_note()

    def hide_note(self, note_id):
        if note_id in self.windows:
            self.windows[note_id].hide_note()

    def show_all(self):
        for window in self.windows.values():
            window.show_note()

    def hide_all(self):
        for window in self.windows.values():
            window.hide_note()

    def toggle_all(self):
        """Клик по значку: если что-то видно — спрятать всё, иначе показать всё."""
        if any(not w.note.hidden for w in self.windows.values()):
            self.hide_all()
        else:
            self.show_all()

    def replace_notes(self, notes):
        """Заменить все заметки (восстановление из копии)."""
        for window in self.windows.values():
            window.destroy()
        self.windows.clear()
        self.store.replace_all(notes)
        for note in self.store.notes:
            self._open_window(note)

    # --- менеджер ---

    def open_manager(self, focus_search=False):
        if self.manager is None:
            self.manager = ManagerWindow(self)
        self.manager.present_with_search(focus_search)

    # --- резервные копии ---

    def backup_now(self):
        path = backup.create(self.store.notes, "manual", self.backup_dir)
        if path is None:
            self._message("Копировать нечего", "Заметок пока нет.", Gtk.MessageType.INFO)
        else:
            self._message("Копия создана", str(path), Gtk.MessageType.INFO)
        return path

    def restore_backup(self):
        dialog = Gtk.FileChooserDialog(
            title="Восстановить из копии",
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Открыть", Gtk.ResponseType.OK)
        folder = backup.default_dir() if self.backup_dir is None else self.backup_dir
        folder.mkdir(parents=True, exist_ok=True)
        dialog.set_current_folder(str(folder))
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Копии заметок (*.json)")
        file_filter.add_pattern("*.json")
        dialog.add_filter(file_filter)
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        if path:
            self.restore_from(path)

    def restore_from(self, path, confirm=True):
        try:
            notes = backup.load(path)
        except ValueError as exc:
            self._message("Не удалось открыть копию", str(exc), Gtk.MessageType.ERROR)
            return False
        if confirm and not self._ask(
            "Восстановить из копии?",
            f"Сейчас заметок: {len(self.store.notes)}, в копии: {len(notes)}. "
            "Текущие заметки заменятся; перед этим будет сделана отдельная копия.",
        ):
            return False
        backup.create(self.store.notes, "before-restore", self.backup_dir)
        self.replace_notes(notes)
        return True

    def open_backup_folder(self):
        folder = backup.default_dir() if self.backup_dir is None else self.backup_dir
        folder.mkdir(parents=True, exist_ok=True)
        Gtk.show_uri_on_window(None, folder.as_uri(), Gdk.CURRENT_TIME)

    # --- диалоги ---

    @staticmethod
    def _message(title, text, kind):
        dialog = Gtk.MessageDialog(
            message_type=kind, buttons=Gtk.ButtonsType.OK, text=title, secondary_text=text
        )
        dialog.run()
        dialog.destroy()

    @staticmethod
    def _ask(title, text):
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=title,
            secondary_text=text,
        )
        answer = dialog.run()
        dialog.destroy()
        return answer == Gtk.ResponseType.YES

    # --- трей ---

    def _build_tray(self):
        self.tray = Gtk.StatusIcon.new_from_icon_name("accessories-text-editor")
        self.tray.set_tooltip_text("Стикеры")
        self.tray.connect("activate", lambda _i: self.toggle_all())
        self.tray.connect("popup-menu", self._on_tray_menu)

    def _on_tray_menu(self, icon, button, time):
        menu = self.build_tray_menu()
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def build_tray_menu(self):
        menu = Gtk.Menu()

        def action(parent, label, callback):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i: callback())
            parent.append(item)
            return item

        action(menu, "Новая заметка", self.new_note)
        action(menu, "Менеджер заметок…", self.open_manager)
        menu.append(Gtk.SeparatorMenuItem())
        action(menu, "Показать все", self.show_all)
        action(menu, "Скрыть все", self.hide_all)
        menu.append(Gtk.SeparatorMenuItem())

        backups = Gtk.Menu()
        action(backups, "Создать копию сейчас", self.backup_now)
        action(backups, "Восстановить из копии…", self.restore_backup)
        action(backups, "Открыть папку копий", self.open_backup_folder)
        backups_item = Gtk.MenuItem(label="Резервные копии")
        backups_item.set_submenu(backups)
        menu.append(backups_item)

        startup = Gtk.CheckMenuItem(label="Запускать при входе")
        startup.set_active(autostart.is_enabled())
        startup.connect("toggled", lambda item: autostart.set_enabled(item.get_active()))
        menu.append(startup)

        menu.append(Gtk.SeparatorMenuItem())
        action(menu, "Выход", self.quit)
        menu.show_all()
        return menu
