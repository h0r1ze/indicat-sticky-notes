import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from indicat_sticky_notes import backup
from indicat_sticky_notes.storage import Note


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "backups"
        self.notes = [Note(text="a"), Note(text="б", color="blue")]
        self.t0 = datetime(2026, 10, 10, 12, 0, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_load_roundtrip(self):
        path = backup.create(self.notes, "manual", self.dir, self.t0)
        self.assertEqual(path.name, "notes-20261010-120000-manual.json")
        self.assertEqual(backup.load(path), self.notes)

    def test_nothing_to_back_up(self):
        self.assertIsNone(backup.create([], "manual", self.dir, self.t0))
        self.assertFalse(self.dir.exists())

    def test_same_second_does_not_overwrite(self):
        a = backup.create(self.notes, "manual", self.dir, self.t0)
        b = backup.create(self.notes, "manual", self.dir, self.t0)
        self.assertNotEqual(a, b)
        self.assertEqual(len(backup.list_backups(self.dir)), 2)

    def test_list_is_newest_first_and_parses_reason(self):
        backup.create(self.notes, "auto", self.dir, self.t0)
        backup.create(self.notes, "manual", self.dir, self.t0 + timedelta(hours=1))
        listed = backup.list_backups(self.dir)
        self.assertEqual([b.reason for b in listed], ["manual", "auto"])
        self.assertEqual(listed[0].created, self.t0 + timedelta(hours=1))

    def test_foreign_files_are_ignored(self):
        self.dir.mkdir(parents=True)
        (self.dir / "notes-garbage.json").write_text("{}")
        (self.dir / "readme.txt").write_text("x")
        self.assertEqual(backup.list_backups(self.dir), [])

    def test_prune_keeps_newest(self):
        for i in range(5):
            backup.create(self.notes, "auto", self.dir, self.t0 + timedelta(days=i))
        backup.prune(self.dir, keep=2)
        kept = backup.list_backups(self.dir)
        self.assertEqual([b.created.day for b in kept], [14, 13])

    def test_auto_is_made_once_per_interval(self):
        self.assertIsNotNone(backup.auto_if_due(self.notes, self.dir, self.t0))
        self.assertIsNone(backup.auto_if_due(self.notes, self.dir, self.t0 + timedelta(hours=5)))
        self.assertIsNotNone(backup.auto_if_due(self.notes, self.dir, self.t0 + timedelta(hours=21)))

    def test_manual_copy_does_not_block_auto(self):
        backup.create(self.notes, "manual", self.dir, self.t0)
        self.assertIsNotNone(backup.auto_if_due(self.notes, self.dir, self.t0 + timedelta(hours=1)))

    def test_default_name_matches_listing_pattern(self):
        name = backup.default_name(self.t0)
        self.assertEqual(name, "notes-20261010-120000-manual.json")
        (self.dir).mkdir(parents=True)
        (self.dir / name).write_text("{}")
        self.assertEqual([b.reason for b in backup.list_backups(self.dir)], ["manual"])

    def test_save_to_chosen_path_adds_extension_and_roundtrips(self):
        target = Path(self.tmp.name) / "куда-хочу" / "моя копия"
        saved = backup.save_to(self.notes, target)
        self.assertEqual(saved.name, "моя копия.json")
        self.assertEqual(backup.load(saved), self.notes)
        kept = backup.save_to(self.notes, Path(self.tmp.name) / "уже.JSON")
        self.assertEqual(kept.name, "уже.JSON")  # своё расширение не трогаем

    def test_save_to_does_not_touch_default_backup_folder(self):
        backup.save_to(self.notes, Path(self.tmp.name) / "out.json")
        self.assertEqual(backup.list_backups(self.dir), [])

    def test_unknown_reason_rejected(self):
        with self.assertRaises(ValueError):
            backup.create(self.notes, "whatever", self.dir, self.t0)

    def test_load_rejects_bad_files(self):
        self.dir.mkdir(parents=True)
        for name, content in (("a.json", "{oops"), ("b.json", "[]"), ("c.json", '{"notes": 5}'),
                              ("d.json", '{"notes": [1]}')):
            path = self.dir / name
            path.write_text(content)
            with self.assertRaises(ValueError, msg=name):
                backup.load(path)
        with self.assertRaises(ValueError):
            backup.load(self.dir / "missing.json")


if __name__ == "__main__":
    unittest.main()
