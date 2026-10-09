"""Сквозные проверки интерфейса. Нужен дисплей (например, xvfb-run), иначе пропускаются."""
import tempfile
import time
import unittest
from pathlib import Path

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    HAVE_DISPLAY = Gtk.init_check()[0]
except (ImportError, ValueError):
    HAVE_DISPLAY = False

if HAVE_DISPLAY:
    from indicat_sticky_notes import backup, checklist
    from indicat_sticky_notes.app import StickyApp
    from indicat_sticky_notes.storage import NoteStore


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
        self.app = StickyApp(self.store, self.backups)

    def tearDown(self):
        for window in list(self.app.windows.values()):
            window.destroy()
        if self.app.manager:
            self.app.manager.destroy()
        if self.app.tray:
            self.app.tray.set_visible(False)
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
        states = {r[2]: r[3] for r in manager.model}
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
        self.app._message = lambda *a, **k: None  # без модальных окон в тесте
        path = self.app.backup_now()
        self.assertTrue(path.exists())
        # портим состояние и восстанавливаем
        for note_id in [n.id for n in self.store.notes]:
            self.app.delete_note(note_id)
        self.app.new_note()
        self.assertEqual([n.text for n in self.store.notes], [""])
        self.assertTrue(self.app.restore_from(path, confirm=False))
        pump()
        self.assertEqual([n.text for n in self.store.notes], ["важное"])
        self.assertEqual(len(self.app.windows), 1)
        reasons = {b.reason for b in backup.list_backups(self.backups)}
        self.assertEqual(reasons, {"auto", "manual", "before-restore"})

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
        labels = [i.get_label() for i in menu.get_children() if isinstance(i, Gtk.MenuItem)
                  and not isinstance(i, Gtk.SeparatorMenuItem)]
        self.assertEqual(labels, ["Новая заметка", "Менеджер заметок…", "Показать все",
                                  "Скрыть все", "Резервные копии", "Запускать при входе", "Выход"])


if __name__ == "__main__":
    unittest.main()
