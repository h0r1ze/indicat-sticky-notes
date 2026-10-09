import json
import tempfile
import unittest
from pathlib import Path

from indicat_sticky_notes.storage import Note, NoteStore


class NoteStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "sub" / "notes.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_file_gives_empty_store(self):
        store = NoteStore(self.path)
        store.load()
        self.assertEqual(store.notes, [])

    def test_roundtrip(self):
        store = NoteStore(self.path)
        note = store.add(text="Привет", color="blue", x=5, y=7)
        other = NoteStore(self.path)
        other.load()
        self.assertEqual(len(other.notes), 1)
        self.assertEqual(other.notes[0], note)

    def test_remove(self):
        store = NoteStore(self.path)
        a = store.add(text="a")
        b = store.add(text="b")
        store.remove(a.id)
        other = NoteStore(self.path)
        other.load()
        self.assertEqual([n.id for n in other.notes], [b.id])

    def test_corrupt_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        store = NoteStore(self.path)
        store.load()
        self.assertEqual(store.notes, [])

    def test_unknown_fields_are_dropped(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps({"notes": [{"id": "1", "text": "x", "future": True}]}),
            encoding="utf-8",
        )
        store = NoteStore(self.path)
        store.load()
        self.assertEqual(store.notes[0].text, "x")

    def test_listeners_are_called_on_save(self):
        store = NoteStore(self.path)
        calls = []
        store.listeners.append(lambda: calls.append(1))
        store.add(text="x")
        store.save()
        self.assertEqual(len(calls), 2)

    def test_search_is_case_insensitive_and_empty_query_returns_all(self):
        store = NoteStore(self.path)
        store.add(text="Купить МОЛОКО")
        store.add(text="Позвонить")
        self.assertEqual([n.text for n in store.search("молоко")], ["Купить МОЛОКО"])
        self.assertEqual(len(store.search("  ")), 2)
        self.assertEqual(store.search("нет такого"), [])

    def test_preview_uses_first_non_empty_line_and_truncates(self):
        self.assertEqual(Note(text="\n\n  привет  \nвторая").preview(), "привет")
        self.assertEqual(Note(text="").preview(), "")
        self.assertEqual(len(Note(text="x" * 200).preview(20)), 20)

    def test_new_fields_default_for_old_files(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"notes": [{"id": "1", "text": "старая"}]}), encoding="utf-8")
        store = NoteStore(self.path)
        store.load()
        note = store.notes[0]
        self.assertFalse(note.pinned)
        self.assertFalse(note.hidden)

    def test_touch_updates_timestamp(self):
        store = NoteStore(self.path)
        note = store.add(text="x")
        note.updated = 0
        store.touch(note)
        self.assertGreater(note.updated, 0)


if __name__ == "__main__":
    unittest.main()
