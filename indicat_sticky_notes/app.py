"""Приложение: значок в трее, окна заметок, менеджер, настройки, копии и обмен данными."""
import time
import uuid
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import autostart, backup, exchange, theme  # noqa: E402
from .hotkeys import GlobalHotkeys  # noqa: E402
from .manager import ManagerWindow  # noqa: E402
from .note_window import NoteWindow  # noqa: E402
from .settings import Settings  # noqa: E402
from .settings_window import SettingsWindow  # noqa: E402
from .storage import NoteStore  # noqa: E402

APP_ID = "io.github.h0r1ze.IndicatStickyNotes"
ICON_NAME = "indicat-sticky-notes"
FALLBACK_ICON = "accessories-text-editor"
RELOAD_DELAY_MS = 400


class StickyApp(Gtk.Application):
    def __init__(self, store: NoteStore = None, backup_dir=None, settings: Settings = None,
                 use_hotkeys=True):
        super().__init__(application_id=APP_ID)
        self.settings = settings or Settings()
        self.store = store  # None — создаём в setup() по настройкам
        self.backup_dir = backup_dir  # None — папка по умолчанию
        self.use_hotkeys = use_hotkeys
        self.hotkeys = GlobalHotkeys()
        self.hotkey_status = {}  # имя -> True / False / None (отключено)
        self.windows = {}
        self.manager = None
        self.settings_window = None
        self.tray = None
        self._monitor = None
        self._reload_source = None

    # --- запуск и завершение ---

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # живём в трее, даже когда все заметки скрыты
        self.setup()

    def setup(self):
        """Настройки, заметки, автокопия, окна, значок в трее, клавиши, наблюдение за файлом."""
        self.settings.load()
        if self.store is None:
            self.store = NoteStore(self.settings.notes_path())
        theme.install()
        theme.apply_ui_theme(self.settings["theme"])
        theme.set_default_font_size(self.settings["default_font_size"])
        theme.install_icons()
        Gtk.Window.set_default_icon_name(self._icon_name())

        self.store.load()
        self.store.merge_hook = self._sync_windows
        if self.store.corrupt_file:
            GLib.idle_add(self._report_corrupt_file)
        self.store.cleanup(trash_days=self.settings["trash_days"])
        backup.auto_if_due(self.store.notes, self.backup_dir)
        for note in self.store.active_notes:
            self._open_window(note)
        self._build_tray()
        self.settings.listeners.append(self._on_settings_changed)
        self._apply_hotkeys()
        self._watch_data_dir()

    def do_activate(self):
        # Повторный запуск показывает заметки (или создаёт первую).
        if not self.store.active_notes:
            self.new_note()
        else:
            self.show_all()

    def do_shutdown(self):
        for window in self.windows.values():
            window.flush()
        self.hotkeys.stop()
        Gtk.Application.do_shutdown(self)

    def shutdown_services(self):
        """Остановить потоки и наблюдателей (нужно тестам, которые не вызывают do_shutdown)."""
        self.hotkeys.stop()
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
        if self.tray is not None:
            self.tray.set_visible(False)

    def _report_corrupt_file(self):
        self._message(
            "Файл заметок был повреждён",
            f"Он сохранён отдельно: {self.store.corrupt_file}\n"
            "Приложение начало с пустого списка; восстановить заметки можно из резервной копии.",
            Gtk.MessageType.WARNING,
        )
        return False

    def default_font_size(self):
        return self.settings["default_font_size"]

    # --- заметки ---

    def _open_window(self, note):
        window = NoteWindow(note, self)
        self.windows[note.id] = window
        if not note.hidden:
            window.show_all()
        return window

    def new_note(self):
        # Каждая следующая заметка немного смещается, чтобы не лечь ровно поверх.
        offset = 30 * (len(self.store.active_notes) % 8)
        note = self.store.add(x=120 + offset, y=120 + offset, color=self.settings["default_color"])
        window = self._open_window(note)
        window.show_note()
        window.view.grab_focus()

    def _close_window(self, note_id):
        window = self.windows.pop(note_id, None)
        if window is not None:
            window.flush()
            window.destroy()

    def delete_note(self, note_id):
        """Пустая заметка стирается совсем, остальные уходят в корзину."""
        note = self.store.get(note_id)
        if note is None:
            return
        self._close_window(note_id)
        if note.is_blank():
            self.store.purge(note_id)  # без корзины, но «надгробие» не даст ей вернуться при синхронизации
        else:
            self.store.move_to_trash(note_id)

    def restore_note(self, note_id):
        self.store.restore(note_id)
        note = self.store.get(note_id)
        if note is not None and note.active:
            window = self.windows.get(note_id) or self._open_window(note)
            window.show_note()

    def purge_note(self, note_id):
        self.store.purge(note_id)

    def empty_trash(self):
        self.store.empty_trash()

    def show_note(self, note_id, highlight=None):
        if note_id in self.windows:
            self.windows[note_id].show_note(highlight)

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
        """Если что-то видно — спрятать всё, иначе показать всё."""
        if any(not w.note.hidden for w in self.windows.values()):
            self.hide_all()
        else:
            self.show_all()

    def set_group_visible(self, group, visible):
        for window in self.windows.values():
            if window.note.group == group:
                window.show_note() if visible else window.hide_note()

    def replace_notes(self, notes):
        """Заменить все заметки (восстановление из копии)."""
        for window in self.windows.values():
            window.destroy()
        self.windows.clear()
        self.store.replace_all(notes)
        for note in self.store.active_notes:
            self._open_window(note)

    # --- менеджер и настройки ---

    def open_manager(self, focus_search=False):
        if self.manager is None:
            self.manager = ManagerWindow(self)
        self.manager.present_with_search(focus_search)

    def open_search(self):
        self.open_manager(focus_search=True)

    def open_settings(self):
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self)
        self.settings_window.present_window()

    def _on_settings_changed(self, changed):
        if "theme" in changed:
            theme.apply_ui_theme(self.settings["theme"])
        if "default_font_size" in changed:
            theme.set_default_font_size(self.settings["default_font_size"])
        if "trash_days" in changed:
            self.store.cleanup(trash_days=self.settings["trash_days"])
        if "data_dir" in changed:
            self.change_data_dir(self.settings.notes_path())
        if {"hotkey_new", "hotkey_toggle"} & set(changed):
            self._apply_hotkeys()
        if self.manager is not None:
            self.manager.refresh()

    # --- глобальные клавиши ---

    def _apply_hotkeys(self):
        if not self.use_hotkeys:
            return
        wanted = {
            "new": (self.settings["hotkey_new"], self.new_note),
            "toggle": (self.settings["hotkey_toggle"], self.toggle_all),
        }
        results = self.hotkeys.set({k: v for k, v in wanted.items() if v[0]})
        self.hotkey_status = {name: results.get(name) for name in wanted}  # None — отключено

    # --- синхронизация через общую папку ---

    def _watch_data_dir(self):
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
        folder = Gio.File.new_for_path(str(self.store.path.parent))
        try:
            self._monitor = folder.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error:
            return
        self._monitor.connect("changed", self._on_file_event)

    def _on_file_event(self, _monitor, file, other, _event):
        names = {f.get_basename() for f in (file, other) if f is not None}
        if self.store.path.name not in names or self._reload_source is not None:
            return
        self._reload_source = GLib.timeout_add(RELOAD_DELAY_MS, self._reload_idle)

    def _reload_idle(self):
        self._reload_source = None
        self.reload_external()
        return False

    def reload_external(self):
        """Подтянуть изменения, сделанные другим компьютером (или программой) в файле заметок."""
        added, changed = self.store.sync_from_disk()
        if not (added or changed):
            return False
        self.store.save()  # записываем итог слияния; окна обновит merge_hook при записи
        self._sync_windows(added, changed)
        return True

    def _sync_windows(self, added, changed):
        for note_id in added + changed:
            note = self.store.get(note_id)
            window = self.windows.get(note_id)
            if note is None or not note.active:
                if window is not None:
                    self._close_window(note_id)
            elif window is None:
                self._open_window(note)
            else:
                window.refresh_from_note()

    def change_data_dir(self, new_path):
        """Перейти на другой файл заметок: заметки из него сливаются с текущими."""
        new_path = Path(new_path)
        if new_path == self.store.path:
            return
        for window in self.windows.values():
            window.flush()
        added, changed = [], []
        if new_path.exists():
            other = NoteStore(new_path)
            try:
                added, changed = self.store.merge(other.read_disk())
            except (OSError, ValueError):
                pass
        self.store.path = new_path
        self.store.save()
        self._sync_windows(added, changed)
        self._watch_data_dir()

    # --- резервные копии ---

    def _backup_folder(self):
        folder = backup.default_dir() if self.backup_dir is None else Path(self.backup_dir)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def backup_now(self, path=None):
        """Сохранить копию заметок туда, куда укажет пользователь."""
        if not self.store.notes:
            self._message("Копировать нечего", "Заметок пока нет.", Gtk.MessageType.INFO)
            return None
        path = path or self._choose_save_path(
            "Сохранить резервную копию", backup.default_name(), folder=self._backup_folder()
        )
        if path is None:
            return None
        saved = backup.save_to(self.store.notes, path)
        self._message("Копия сохранена", str(saved), Gtk.MessageType.INFO)
        return saved

    def restore_backup(self):
        paths = self._choose_files("Восстановить из копии", "*.json", "Копии заметок (*.json)",
                                   folder=self._backup_folder())
        if paths:
            self.restore_from(paths[0])

    def restore_from(self, path, confirm=True):
        try:
            notes = backup.load(path)
        except ValueError as exc:
            self._message("Не удалось открыть копию", str(exc), Gtk.MessageType.ERROR)
            return False
        if confirm and not self._ask(
            "Восстановить из копии?",
            f"Сейчас заметок: {len(self.store.active_notes)}, в копии: "
            f"{sum(1 for n in notes if n.active)}. Текущие заметки заменятся; "
            "перед этим будет сделана отдельная копия.",
        ):
            return False
        backup.create(self.store.notes, "before-restore", self.backup_dir)
        self.replace_notes(notes)
        return True

    def open_backup_folder(self):
        Gtk.show_uri_on_window(None, self._backup_folder().as_uri(), Gdk.CURRENT_TIME)

    # --- ярлык на рабочем столе ---

    def create_desktop_shortcut(self):
        try:
            path = autostart.create_desktop_shortcut()
        except OSError as exc:
            self._message("Не удалось создать ярлык", str(exc), Gtk.MessageType.ERROR)
            return None
        self._message("Ярлык создан", str(path), Gtk.MessageType.INFO)
        return path

    # --- экспорт и импорт ---

    def export_note(self, note, parent=None):
        """Сохранить одну заметку в файл: .md — с форматированием, иначе простой текст."""
        name = exchange.slug(note.display_title(60)) + ".md"
        path = self._choose_save_path("Сохранить заметку", name, parent)
        if path is None:
            return None
        path = Path(path)
        if path.suffix.lower() == ".md":
            path.write_text(exchange.export_markdown([note]), encoding="utf-8")
        else:
            path.write_text(note.text, encoding="utf-8")
        return path

    def export_markdown(self, path=None):
        """Все заметки одним Markdown-файлом."""
        path = path or self._choose_save_path("Экспорт в Markdown", "стикеры.md")
        if path is None:
            return None
        Path(path).write_text(exchange.export_markdown(self.store.notes), encoding="utf-8")
        self._message("Экспорт готов", str(path), Gtk.MessageType.INFO)
        return Path(path)

    def export_text_folder(self, folder=None):
        """Каждая заметка — отдельный .txt в выбранной папке."""
        folder = folder or self._choose_folder("Папка для .txt файлов")
        if folder is None:
            return []
        paths = exchange.export_text_files(self.store.notes, folder)
        self._message("Экспорт готов", f"Сохранено файлов: {len(paths)}\n{folder}", Gtk.MessageType.INFO)
        return paths

    def import_files(self):
        paths = self._choose_files("Импорт заметок", "*", "Заметки (.json, .md, .txt)",
                                   multiple=True, patterns=("*.json", "*.md", "*.txt"))
        if paths:
            self._report_import(*self.import_paths(paths))

    def import_mint(self):
        path = exchange.default_mint_path()
        if not path.exists():
            self._message("Mint Sticky не найден", f"Нет файла {path}", Gtk.MessageType.INFO)
            return
        self._report_import(*self.import_paths([path]))

    def import_paths(self, paths):
        """Добавить заметки из файлов. Возвращает (сколько добавлено, список ошибок)."""
        added, errors = 0, []
        for path in paths:
            try:
                notes = exchange.read_notes_file(path)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            for note in notes:
                if not note.active or note.is_blank():
                    continue
                note.id = uuid.uuid4().hex
                note.hidden = False
                note.created = note.updated = time.time()
                self.store.notes.append(note)
                self._open_window(note)
                added += 1
        if added:
            self.store.save()
        return added, errors

    def _report_import(self, added, errors):
        text = f"Добавлено заметок: {added}"
        if errors:
            text += "\n\nНе удалось разобрать:\n" + "\n".join(errors)
        self._message("Импорт завершён", text,
                      Gtk.MessageType.WARNING if errors else Gtk.MessageType.INFO)

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

    @staticmethod
    def _choose_files(title, pattern, label, folder=None, multiple=False, patterns=None):
        dialog = Gtk.FileChooserDialog(title=title, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Открыть", Gtk.ResponseType.OK)
        dialog.set_select_multiple(multiple)
        if folder is not None:
            dialog.set_current_folder(str(folder))
        file_filter = Gtk.FileFilter()
        file_filter.set_name(label)
        for item in patterns or (pattern,):
            file_filter.add_pattern(item)
        dialog.add_filter(file_filter)
        paths = dialog.get_filenames() if dialog.run() == Gtk.ResponseType.OK else []
        dialog.destroy()
        return paths

    @staticmethod
    def _choose_save_path(title, name, parent=None, folder=None):
        dialog = Gtk.FileChooserDialog(title=title, action=Gtk.FileChooserAction.SAVE,
                                       transient_for=parent)
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Сохранить", Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        if folder is not None:
            dialog.set_current_folder(str(folder))
        dialog.set_current_name(name)
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return path

    @staticmethod
    def _choose_folder(title):
        dialog = Gtk.FileChooserDialog(title=title, action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Выбрать", Gtk.ResponseType.OK)
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return path

    # --- трей ---

    @staticmethod
    def _icon_name():
        return ICON_NAME if Gtk.IconTheme.get_default().has_icon(ICON_NAME) else FALLBACK_ICON

    def _build_tray(self):
        self.tray = Gtk.StatusIcon.new_from_icon_name(self._icon_name())
        self.tray.set_tooltip_text("Стикеры")
        self.tray.connect("activate", lambda _i: self.on_tray_click())
        self.tray.connect("popup-menu", self._on_tray_menu)

    def on_tray_click(self):
        if self.settings["tray_click"] == "manager":
            self.open_manager()
        else:
            self.toggle_all()

    def _on_tray_menu(self, icon, button, time_):
        menu = self.build_tray_menu()
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time_)

    def build_tray_menu(self):
        menu = Gtk.Menu()

        def action(parent, label, callback):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i: callback())
            parent.append(item)
            return item

        def submenu(label):
            sub = Gtk.Menu()
            head = Gtk.MenuItem(label=label)
            head.set_submenu(sub)
            menu.append(head)
            return sub

        def separator():
            menu.append(Gtk.SeparatorMenuItem())

        action(menu, "Новая заметка", self.new_note)
        action(menu, "Найти заметку…", self.open_search)
        action(menu, "Менеджер заметок…", self.open_manager)
        separator()
        action(menu, "Показать все", self.show_all)
        action(menu, "Скрыть все", self.hide_all)

        groups = self.store.groups()
        if groups:
            groups_menu = submenu("Группы")
            for name in groups:
                head = Gtk.MenuItem(label=name)
                sub = Gtk.Menu()
                action(sub, "Показать группу", lambda n=name: self.set_group_visible(n, True))
                action(sub, "Скрыть группу", lambda n=name: self.set_group_visible(n, False))
                head.set_submenu(sub)
                groups_menu.append(head)
        separator()

        exchange_menu = submenu("Обмен данными")
        action(exchange_menu, "Экспорт в Markdown…", self.export_markdown)
        action(exchange_menu, "Экспорт в папку (.txt)…", self.export_text_folder)
        exchange_menu.append(Gtk.SeparatorMenuItem())
        action(exchange_menu, "Импорт из файлов…", self.import_files)
        action(exchange_menu, "Импорт из Mint Sticky", self.import_mint)

        backups = submenu("Резервные копии")
        action(backups, "Создать копию сейчас", self.backup_now)
        action(backups, "Восстановить из копии…", self.restore_backup)
        action(backups, "Открыть папку копий", self.open_backup_folder)

        startup = Gtk.CheckMenuItem(label="Запускать при входе")
        startup.set_active(autostart.is_enabled())
        startup.connect("toggled", lambda item: autostart.set_enabled(item.get_active()))
        menu.append(startup)
        action(menu, "Создать ярлык на рабочем столе", self.create_desktop_shortcut)
        action(menu, "Настройки…", self.open_settings)

        separator()
        action(menu, "Выход", self.quit)
        menu.show_all()
        return menu
