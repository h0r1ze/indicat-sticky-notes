import json
import tempfile
import time
import unittest
from pathlib import Path

from indicat_sticky_notes.storage import Note, NoteStore

DAY = 86400


class TrashAndGroupsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "notes.json"
        self.store = NoteStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def reload(self):
        other = NoteStore(self.path)
        other.load()
        return other

    def test_trash_restore_roundtrip(self):
        note = self.store.add(text="x")
        self.store.move_to_trash(note.id)
        self.assertEqual(self.store.active_notes, [])
        self.assertEqual([n.id for n in self.store.trash_notes], [note.id])
        self.assertTrue(self.reload().notes[0].in_trash)  # состояние сохранено
        self.store.restore(note.id)
        self.assertEqual([n.id for n in self.store.active_notes], [note.id])
        self.assertFalse(self.store.get(note.id).hidden)

    def test_restore_ignores_active_note(self):
        note = self.store.add(text="x", hidden=True)
        self.store.restore(note.id)
        self.assertTrue(note.hidden)  # живую заметку не трогаем

    def test_purge_leaves_empty_tombstone(self):
        note = self.store.add(text="секрет", title="т", group="г", formats=[[0, 1, "bold"]])
        self.store.move_to_trash(note.id)
        self.store.purge(note.id)
        tomb = self.store.get(note.id)
        self.assertTrue(tomb.purged)
        self.assertEqual((tomb.text, tomb.title, tomb.group, tomb.formats), ("", "", "", []))
        self.assertEqual(self.store.trash_notes, [])
        self.assertEqual(self.store.active_notes, [])

    def test_empty_trash_only_touches_trash(self):
        keep = self.store.add(text="жива")
        gone = self.store.add(text="в корзине")
        self.store.move_to_trash(gone.id)
        self.store.empty_trash()
        self.assertEqual([n.id for n in self.store.active_notes], [keep.id])
        self.assertTrue(self.store.get(gone.id).purged)

    def test_cleanup_ages_trash_then_tombstones(self):
        now = time.time()
        fresh = self.store.add(text="свежая")
        old = self.store.add(text="старая")
        self.store.move_to_trash(fresh.id)
        self.store.move_to_trash(old.id)
        self.store.get(old.id).deleted_at = now - 31 * DAY
        self.assertTrue(self.store.cleanup(now))
        self.assertTrue(self.store.get(old.id).purged)       # старая -> надгробие
        self.assertTrue(self.store.get(fresh.id).in_trash)   # свежая осталась
        # надгробие живёт ещё TOMBSTONE_DAYS
        self.assertFalse(self.store.cleanup(now + 10 * DAY))
        self.assertIsNotNone(self.store.get(old.id))
        self.assertTrue(self.store.cleanup(now + 40 * DAY))
        self.assertIsNone(self.store.get(old.id))

    def test_cleanup_respects_custom_retention(self):
        note = self.store.add(text="x")
        self.store.move_to_trash(note.id)
        self.store.get(note.id).deleted_at = time.time() - 5 * DAY
        self.assertFalse(self.store.cleanup(trash_days=30))
        self.assertTrue(self.store.cleanup(trash_days=3))

    def test_groups_listing_ignores_trash_and_empty(self):
        self.store.add(text="a", group="Работа")
        self.store.add(text="b", group="дом")
        self.store.add(text="c", group="")
        gone = self.store.add(text="d", group="Старое")
        self.store.move_to_trash(gone.id)
        self.assertEqual(self.store.groups(), ["дом", "Работа"])  # без учёта регистра

    def test_search_covers_title_text_and_group_filter(self):
        a = self.store.add(text="Купить молоко", group="Дом")
        b = self.store.add(text="отчёт", title="Молоко для офиса", group="Работа")
        c = self.store.add(text="прочее")
        self.assertEqual({n.id for n in self.store.search("молоко")}, {a.id, b.id})
        self.assertEqual([n.id for n in self.store.search("молоко", group="Дом")], [a.id])
        self.assertEqual([n.id for n in self.store.search("", group="")], [c.id])
        self.store.move_to_trash(a.id)
        self.assertEqual([n.id for n in self.store.search("молоко")], [b.id])  # корзина не ищется

    def test_blank_and_display_title(self):
        self.assertTrue(Note().is_blank())
        self.assertFalse(Note(title="т").is_blank())
        self.assertEqual(Note(title=" Имя ", text="текст").display_title(), "Имя")
        self.assertEqual(Note(text="\nпервая\nвторая").display_title(), "первая")


