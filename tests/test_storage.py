import json
import tempfile
import unittest
from pathlib import Path

from indicat_sticky_notes.storage import NoteStore


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


if __name__ == "__main__":
    unittest.main()
