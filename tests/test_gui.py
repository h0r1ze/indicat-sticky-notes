"""Сквозные проверки интерфейса. Нужен дисплей (например, xvfb-run), иначе пропускаются."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    HAVE_DISPLAY = Gtk.init_check()[0]
except (ImportError, ValueError):
    HAVE_DISPLAY = False

if HAVE_DISPLAY:
    from indicat_sticky_notes import backup, checklist, exchange
    from indicat_sticky_notes.app import StickyApp
    from indicat_sticky_notes.manager import ALL_GROUPS, NO_GROUP
    from indicat_sticky_notes.settings import Settings
    from indicat_sticky_notes.storage import Note, NoteStore


def pump(seconds=0.15):
    end = time.time() + seconds
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.01)


def key(keyval, state=0):
    event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    event.keyval = keyval
    event.state = state
    return event


@unittest.skipUnless(HAVE_DISPLAY, "нет дисплея")
class GuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = NoteStore(root / "notes.json")
        self.backups = root / "backups"
        self.settings = Settings(root / "config" / "settings.json")
        self.app = StickyApp(self.store, self.backups, settings=self.settings, use_hotkeys=False)
        self.app._message = lambda *a, **k: None  # без модальных окон в тестах

    def tearDown(self):
        for window in list(self.app.windows.values()):
            window.destroy()
        for extra in (self.app.manager, self.app.settings_window):
            if extra:
                extra.destroy()
        self.app.shutdown_services()
        self.tmp.cleanup()

    def start(self, *notes):
        for kwargs in notes:
            self.store.add(**kwargs)
        self.app.setup()  # то же, что делает do_startup, без регистрации в D-Bus
        pump()
        return [self.app.windows[n.id] for n in self.store.notes]

    def text_of(self, window):
        buffer = window.view.get_buffer()
        return buffer.get_text(*buffer.get_bounds(), True)

    def put_text(self, window, text):
        buffer = window.view.get_buffer()
        buffer.set_text(text)
        buffer.place_cursor(buffer.get_end_iter())
        pump()

    # --- запуск и скрытие ---

    def test_startup_shows_visible_and_keeps_hidden_hidden(self):
        shown, hidden = self.start({"text": "a"}, {"text": "b", "hidden": True})
        self.assertTrue(shown.get_visible())
        self.assertFalse(hidden.get_visible())

    def test_hide_and_show_are_persisted(self):
        (window,) = self.start({"text": "a"})
        window.hide_note()
        reloaded = NoteStore(self.store.path)
        reloaded.load()
        self.assertTrue(reloaded.notes[0].hidden)
        window.show_note()
        pump(0.7)
        reloaded.load()
        self.assertFalse(reloaded.notes[0].hidden)

    def test_toggle_all(self):
        a, b = self.start({"text": "a"}, {"text": "b"})
        self.app.toggle_all()
        self.assertFalse(a.get_visible() or b.get_visible())
        self.app.toggle_all()
        self.assertTrue(a.get_visible() and b.get_visible())

    # --- закрепление ---

    def test_pin_toggles_and_persists(self):
        (window,) = self.start({"text": "a"})
        window.pin_button.clicked()
        self.assertTrue(window.note.pinned)
        self.assertTrue(window.pin_button.get_style_context().has_class("active"))
        window.flush()
        reloaded = NoteStore(self.store.path)
        reloaded.load()
        self.assertTrue(reloaded.notes[0].pinned)
        window.pin_button.clicked()
        self.assertFalse(window.note.pinned)

    def test_pinned_note_starts_pinned(self):
        (window,) = self.start({"text": "a", "pinned": True})
        self.assertTrue(window.pin_button.get_style_context().has_class("active"))

    # --- чекбоксы ---

    def test_typed_marker_becomes_checkbox(self):
        (window,) = self.start({})
        self.put_text(window, "[ ] молоко")
        self.assertEqual(self.text_of(window), "☐ молоко")
        self.put_text(window, "x\n[x] сделано")
        self.assertEqual(self.text_of(window), "x\n☑ сделано")

    def test_enter_continues_list_and_empty_item_ends_it(self):
        (window,) = self.start({})
        self.put_text(window, "☐ первое")
        self.assertTrue(window._on_key_press(window.view, key(Gdk.KEY_Return)))
        self.assertEqual(self.text_of(window), "☐ первое\n☐ ")
        self.assertTrue(window._on_key_press(window.view, key(Gdk.KEY_Return)))
        self.assertEqual(self.text_of(window), "☐ первое\n")
        self.assertFalse(window._on_key_press(window.view, key(Gdk.KEY_Return)))  # обычный Enter

    def test_ctrl_l_adds_and_removes_checkbox(self):
        (window,) = self.start({})
        self.put_text(window, "дело")
        window._on_key_press(window.view, key(Gdk.KEY_l, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.text_of(window), "☐ дело")
        window._on_key_press(window.view, key(Gdk.KEY_l, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.text_of(window), "дело")

    def test_ctrl_l_on_selection_handles_every_line(self):
        (window,) = self.start({})
        self.put_text(window, "a\nb\nc")
        buffer = window.view.get_buffer()
        buffer.select_range(buffer.get_start_iter(), buffer.get_end_iter())
        window.toggle_checklist()
        self.assertEqual(self.text_of(window), "☐ a\n☐ b\n☐ c")

    def test_click_on_box_toggles_and_strikes_through(self):
        (window,) = self.start({"text": "☐ купить"})
        pump(0.3)
        view = window.view
        start = view.get_buffer().get_start_iter()
        rect = view.get_iter_location(start)
        wx, wy = view.buffer_to_window_coords(Gtk.TextWindowType.TEXT, rect.x + 2, rect.y + 2)
        raw = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)  # держим ссылку, иначе событие освободится
        event = raw.button
        event.button, event.x, event.y = 1, wx, wy
        self.assertTrue(window._on_view_press(view, event))
        pump()
        self.assertEqual(self.text_of(window), "☑ купить")
        buffer = view.get_buffer()
        text_start = buffer.get_iter_at_offset(3)
        self.assertTrue(text_start.has_tag(window.done_tag))  # зачёркнуто
        self.assertFalse(buffer.get_start_iter().has_tag(window.done_tag))  # сам квадратик нет
        # клик по обычному тексту ничего не делает
        far_x, far_y = view.buffer_to_window_coords(Gtk.TextWindowType.TEXT, rect.x + 60, rect.y + 2)
        event.x, event.y = far_x, far_y
        self.assertFalse(window._on_view_press(view, event))

    # --- менеджер ---

    def test_manager_lists_filters_and_deletes(self):
        self.start({"text": "Молоко и хлеб"}, {"text": "Позвонить маме", "hidden": True})
        self.app.open_manager()
        pump()
        manager = self.app.manager
        self.assertEqual(len(manager.model), 2)
        manager.search.set_text("позвон")
        manager.refresh()
        self.assertEqual([r[2] for r in manager.model], ["Позвонить маме"])
        self.assertIn("1 из 2", manager.status.get_text())
        manager.search.set_text("")
        manager.refresh()
        self.assertEqual(len(manager.model), 2)
        states = {r[2]: r[4] for r in manager.model}
        self.assertEqual(states["Позвонить маме"], "скрыта")
        note_id = self.store.notes[0].id
        self.app.delete_note(note_id)
        pump()
        self.assertEqual(len(manager.model), 1)
        self.assertNotIn(note_id, self.app.windows)

    def test_manager_show_selected_reveals_hidden_note(self):
        (window,) = self.start({"text": "скрытая", "hidden": True})
        self.app.open_manager()
        pump()
        manager = self.app.manager
        manager.tree.get_selection().select_path(Gtk.TreePath.new_first())
        manager._show_selected()
        self.assertTrue(window.get_visible())
        self.assertFalse(window.note.hidden)

    # --- резервные копии ---

    def test_backup_now_and_restore(self):
        self.start({"text": "важное"})
        chosen = Path(self.tmp.name) / "my-backup.json"
        self.app._choose_save_path = lambda *a, **k: str(chosen)
        path = self.app.backup_now()
        self.assertEqual(path, chosen)
        self.assertTrue(path.exists())
        # портим состояние и восстанавливаем
        for note_id in [n.id for n in self.store.notes]:
            self.app.delete_note(note_id)
        self.app.new_note()
        self.assertEqual([n.text for n in self.store.active_notes], [""])
        self.assertTrue(self.app.restore_from(path, confirm=False))
        pump()
        self.assertEqual([n.text for n in self.store.notes], ["важное"])
        self.assertEqual(len(self.app.windows), 1)
        reasons = {b.reason for b in backup.list_backups(self.backups)}
        self.assertEqual(reasons, {"auto", "before-restore"})  # ручная копия лежит там, куда её сохранили

    def test_restore_rejects_garbage_and_keeps_notes(self):
        self.start({"text": "остаётся"})
        errors = []
        self.app._message = lambda title, text, kind: errors.append(title)
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("не json")
        self.assertFalse(self.app.restore_from(bad, confirm=False))
        self.assertEqual(errors, ["Не удалось открыть копию"])
        self.assertEqual([n.text for n in self.store.notes], ["остаётся"])

    def test_startup_makes_auto_backup_once(self):
        self.start({"text": "a"})
        self.assertEqual([b.reason for b in backup.list_backups(self.backups)], ["auto"])

    # --- меню трея ---

    def test_tray_menu_has_expected_entries(self):
        self.start({"text": "a"})
        menu = self.app.build_tray_menu()
        labels = [i.get_label() for i in menu.get_children()
                  if isinstance(i, Gtk.MenuItem) and not isinstance(i, Gtk.SeparatorMenuItem)]
        self.assertEqual(labels, [
            "Новая заметка", "Найти заметку…", "Менеджер заметок…", "Показать все", "Скрыть все",
            "Обмен данными", "Резервные копии", "Запускать при входе",
            "Создать ярлык на рабочем столе", "Настройки…", "Справка   F1", "О программе", "Выход"])

    def test_tray_menu_lists_groups_when_present(self):
        self.start({"text": "a", "group": "Работа"})
        menu = self.app.build_tray_menu()  # держим ссылку: иначе меню уничтожится раньше времени
        labels = [i.get_label() for i in menu.get_children() if isinstance(i, Gtk.MenuItem)]
        self.assertIn("Группы", labels)

    def test_tray_click_follows_setting(self):
        (window,) = self.start({"text": "a"})
        self.app.on_tray_click()
        self.assertFalse(window.get_visible())  # toggle по умолчанию
        self.settings.update(tray_click="manager")
        self.app.on_tray_click()
        self.assertTrue(self.app.manager.get_visible())



def double_click():
    raw = Gdk.Event.new(Gdk.EventType.DOUBLE_BUTTON_PRESS)
    event = raw.button
    event.button = 1
    return raw, event


@unittest.skipUnless(HAVE_DISPLAY, "нет дисплея")
class GuiStage2Test(GuiTest):
    """Те же стенд и вспомогательные функции, но проверяем возможности второго этапа."""

    # Наследование нужно ради setUp/tearDown/start; унаследованные тесты не повторяем.
    def run(self, result=None):
        if type(self) is GuiStage2Test and self._testMethodName in dir(GuiTest) \
                and self._testMethodName not in vars(GuiStage2Test):
            return None
        return super().run(result)

    # --- корзина ---

    def test_delete_moves_to_trash_blank_is_erased(self):
        full, blank = self.start({"text": "важное"}, {"text": ""})
        self.app.delete_note(blank.note.id)
        self.app.delete_note(full.note.id)
        self.assertEqual(self.app.windows, {})
        self.assertEqual([n.text for n in self.store.notes if not n.purged], ["важное"])
        self.assertTrue(self.store.get(full.note.id).in_trash)
        self.assertTrue(self.store.get(blank.note.id).purged)  # пустая: без корзины, но с «надгробием»

    def test_restore_reopens_window_and_purge_forgets(self):
        (window,) = self.start({"text": "вернусь"})
        note_id = window.note.id
        self.app.delete_note(note_id)
        self.app.restore_note(note_id)
        self.assertTrue(self.app.windows[note_id].get_visible())
        self.app.delete_note(note_id)
        self.app.purge_note(note_id)
        self.assertTrue(self.store.get(note_id).purged)
        self.assertNotIn(note_id, self.app.windows)

    def test_manager_trash_page(self):
        (window,) = self.start({"text": "корзинная"}, )
        self.app.delete_note(window.note.id)
        self.app.open_manager()
        pump()
        manager = self.app.manager
        self.assertEqual(len(manager.model), 0)
        self.assertEqual([r[2] for r in manager.trash_model], ["корзинная"])
        self.assertEqual(manager.stack.child_get_property(manager.trash_page, "title"), "Корзина (1)")
        manager.trash_tree.get_selection().select_path(Gtk.TreePath.new_first())
        manager._restore_selected()
        pump()
        self.assertEqual(len(manager.model), 1)
        self.assertEqual(len(manager.trash_model), 0)

    def test_pending_save_of_deleted_note_does_not_crash(self):
        (window,) = self.start({"text": "a"})
        self.put_text(window, "правка")  # запись ещё отложена
        self.app.delete_note(window.note.id)
        pump(0.8)  # таймер сохранения не должен трогать уничтоженное окно
        self.assertTrue(self.store.notes[0].in_trash)
        self.assertEqual(self.store.notes[0].text, "правка")

    # --- группы ---

    def test_group_menu_and_filter_and_visibility(self):
        a, b, c = self.start({"text": "a", "group": "Работа"}, {"text": "b", "group": "Работа"},
                             {"text": "c"})
        self.app.open_manager()
        manager = self.app.manager
        pump()
        self.assertEqual([r[0] for r in manager.group_combo.get_model()][:3],
                         ["Все группы", "Без группы", "Работа"])
        manager.group_combo.set_active_id("Работа")
        pump()
        self.assertEqual(len(manager.model), 2)
        manager.group_combo.set_active_id(NO_GROUP)
        pump()
        self.assertEqual([r[2] for r in manager.model], ["c"])
        self.app.set_group_visible("Работа", False)
        self.assertFalse(a.get_visible() or b.get_visible())
        self.assertTrue(c.get_visible())
        self.app.set_group_visible("Работа", True)
        self.assertTrue(a.get_visible() and b.get_visible())

    def test_manager_shows_every_note_by_default_and_ids_differ(self):
        """Регрессия: оба идентификатора содержали NUL, превращались в "" и «Все группы» прятали сгруппированные."""
        self.start({"text": "a", "group": "Работа"}, {"text": "b", "group": "Дом"}, {"text": "c"})
        self.assertNotEqual(ALL_GROUPS, NO_GROUP)
        self.assertTrue(ALL_GROUPS and NO_GROUP and "\0" not in ALL_GROUPS + NO_GROUP)
        self.app.open_manager()
        pump()
        manager = self.app.manager
        self.assertEqual(manager.group_combo.get_active_id(), ALL_GROUPS)
        self.assertIsNone(manager.current_group())
        self.assertEqual(len(manager.model), 3)
        self.assertEqual(manager.status.get_text(), "Заметок: 3")

    def test_collapsed_note_has_rounded_class(self):
        (window,) = self.start({"text": "a"})
        style = window.card.get_style_context()
        window.set_collapsed(True)
        self.assertTrue(style.has_class("collapsed"))
        window.set_collapsed(False)
        self.assertFalse(style.has_class("collapsed"))

    def test_window_menu_sets_group(self):
        (window,) = self.start({"text": "a"})
        window.set_group("  Дом ")
        self.assertEqual(window.note.group, "Дом")
        menu = window.build_menu()
        labels = [i.get_label() for i in menu.get_children() if isinstance(i, Gtk.MenuItem)]
        self.assertEqual(labels[:2], ["Заголовок…", "Свернуть"])
        self.assertIn("Группа", labels)

    # --- форматирование ---

    def test_format_selection_persists_and_reloads(self):
        (window,) = self.start({"text": "привет мир"})
        buffer = window.view.get_buffer()
        buffer.select_range(buffer.get_iter_at_offset(0), buffer.get_iter_at_offset(6))
        window.toggle_format("bold")
        self.assertEqual(window.collect_formats(), [[0, 6, "bold"]])
        window.toggle_format("bold")  # повторно — снять
        self.assertEqual(window.collect_formats(), [])
        window.toggle_format("bold")
        buffer.select_range(buffer.get_iter_at_offset(7), buffer.get_iter_at_offset(10))
        window.toggle_format("italic")
        window.flush()
        reloaded = NoteStore(self.store.path)
        reloaded.load()
        self.assertEqual(reloaded.notes[0].formats, [[0, 6, "bold"], [7, 10, "italic"]])
        # новое окно по этим данным показывает форматирование
        clone = type(window)(reloaded.notes[0], self.app)
        tag = clone.view.get_buffer().get_tag_table().lookup("bold")
        self.assertTrue(clone.view.get_buffer().get_iter_at_offset(2).has_tag(tag))
        self.assertFalse(clone.view.get_buffer().get_iter_at_offset(8).has_tag(tag))
        clone.destroy()

    def test_format_without_selection_applies_to_next_typed_text(self):
        (window,) = self.start({})
        self.put_text(window, "abc")
        window.toggle_format("bold")
        window.view.get_buffer().insert_at_cursor("XY")
        pump()
        self.assertEqual(window.collect_formats(), [[3, 5, "bold"]])
        window.toggle_format("bold")  # выключить для дальнейшего ввода
        window.view.get_buffer().insert_at_cursor("Z")
        pump()
        self.assertEqual(window.collect_formats(), [[3, 5, "bold"]])

    def test_typing_format_is_dropped_when_cursor_moves_away(self):
        (window,) = self.start({})
        self.put_text(window, "abc")
        buffer = window.view.get_buffer()
        window.toggle_format("italic")
        buffer.place_cursor(buffer.get_start_iter())
        buffer.insert_at_cursor("X")
        pump()
        self.assertEqual(window.collect_formats(), [])

    def test_shortcuts_work_in_russian_layout(self):
        (window,) = self.start({"text": "слово"})
        buffer = window.view.get_buffer()
        found, keys = Gdk.Keymap.get_default().get_entries_for_keyval(Gdk.KEY_b)
        self.assertTrue(found)
        ctrl = Gdk.ModifierType.CONTROL_MASK
        buffer.select_range(buffer.get_start_iter(), buffer.get_end_iter())
        event = key(Gdk.KEY_Cyrillic_i, ctrl)       # «и» на клавише B
        event.hardware_keycode = keys[0].keycode
        self.assertTrue(window._on_key_press(window.view, event))
        self.assertEqual(window.collect_formats(), [[0, 5, "bold"]])
        event = key(Gdk.KEY_b, ctrl)                # и обычная латинская
        self.assertTrue(window._on_key_press(window.view, event))
        self.assertEqual(window.collect_formats(), [])

    # --- заголовок, сворачивание, прозрачность, шрифт ---

    def test_title_label_and_collapsed_preview(self):
        (window,) = self.start({"text": "первая строка\nвторая"})
        self.assertEqual(window.title_label.get_text(), "")
        window.set_collapsed(True)
        self.assertEqual(window.title_label.get_text(), "первая строка")
        window.set_title_text("  Мой заголовок ")
        self.assertEqual(window.title_label.get_text(), "Мой заголовок")
        self.assertEqual(window.note.title, "Мой заголовок")

    def test_double_click_collapses_and_expands_keeping_height(self):
        (window,) = self.start({"text": "a", "width": 300, "height": 260})
        pump(0.3)
        raw, event = double_click()
        self.assertTrue(window._on_bar_press(None, event))
        pump(0.3)
        self.assertTrue(window.note.collapsed)
        self.assertFalse(window.body.get_visible())
        self.assertLess(window.get_size()[1], 100)
        self.assertEqual(window.note.height, 260)  # настоящая высота не потеряна
        self.assertTrue(window._on_bar_press(None, event))
        pump(0.3)
        self.assertFalse(window.note.collapsed)
        self.assertGreaterEqual(window.get_size()[1], 200)

    def test_collapsed_state_persists(self):
        (window,) = self.start({"text": "a"})
        window.set_collapsed(True)
        window.flush()
        reloaded = NoteStore(self.store.path)
        reloaded.load()
        self.assertTrue(reloaded.notes[0].collapsed)

    def test_opacity(self):
        (window,) = self.start({"text": "a"})
        window.set_note_opacity(0.6)
        self.assertAlmostEqual(window.get_opacity(), 0.6, places=1)
        window.flush()
        reloaded = NoteStore(self.store.path)
        reloaded.load()
        self.assertEqual(reloaded.notes[0].opacity, 0.6)
        window.note.opacity = 7  # мусор в данных не должен ломать окно
        self.assertEqual(window._valid_opacity(), 1.0)

    def test_font_size_steps_clamps_and_resets(self):
        (window,) = self.start({"text": "a"})
        base = self.settings["default_font_size"]
        window.change_font(+1)
        self.assertEqual(window.note.font_size, base + 1)
        for _ in range(100):
            window.change_font(+1)
        self.assertEqual(window.note.font_size, 40)
        for _ in range(100):
            window.change_font(-1)
        self.assertEqual(window.note.font_size, 8)
        window.change_font(0)
        self.assertEqual(window.note.font_size, 0)
        self.assertEqual(window.effective_font_size(), base)

    def test_ctrl_wheel_changes_font(self):
        (window,) = self.start({"text": "a"})
        raw = Gdk.Event.new(Gdk.EventType.SCROLL)
        event = raw.scroll
        event.direction, event.state = Gdk.ScrollDirection.UP, Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(window._on_scroll(window.view, event))
        self.assertEqual(window.note.font_size, self.settings["default_font_size"] + 1)
        event.state = 0
        self.assertFalse(window._on_scroll(window.view, event))  # без Ctrl — обычная прокрутка

    # --- поиск и подсветка ---

    def test_highlight_marks_all_matches_and_clears_on_edit(self):
        (window,) = self.start({"text": "Молоко и молоко"})
        self.assertEqual(window.highlight("МОЛОКО"), 2)
        buffer = window.view.get_buffer()
        self.assertTrue(buffer.get_iter_at_offset(1).has_tag(window.found_tag))
        self.assertFalse(buffer.get_iter_at_offset(7).has_tag(window.found_tag))
        self.assertEqual(window.highlight("нет такого"), 0)
        window.highlight("молоко")
        buffer.insert_at_cursor("!")
        pump()
        self.assertFalse(buffer.get_iter_at_offset(1).has_tag(window.found_tag))

    def test_manager_show_highlights_search_text(self):
        (window,) = self.start({"text": "купить хлеб", "hidden": True})
        self.app.open_manager()
        manager = self.app.manager
        manager.search.set_text("хлеб")
        manager.refresh()
        manager.tree.get_selection().select_path(Gtk.TreePath.new_first())
        manager._show_selected()
        self.assertTrue(window.get_visible())
        self.assertTrue(window.view.get_buffer().get_iter_at_offset(8).has_tag(window.found_tag))

    # --- настройки ---

    def test_new_note_uses_default_color_and_font_setting(self):
        self.start()
        self.settings.update(default_color="graphite", default_font_size=18)
        self.app.new_note()
        self.assertEqual(self.store.notes[-1].color, "graphite")
        self.assertEqual(list(self.app.windows.values())[-1].effective_font_size(), 18)

    def test_trash_days_setting_applies_immediately(self):
        (window,) = self.start({"text": "x"})
        note = window.note
        self.app.delete_note(note.id)
        note.deleted_at = time.time() - 5 * 86400
        self.settings.update(trash_days=3)
        self.assertTrue(note.purged)

    def test_settings_window_controls_write_settings(self):
        self.start()
        self.app.open_settings()
        window = self.app.settings_window
        window.theme_combo.set_active_id("dark")
        window.font_spin.set_value(17)
        window.tray_combo.set_active_id("manager")
        self.assertEqual((self.settings["theme"], self.settings["default_font_size"],
                          self.settings["tray_click"]), ("dark", 17, "manager"))
        self.settings.update(theme="system")
        self.assertEqual(window.theme_combo.get_active_id(), "system")  # окно следит за настройками

    def test_hotkey_capture_in_settings_window(self):
        self.start()
        self.app.open_settings()
        window = self.app.settings_window
        ctrl_alt = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK
        window._start_capture("hotkey_new")
        self.assertTrue(window._on_key_press(window, key(Gdk.KEY_k, ctrl_alt)))
        self.assertEqual(self.settings["hotkey_new"], "<Primary><Alt>k")
        window._start_capture("hotkey_new")
        window._on_key_press(window, key(Gdk.KEY_k, 0))          # без модификатора — не принимаем
        self.assertEqual(self.settings["hotkey_new"], "<Primary><Alt>k")
        window._start_capture("hotkey_new")
        window._on_key_press(window, key(Gdk.KEY_Escape, 0))      # отмена
        self.assertEqual(self.settings["hotkey_new"], "<Primary><Alt>k")
        window._start_capture("hotkey_new")
        window._on_key_press(window, key(Gdk.KEY_BackSpace, 0))   # отключить
        self.assertEqual(self.settings["hotkey_new"], "")

    # --- синхронизация ---

    def external_store(self):
        other = NoteStore(self.store.path)
        other.load()
        return other

    def test_external_edit_is_merged_into_open_window(self):
        (window,) = self.start({"text": "было", "x": 11, "y": 22})
        self.assertFalse(self.app.reload_external())  # собственные записи не считаются внешними
        other = self.external_store()
        other.notes[0].text, other.notes[0].color = "стало", "blue"
        other.notes[0].updated = time.time() + 100
        other.notes[0].x = 999  # чужая позиция окна не должна переехать к нам
        other.save()
        self.assertTrue(self.app.reload_external())
        self.assertEqual(self.text_of(window), "стало")
        self.assertEqual(window.note.color, "blue")
        self.assertEqual(window.note.x, 11)

    def test_external_new_and_deleted_notes(self):
        (window,) = self.start({"text": "моя"})
        other = self.external_store()
        newcomer = other.add(text="пришла с другого компьютера")
        self.assertTrue(self.app.reload_external())
        self.assertIn(newcomer.id, self.app.windows)
        mine = other.get(window.note.id)
        other.purge(mine.id)
        self.assertTrue(self.app.reload_external())
        self.assertNotIn(window.note.id, self.app.windows)

    def test_file_monitor_triggers_reload(self):
        (window,) = self.start({"text": "было"})
        other = self.external_store()
        other.notes[0].text, other.notes[0].updated = "по сети", time.time() + 100
        other.save()
        pump(1.5)  # наблюдатель + задержка перезагрузки
        self.assertEqual(self.text_of(window), "по сети")

    def test_change_data_dir_merges_and_moves(self):
        (window,) = self.start({"text": "локальная"})
        target = Path(self.tmp.name) / "shared"
        target.mkdir()
        remote = NoteStore(target / "notes.json")
        remote_note = remote.add(text="из общей папки")
        self.settings.update(data_dir=str(target))
        self.assertEqual(self.store.path, target / "notes.json")
        self.assertEqual({n.text for n in self.store.active_notes}, {"локальная", "из общей папки"})
        self.assertIn(remote_note.id, self.app.windows)
        saved = NoteStore(target / "notes.json")
        saved.load()
        self.assertEqual(len(saved.notes), 2)  # итог записан в новую папку

    # --- импорт и экспорт ---

    def test_import_paths_adds_notes_with_new_ids_and_reports_errors(self):
        self.start({"text": "своя"})
        root = Path(self.tmp.name)
        (root / "идеи.txt").write_text("текст идеи", encoding="utf-8")
        (root / "m.json").write_text('{"Работа": [{"title": "Отчёт", "text": "#check:1 готов"}]}',
                                     encoding="utf-8")
        (root / "bad.json").write_text("{не json", encoding="utf-8")
        added, errors = self.app.import_paths([root / "идеи.txt", root / "m.json", root / "bad.json"])
        self.assertEqual(added, 2)
        self.assertEqual(len(errors), 1)
        texts = {n.text for n in self.store.active_notes}
        self.assertEqual(texts, {"своя", "текст идеи", "☑ готов"})
        self.assertEqual(len({n.id for n in self.store.notes}), 3)
        self.assertEqual(len(self.app.windows), 3)

    def test_importing_own_export_roundtrip(self):
        self.start({"text": "☐ дело\nтекст", "title": "План", "group": "Дом"})
        path = Path(self.tmp.name) / "all.md"
        self.app.export_markdown(path)
        added, errors = self.app.import_paths([path])
        self.assertEqual((added, errors), (1, []))
        copy = self.store.notes[-1]
        self.assertEqual((copy.title, copy.text, copy.group), ("План", "☐ дело\nтекст", "Дом"))

    def test_export_text_folder_and_note(self):
        (window,) = self.start({"text": "содержимое", "title": "Имя"})
        folder = Path(self.tmp.name) / "txt"
        paths = self.app.export_text_folder(folder)
        self.assertEqual([p.name for p in paths], ["Имя.txt"])
        self.assertEqual(paths[0].read_text(encoding="utf-8"), "содержимое")
        self.app._choose_save_path = lambda *a, **k: str(Path(self.tmp.name) / "one.md")
        out = self.app.export_note(window.note, window)
        self.assertIn("## Имя", out.read_text(encoding="utf-8"))

    # --- списки с длинным тире (как в Word) ---

    def press(self, window, keyval, state=0):
        return window._on_key_press(window.view, key(keyval, state))

    def test_hyphen_and_space_becomes_long_dash(self):
        (window,) = self.start({})
        self.put_text(window, "- молоко")
        self.assertEqual(self.text_of(window), "— молоко")
        self.put_text(window, "    - вложенный")
        self.assertEqual(self.text_of(window), "    — вложенный")

    def test_hyphen_then_tab_makes_a_list_item(self):
        (window,) = self.start({})
        self.put_text(window, "-")
        self.assertTrue(self.press(window, Gdk.KEY_Tab))
        self.assertEqual(self.text_of(window), "— ")
        buffer = window.view.get_buffer()
        self.assertEqual(buffer.get_iter_at_mark(buffer.get_insert()).get_offset(), 2)  # курсор после маркера
        window.view.get_buffer().insert_at_cursor("первый")
        self.assertEqual(self.text_of(window), "— первый")

    def test_ordinary_hyphens_are_left_alone(self):
        (window,) = self.start({})
        for text in ("слово-слово", "-молоко", "а - б", "-- шутка"):
            self.put_text(window, text)
            self.assertEqual(self.text_of(window), text)
        self.put_text(window, "обычный текст")
        self.assertFalse(self.press(window, Gdk.KEY_Tab))      # Tab вне списка — обычное поведение
        self.put_text(window, "☐ дело")
        self.assertFalse(self.press(window, Gdk.KEY_Tab))      # и у чекбокса тоже

    def test_tab_and_shift_tab_change_nesting_level(self):
        (window,) = self.start({"text": "— пункт"})
        buffer = window.view.get_buffer()
        buffer.place_cursor(buffer.get_end_iter())
        self.assertTrue(self.press(window, Gdk.KEY_Tab))
        self.assertEqual(self.text_of(window), "    — пункт")
        self.assertTrue(self.press(window, Gdk.KEY_Tab))
        self.assertEqual(self.text_of(window), "        — пункт")
        for _ in range(5):
            self.press(window, Gdk.KEY_Tab)
        self.assertEqual(self.text_of(window), "            — пункт")   # не глубже трёх уровней
        self.assertTrue(self.press(window, Gdk.KEY_ISO_Left_Tab, Gdk.ModifierType.SHIFT_MASK))
        self.assertEqual(self.text_of(window), "        — пункт")
        self.press(window, Gdk.KEY_ISO_Left_Tab, Gdk.ModifierType.SHIFT_MASK)
        self.press(window, Gdk.KEY_ISO_Left_Tab, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(self.text_of(window), "— пункт")
        self.assertFalse(self.press(window, Gdk.KEY_ISO_Left_Tab, Gdk.ModifierType.SHIFT_MASK))  # выше некуда

    def test_tab_at_line_start_keeps_cursor_before_marker(self):
        (window,) = self.start({"text": "— пункт"})
        buffer = window.view.get_buffer()
        buffer.place_cursor(buffer.get_start_iter())
        self.press(window, Gdk.KEY_Tab)
        self.assertEqual(buffer.get_iter_at_mark(buffer.get_insert()).get_offset(), 4)

    def test_tab_on_selection_indents_every_list_line(self):
        (window,) = self.start({"text": "— раз\nтекст\n— два"})
        buffer = window.view.get_buffer()
        buffer.select_range(buffer.get_start_iter(), buffer.get_end_iter())
        self.assertTrue(self.press(window, Gdk.KEY_Tab))
        self.assertEqual(self.text_of(window), "    — раз\nтекст\n    — два")
        self.press(window, Gdk.KEY_ISO_Left_Tab, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(self.text_of(window), "— раз\nтекст\n— два")

    def test_enter_continues_nested_list_and_ends_it(self):
        (window,) = self.start({"text": "— раз\n    — вложенный"})
        buffer = window.view.get_buffer()
        buffer.place_cursor(buffer.get_end_iter())
        self.assertTrue(self.press(window, Gdk.KEY_Return))
        self.assertEqual(self.text_of(window), "— раз\n    — вложенный\n    — ")
        self.assertTrue(self.press(window, Gdk.KEY_Return))      # пустой вложенный пункт выносится выше
        self.assertEqual(self.text_of(window), "— раз\n    — вложенный\n— ")
        self.assertTrue(self.press(window, Gdk.KEY_Return))      # пустой верхний пункт заканчивает список
        self.assertEqual(self.text_of(window), "— раз\n    — вложенный\n")
        self.assertFalse(self.press(window, Gdk.KEY_Return))     # дальше обычный Enter

    def test_enter_in_middle_of_item_splits_it_into_two_items(self):
        (window,) = self.start({"text": "— купить хлеб"})
        buffer = window.view.get_buffer()
        buffer.place_cursor(buffer.get_iter_at_offset(9))        # после «купить »
        self.press(window, Gdk.KEY_Return)
        self.assertEqual(self.text_of(window), "— купить \n— хлеб")

    def test_backspace_right_after_marker_removes_it(self):
        (window,) = self.start({"text": "— текст"})
        buffer = window.view.get_buffer()
        buffer.place_cursor(buffer.get_iter_at_offset(2))
        self.assertTrue(self.press(window, Gdk.KEY_BackSpace))
        self.assertEqual(self.text_of(window), "текст")
        buffer.place_cursor(buffer.get_iter_at_offset(3))        # внутри слова: обычный Backspace
        self.assertFalse(self.press(window, Gdk.KEY_BackSpace))

    def test_wrapped_list_lines_get_hanging_indent(self):
        long_text = "— " + "очень длинный пункт списка, " * 6
        (window,) = self.start({"text": long_text + "\nобычная строка"})
        pump(0.4)
        buffer = window.view.get_buffer()
        names = [t.get_property("name") for t in buffer.get_iter_at_offset(3).get_tags()]
        hang = [n for n in names if n and n.startswith("hang")]
        self.assertEqual(len(hang), 1)
        tag = buffer.get_tag_table().lookup(hang[0])
        self.assertLess(tag.get_property("indent"), 0)           # отрицательный — висячий отступ
        plain = [t.get_property("name") for t in buffer.get_iter_at_offset(len(long_text) + 3).get_tags()]
        self.assertFalse([n for n in plain if n and n.startswith("hang")])
        # вложенный пункт висит глубже
        window.note.text = window.note.text
        self.put_text(window, "— a\n    — b")
        starts = [t.get_property("indent") for line in (0, 1)
                  for t in buffer.get_iter_at_line(line).get_tags() if (t.get_property("name") or "").startswith("hang")]
        self.assertEqual(len(starts), 2)
        self.assertLess(starts[1], starts[0])

    def test_dash_list_survives_save_and_reload(self):
        (window,) = self.start({})
        self.put_text(window, "- раз")
        self.press(window, Gdk.KEY_Return)
        window.view.get_buffer().insert_at_cursor("два")
        self.press(window, Gdk.KEY_Return)
        self.press(window, Gdk.KEY_Tab)
        window.view.get_buffer().insert_at_cursor("вложенный")
        window.flush()
        reloaded = NoteStore(self.store.path)
        reloaded.load()
        self.assertEqual(reloaded.notes[0].text, "— раз\n— два\n    — вложенный")

    # --- ползунок размера шрифта в меню ---

    @staticmethod
    def font_submenu(menu):
        head = next(i for i in menu.get_children()
                    if isinstance(i, Gtk.MenuItem) and i.get_label() == "Размер шрифта")
        return head, head.get_submenu()

    def test_font_submenu_has_slider_and_default_but_no_plus_minus(self):
        (window,) = self.start({"text": "a"})
        menu = window.build_menu()  # держим ссылку
        _head, sub = self.font_submenu(menu)
        items = sub.get_children()
        self.assertTrue(hasattr(items[0], "font_scale"))               # ползунок — первый пункт
        self.assertIsInstance(items[1], Gtk.SeparatorMenuItem)
        labels = [i.get_label() for i in items[2:]]
        default = self.settings["default_font_size"]
        self.assertEqual(labels, [f"По умолчанию ({default} пт)   Ctrl+0"])  # «Крупнее/Мельче» убраны

    def test_menu_slider_sets_size_and_clamps(self):
        (window,) = self.start({"text": "a"})
        menu = window.build_menu()
        scale = self.font_submenu(menu)[1].get_children()[0].font_scale
        default = self.settings["default_font_size"]
        self.assertEqual(scale.get_value(), default)           # показывает текущий размер
        scale.set_value(21)
        self.assertEqual(window.note.font_size, 21)
        scale.set_value(500)
        self.assertEqual(window.note.font_size, 40)
        scale.set_value(-3)
        self.assertEqual(window.note.font_size, 8)

    def test_menu_slider_starts_at_the_notes_own_size_and_shows_value(self):
        (window,) = self.start({"text": "a", "font_size": 20})
        menu = window.build_menu()
        item = self.font_submenu(menu)[1].get_children()[0]
        self.assertEqual(item.font_scale.get_value(), 20)
        item.font_scale.set_value(25)
        labels = []

        def walk(widget):
            if isinstance(widget, Gtk.Label):
                labels.append(widget.get_text())
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    walk(child)

        walk(item)
        self.assertIn("25 пт", labels)

    def test_default_item_resets_slider_change(self):
        (window,) = self.start({"text": "a", "font_size": 20})
        menu = window.build_menu()
        sub = self.font_submenu(menu)[1]
        reset = [i for i in sub.get_children() if isinstance(i, Gtk.MenuItem) and (i.get_label() or "").startswith("По умолчанию")][0]
        reset.activate()
        self.assertEqual(window.note.font_size, 0)
        self.assertEqual(window.effective_font_size(), self.settings["default_font_size"])

    def test_menu_slider_change_is_saved(self):
        (window,) = self.start({"text": "a"})
        menu = window.build_menu()
        self.font_submenu(menu)[1].get_children()[0].font_scale.set_value(25)
        window.flush()
        reloaded = NoteStore(self.store.path)
        reloaded.load()
        self.assertEqual(reloaded.notes[0].font_size, 25)

    @unittest.skipUnless(__import__("indicat_sticky_notes.hotkeys", fromlist=["x"]).supported(),
                         "нужен X11")
    def test_dragging_the_slider_inside_the_open_menu_keeps_menu_open(self):
        """Настоящее перетаскивание мышью (XTest) внутри открытого меню: меню не должно закрыться."""
        import ctypes
        import ctypes.util
        from indicat_sticky_notes import hotkeys
        xtest_lib = ctypes.util.find_library("Xtst")
        if not xtest_lib:
            self.skipTest("нет libXtst")
        x11, xtst = hotkeys._load_x11(), ctypes.CDLL(xtest_lib)
        xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        display = x11.XOpenDisplay(None)
        self.addCleanup(x11.XCloseDisplay, display)

        def move(x, y):
            xtst.XTestFakeMotionEvent(display, -1, int(x), int(y), 0)
            x11.XSync(display, 0)
            pump(0.05)

        def button(down):
            xtst.XTestFakeButtonEvent(display, 1, 1 if down else 0, 0)
            x11.XSync(display, 0)
            pump(0.05)

        (window,) = self.start({"text": "a"})
        menu = window.build_menu()
        menu.popup(None, None, lambda *_a: (60, 60, True), None, 0, Gtk.get_current_event_time())
        pump(0.5)
        head, sub = self.font_submenu(menu)
        menu.select_item(head)          # как при наведении на «Размер шрифта»: раскрывается подменю
        pump(1.0)
        self.assertTrue(sub.get_visible())
        item = sub.get_children()[0]
        scale = item.font_scale
        tx, ty = scale.translate_coordinates(sub.get_toplevel(), 0, 0)
        px, py = sub.get_toplevel().get_window().get_origin()[1:]
        width, height = scale.get_allocated_width(), scale.get_allocated_height()
        start, end = scale.get_slider_range()
        y = py + ty + height / 2

        def drag(from_x, to_x):
            move(from_x, y)
            button(True)
            for i in range(1, 13):
                move(from_x + (to_x - from_x) * i / 12, y)
            button(False)

        drag(px + tx + (start + end) / 2, px + tx + width + 40)
        self.assertEqual(window.note.font_size, 40)
        self.assertTrue(sub.get_visible(), "меню закрылось при отпускании кнопки мыши")
        start, end = scale.get_slider_range()
        drag(px + tx + (start + end) / 2, px + tx - 40)
        self.assertEqual(window.note.font_size, 8)
        self.assertTrue(sub.get_visible(), "меню закрылось при втором перетаскивании")
        menu.popdown()

    # --- справка и «О программе» ---

    def test_help_window_lists_every_section_and_is_reused(self):
        from indicat_sticky_notes import help_window
        self.start()
        self.app.open_help()
        first = self.app.help_window
        self.app.open_help()
        self.assertIs(self.app.help_window, first)               # одно окно, а не новое на каждый F1
        self.assertTrue(first.get_visible())
        buffer = first.view.get_buffer()
        shown = buffer.get_text(*buffer.get_bounds(), True)
        for title, lines in help_window.HELP_SECTIONS:
            self.assertIn(title, shown)
            self.assertIn(lines[0], shown)
        first.destroy()

    def test_help_mentions_the_shortcuts_the_app_really_has(self):
        from indicat_sticky_notes import help_window
        text = help_window.help_text()
        for needle in ("Ctrl+B", "Ctrl+L", "Ctrl+Alt+N", "Ctrl+Alt+S", "F1", "Tab", "Ctrl+A", "Delete"):
            self.assertIn(needle, text)

    def test_f1_opens_help_from_note_manager_and_settings(self):
        (window,) = self.start({"text": "a"})
        calls = []
        self.app.open_help = lambda: calls.append("help")
        self.assertTrue(window._on_window_key(window, key(Gdk.KEY_F1)))
        self.assertFalse(window._on_window_key(window, key(Gdk.KEY_F2)))
        self.app.open_manager()
        self.assertTrue(self.app.manager._on_f1(None, key(Gdk.KEY_F1)))
        self.assertFalse(self.app.manager._on_f1(None, key(Gdk.KEY_F2)))
        self.app.open_settings()
        self.assertTrue(self.app.settings_window._on_key_press(None, key(Gdk.KEY_F1)))
        self.assertEqual(calls, ["help", "help", "help"])

    @unittest.skipUnless(__import__("indicat_sticky_notes.hotkeys", fromlist=["x"]).supported(),
                         "нужен X11")
    def test_real_f1_key_press_opens_help_with_focus_on_header_button_and_on_text(self):
        """Настоящее нажатие F1 (XTest) при разном фокусе внутри заметки."""
        import ctypes
        import ctypes.util
        from indicat_sticky_notes import hotkeys
        xtest_lib = ctypes.util.find_library("Xtst")
        if not xtest_lib:
            self.skipTest("нет libXtst")
        x11, xtst = hotkeys._load_x11(), ctypes.CDLL(xtest_lib)
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        display = x11.XOpenDisplay(None)
        self.addCleanup(x11.XCloseDisplay, display)
        (window,) = self.start({"text": "a", "x": 50, "y": 50})
        pump(0.4)
        gdk_window = window.get_window()
        ox, oy = gdk_window.get_origin()[1:]
        xtst.XTestFakeMotionEvent(display, -1, ox + 100, oy + 100, 0)   # указатель над заметкой
        x11.XSync(display, 0)
        # без оконного менеджера фокус ввода задаём сами, как это сделал бы он при щелчке по заметке
        x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        x11.XSetInputFocus(display, gdk_window.get_xid() if hasattr(gdk_window, "get_xid") else 0, 1, 0)
        x11.XSync(display, 0)
        keycode = x11.XKeysymToKeycode(display, 0xFFBE)                 # XK_F1
        for focus_on_button in (False, True):
            self.app.help_window = None
            if focus_on_button:
                window.pin_button.grab_focus()      # фокус на кнопке шапки, не в тексте
            else:
                window.view.grab_focus()
            pump(0.2)
            xtst.XTestFakeKeyEvent(display, keycode, 1, 0)
            xtst.XTestFakeKeyEvent(display, keycode, 0, 0)
            x11.XSync(display, 0)
            pump(0.6)
            self.assertIsNotNone(self.app.help_window, f"F1 не открыла справку (фокус на кнопке: {focus_on_button})")
            self.assertTrue(self.app.help_window.get_visible())
            self.app.help_window.destroy()

    def test_f1_does_not_interrupt_hotkey_capture_in_settings(self):
        self.start()
        self.app.open_settings()
        self.app.open_help = lambda: self.fail("F1 при записи сочетания не должен открывать справку")
        window = self.app.settings_window
        window._start_capture("hotkey_new")
        window._on_key_press(window, key(Gdk.KEY_F1, 0))   # просто не принимается как сочетание

    def test_about_dialog_has_version_site_and_license(self):
        from indicat_sticky_notes import __version__, help_window
        dialog = help_window.build_about_dialog()
        self.assertEqual(dialog.get_version(), __version__)
        self.assertEqual(dialog.get_website(), help_window.WEBSITE)
        self.assertEqual(dialog.get_license_type(), Gtk.License.MIT_X11)
        self.assertEqual(dialog.get_program_name(), "Стикеры")
        self.assertIn("h0r1ze", dialog.get_authors())
        dialog.destroy()

    # --- замечания по первому тестированию ---

    def test_resize_cursor_is_not_left_on_the_whole_note(self):
        """Регрессия: курсор «угла» должен быть только над ручкой, а не над всей заметкой."""
        (window,) = self.start({"text": "a"})
        pump(0.3)
        self.assertIsNone(window.get_window().get_cursor())
        window._set_window_cursor("se-resize")   # курсор мыши над ручкой
        self.assertIs(window.get_window().get_cursor(), window._cursor("se-resize"))
        window._set_window_cursor(None)          # мышь ушла с ручки
        self.assertIsNone(window.get_window().get_cursor())

    def test_cursor_over_checkbox_is_arrow_over_text_is_text(self):
        (window,) = self.start({"text": "☐ купить\nобычная строка"})
        pump(0.3)
        view, buffer = window.view, window.view.get_buffer()

        def pointer_at(x, y):
            wx, wy = view.buffer_to_window_coords(Gtk.TextWindowType.TEXT, x, y)
            raw = Gdk.Event.new(Gdk.EventType.MOTION_NOTIFY)
            event = raw.motion
            event.x, event.y = wx, wy
            window._on_view_motion(view, event)
            return view.get_window(Gtk.TextWindowType.TEXT).get_cursor()

        box = view.get_iter_location(buffer.get_start_iter())
        self.assertIs(pointer_at(box.x + 2, box.y + 2), window._cursor("default"))
        self.assertIs(pointer_at(box.x + 70, box.y + 2), window._cursor("text"))
        second = view.get_iter_location(buffer.get_iter_at_line(1))
        self.assertIs(pointer_at(second.x + 2, second.y + 2), window._cursor("text"))
        self.assertIs(pointer_at(box.x + 2, box.y + 2), window._cursor("default"))  # и обратно на квадратик

    def test_ctrl_a_selects_all_text_in_note_in_any_layout(self):
        (window,) = self.start({"text": "раз два три"})
        buffer = window.view.get_buffer()
        ctrl = Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(window._on_key_press(window.view, key(Gdk.KEY_a, ctrl)))
        self.assertEqual(buffer.get_selection_bounds()[1].get_offset(), len("раз два три"))
        buffer.place_cursor(buffer.get_start_iter())
        found, keys = Gdk.Keymap.get_default().get_entries_for_keyval(Gdk.KEY_a)
        event = key(Gdk.KEY_Cyrillic_ef, ctrl)        # «ф» на клавише A
        event.hardware_keycode = keys[0].keycode
        self.assertTrue(window._on_key_press(window.view, event))
        self.assertTrue(buffer.get_has_selection())

    def test_manager_ctrl_a_selects_all_and_delete_moves_them_to_trash(self):
        self.start({"text": "a"}, {"text": "b"}, {"text": "c"})
        self.app.open_manager()
        pump()
        manager = self.app.manager
        self.assertTrue(manager._on_tree_key(manager.tree, key(Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK), None))
        self.assertEqual(len(manager._selected(manager.tree)), 3)
        self.assertTrue(manager._on_tree_key(manager.tree, key(Gdk.KEY_Delete), None))
        pump()
        self.assertEqual(len(self.store.active_notes), 0)
        self.assertEqual(len(self.store.trash_notes), 3)
        self.assertEqual(self.app.windows, {})

    def test_manager_delete_in_trash_purges_selected_after_confirmation(self):
        windows = self.start({"text": "a"}, {"text": "b"})
        for window in windows:
            self.app.delete_note(window.note.id)
        self.app.open_manager()
        pump()
        manager = self.app.manager
        manager.trash_tree.get_selection().select_all()
        manager._confirm = lambda *a: False
        manager._on_tree_key(manager.trash_tree, key(Gdk.KEY_Delete), None)
        self.assertEqual(len(self.store.trash_notes), 2)  # отказались — ничего не удалено
        manager._confirm = lambda *a: True
        manager._on_tree_key(manager.trash_tree, key(Gdk.KEY_Delete), None)
        pump()
        self.assertEqual(self.store.trash_notes, [])

    def test_manager_actions_apply_to_every_selected_note(self):
        a, b, c = self.start({"text": "a", "hidden": True}, {"text": "b", "hidden": True}, {"text": "c"})
        self.app.open_manager()
        pump()
        manager = self.app.manager
        manager.tree.get_selection().select_all()
        manager._show_selected()
        self.assertTrue(a.get_visible() and b.get_visible() and c.get_visible())
        manager._hide_selected()
        self.assertFalse(a.get_visible() or b.get_visible() or c.get_visible())

    def test_manager_keeps_multi_selection_across_refresh(self):
        self.start({"text": "a"}, {"text": "b"}, {"text": "c"})
        self.app.open_manager()
        pump()
        manager = self.app.manager
        manager.tree.get_selection().select_all()
        before = set(manager._selected(manager.tree))
        manager.refresh()
        self.assertEqual(set(manager._selected(manager.tree)), before)

    def test_backup_asks_where_to_save_and_cancel_saves_nothing(self):
        self.start({"text": "важное"})
        asked = []
        target = Path(self.tmp.name) / "выбранная папка" / "копия"

        def fake_dialog(title, name, parent=None, folder=None):
            asked.append((name, folder))
            return str(target)

        self.app._choose_save_path = fake_dialog
        saved = self.app.backup_now()
        self.assertEqual(saved, target.with_name("копия.json"))
        self.assertEqual([n.text for n in backup.load(saved)], ["важное"])
        name, folder = asked[0]
        self.assertTrue(name.startswith("notes-") and name.endswith("-manual.json"))
        self.assertEqual(Path(folder), self.backups)  # диалог открывается в папке копий
        manual_before = [b for b in backup.list_backups(self.backups) if b.reason == "manual"]
        self.app._choose_save_path = lambda *a, **k: None  # «Отмена»
        self.assertIsNone(self.app.backup_now())
        self.assertEqual([b for b in backup.list_backups(self.backups) if b.reason == "manual"], manual_before)

    def test_backup_with_no_notes_does_not_ask(self):
        self.start()
        for note_id in [n.id for n in self.store.notes]:
            self.store.remove(note_id)
        self.app._choose_save_path = lambda *a, **k: self.fail("не должен спрашивать, когда копировать нечего")
        self.assertIsNone(self.app.backup_now())

    def test_create_desktop_shortcut_from_app_and_settings(self):
        self.start()
        home = Path(self.tmp.name) / "home"
        with mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}):
            path = self.app.create_desktop_shortcut()
            self.assertEqual(path, home / "Desktop" / "Стикеры.desktop")
            self.assertTrue(path.exists() and os.access(path, os.X_OK))
            self.app.open_settings()
            labels = []

            def walk(widget):
                if isinstance(widget, Gtk.Button):
                    labels.append(widget.get_label())
                if isinstance(widget, Gtk.Container):
                    for child in widget.get_children():
                        walk(child)

            walk(self.app.settings_window)
            self.assertIn("Создать ярлык на рабочем столе", labels)

    def test_shadow_does_not_exceed_window_margin(self):
        """Регрессия: тень шире отступа вокруг листа обрезалась и давала видимый прямоугольник."""
        import re
        from indicat_sticky_notes import theme
        shadow = re.search(r"\.note \{[^}]*box-shadow: 0 (\d+)px (\d+)px", theme._STATIC_CSS)
        offset, blur = int(shadow.group(1)), int(shadow.group(2))
        self.assertLessEqual(offset + blur, theme.SHADOW_MARGIN)

    # --- глобальные клавиши ---

    @unittest.skipUnless(__import__("indicat_sticky_notes.hotkeys", fromlist=["x"]).supported(),
                         "нужен X11")
    def test_global_hotkey_creates_note(self):
        self.app.use_hotkeys = True
        self.start()
        self.assertEqual(self.app.hotkey_status, {"new": True, "toggle": True})
        before = len(self.store.active_notes)
        from tests.test_hotkeys import XK_ALT_L, XK_CONTROL_L, XK_N, XTEST, press_combo
        if not XTEST:
            self.skipTest("нет libXtst")
        press_combo(XK_CONTROL_L, XK_ALT_L, XK_N)
        pump(0.6)
        self.assertEqual(len(self.store.active_notes), before + 1)


if __name__ == "__main__":
    unittest.main()