class MergeTest(unittest.TestCase):
    def test_newer_wins_and_local_view_state_is_kept(self):
        store = NoteStore(Path(tempfile.mkdtemp()) / "n.json")
        mine = Note(id="1", text="старый", x=10, y=20, width=300, height=200, updated=100)
        store.notes = [mine]
        theirs = Note(id="1", text="новый", color="blue", x=999, y=999, width=50, height=50,
                      pinned=True, hidden=True, updated=200)
        added, changed = store.merge([theirs])
        self.assertEqual((added, changed), ([], ["1"]))
        self.assertIs(store.notes[0], mine)  # тот же объект: окна держат на него ссылку
        self.assertEqual((mine.text, mine.color, mine.updated), ("новый", "blue", 200))
        self.assertEqual((mine.x, mine.y, mine.width, mine.height), (10, 20, 300, 200))
        self.assertFalse(mine.pinned or mine.hidden)

    def test_older_remote_is_ignored(self):
        store = NoteStore(Path(tempfile.mkdtemp()) / "n.json")
        store.notes = [Note(id="1", text="мой", updated=200)]
        added, changed = store.merge([Note(id="1", text="чужой", updated=100)])
        self.assertEqual((added, changed, store.notes[0].text), ([], [], "мой"))

    def test_new_notes_are_added_with_their_geometry(self):
        store = NoteStore(Path(tempfile.mkdtemp()) / "n.json")
        added, _ = store.merge([Note(id="9", text="пришла", x=5, y=6)])
        self.assertEqual(added, ["9"])
        self.assertEqual((store.notes[0].x, store.notes[0].y), (5, 6))

    def test_local_only_notes_survive(self):
        store = NoteStore(Path(tempfile.mkdtemp()) / "n.json")
        store.notes = [Note(id="local", text="только у меня")]
        store.merge([Note(id="remote")])
        self.assertEqual({n.id for n in store.notes}, {"local", "remote"})

    def test_remote_deletion_propagates(self):
        store = NoteStore(Path(tempfile.mkdtemp()) / "n.json")
        store.notes = [Note(id="1", text="жива", updated=100)]
        remote = Note(id="1", text="", purged=True, deleted_at=300, updated=300)
        store.merge([remote])
        self.assertTrue(store.notes[0].purged)
        self.assertEqual(store.active_notes, [])


class SaveMergesExternalChangesTest(unittest.TestCase):
    """Отложенная запись одного экземпляра не должна затирать правки другого."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "notes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def pair(self):
        mine = NoteStore(self.path)
        mine.add(text="исходный")
        other = NoteStore(self.path)
        other.load()
        return mine, other

    def test_foreign_edit_survives_our_later_save(self):
        mine, other = self.pair()
        other.notes[0].text, other.notes[0].updated = "правка с другого компьютера", time.time() + 50
        other.save()
        calls = []
        mine.merge_hook = lambda added, changed: calls.append((added, changed))
        mine.save()  # у нас в памяти ещё старый текст
        self.assertEqual(mine.notes[0].text, "правка с другого компьютера")
        self.assertEqual(calls, [([], [mine.notes[0].id])])
        again = NoteStore(self.path)
        again.load()
        self.assertEqual(again.notes[0].text, "правка с другого компьютера")

    def test_foreign_new_note_survives(self):
        mine, other = self.pair()
        newcomer = other.add(text="новая")
        mine.save()
        self.assertEqual({n.id for n in mine.notes}, {mine.notes[0].id, newcomer.id})

    def test_our_newer_edit_wins_over_older_foreign_one(self):
        mine, other = self.pair()
        other.notes[0].text, other.notes[0].updated = "старая чужая", time.time() - 50
        other.save()
        mine.notes[0].text, mine.notes[0].updated = "наша свежая", time.time()
        mine.save()
        self.assertEqual(mine.notes[0].text, "наша свежая")
        again = NoteStore(self.path)
        again.load()
        self.assertEqual(again.notes[0].text, "наша свежая")

    def test_no_hook_call_without_foreign_changes(self):
        mine, _ = self.pair()
        calls = []
        mine.merge_hook = lambda *a: calls.append(a)
        mine.save()
        self.assertEqual(calls, [])

    def test_half_written_foreign_file_does_not_break_saving(self):
        mine, _ = self.pair()
        self.path.write_text('{"notes": [ {"id": "x", "te', encoding="utf-8")  # синхронизатор не дописал
        mine.add(text="ещё одна")  # не падает; перезапишет битый файл целым
        again = NoteStore(self.path)
        again.load()
        self.assertEqual(len(again.notes), 2)


class RobustnessTest(unittest.TestCase):
    def test_corrupt_file_is_set_aside_not_overwritten(self):
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "notes.json"
        path.write_text("{битый json", encoding="utf-8")
        store = NoteStore(path)
        store.load()
        self.assertEqual(store.notes, [])
        self.assertIsNotNone(store.corrupt_file)
        self.assertEqual(store.corrupt_file.read_text(encoding="utf-8"), "{битый json")
        store.add(text="новая")  # теперь можно писать: старое сохранено отдельно
        self.assertTrue(store.corrupt_file.exists())

    def test_missing_file_is_not_corruption(self):
        store = NoteStore(Path(tempfile.mkdtemp()) / "notes.json")
        store.load()
        self.assertIsNone(store.corrupt_file)

    def test_digest_detects_foreign_changes_but_not_own_writes(self):
        path = Path(tempfile.mkdtemp()) / "notes.json"
        store = NoteStore(path)
        store.add(text="a")
        self.assertFalse(store.disk_changed_externally())
        other = NoteStore(path)
        other.load()
        other.notes[0].text = "изменено на другом компьютере"
        other.save()
        self.assertTrue(store.disk_changed_externally())

    def test_old_file_without_new_fields_loads(self):
        path = Path(tempfile.mkdtemp()) / "notes.json"
        path.write_text(json.dumps({"notes": [{"id": "1", "text": "старая"}]}), encoding="utf-8")
        store = NoteStore(path)
        store.load()
        note = store.notes[0]
        self.assertEqual((note.title, note.group, note.opacity, note.font_size, note.formats),
                         ("", "", 1.0, 0, []))
        self.assertTrue(note.active)


if __name__ == "__main__":
    unittest.main()
