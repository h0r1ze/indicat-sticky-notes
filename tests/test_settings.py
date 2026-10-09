import json
import tempfile
import unittest
from pathlib import Path

from indicat_sticky_notes import settings, storage
from indicat_sticky_notes.settings import Settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cfg" / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_when_no_file(self):
        s = Settings(self.path)
        s.load()
        self.assertEqual(s.values, settings.DEFAULTS)

    def test_update_persists_and_notifies(self):
        s = Settings(self.path)
        seen = []
        s.listeners.append(seen.append)
        self.assertEqual(s.update(theme="dark", default_font_size=16), ["theme", "default_font_size"])
        self.assertEqual(seen, [["theme", "default_font_size"]])
        other = Settings(self.path)
        other.load()
        self.assertEqual((other["theme"], other["default_font_size"]), ("dark", 16))

    def test_no_notification_when_nothing_changed(self):
        s = Settings(self.path)
        seen = []
        s.listeners.append(seen.append)
        self.assertEqual(s.update(theme="system"), [])
        self.assertEqual(seen, [])
        self.assertFalse(self.path.exists())

    def test_invalid_values_fall_back_to_defaults(self):
        s = Settings(self.path)
        s.update(theme="розовая", default_font_size=999, trash_days=0, tray_click="x",
                 default_color="nope", data_dir=5)
        self.assertEqual(s.values, settings.DEFAULTS)
        s.update(default_font_size=True)  # bool — не число
        self.assertEqual(s["default_font_size"], settings.DEFAULTS["default_font_size"])

    def test_color_accepts_names_and_hex(self):
        s = Settings(self.path)
        s.update(default_color="graphite")
        self.assertEqual(s["default_color"], "graphite")
        s.update(default_color="#ABCDEF")
        self.assertEqual(s["default_color"], "#abcdef")

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(KeyError):
            Settings(self.path).update(bogus=1)

    def test_broken_or_foreign_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        for content in ("{не json", "[1, 2]", '{"theme": "dark", "mystery": 1}'):
            self.path.write_text(content, encoding="utf-8")
            s = Settings(self.path)
            s.load()
            self.assertEqual(set(s.values), set(settings.DEFAULTS))
        self.assertEqual(s["theme"], "dark")  # из последнего файла

    def test_dash_autoconvert_is_off_by_default_and_accepts_only_booleans(self):
        s = Settings(self.path)
        self.assertIs(s["dash_autoconvert"], False)
        s.update(dash_autoconvert=True)
        self.assertIs(s["dash_autoconvert"], True)
        s.update(dash_autoconvert="да")        # мусор не принимается: остаётся значение по умолчанию
        self.assertIs(s["dash_autoconvert"], False)
        s.update(dash_autoconvert=1)
        self.assertIs(s["dash_autoconvert"], False)

    def test_notes_path(self):
        s = Settings(self.path)
        self.assertEqual(s.notes_path(), storage.default_path())
        s.update(data_dir="/srv/sync")
        self.assertEqual(s.notes_path(), Path("/srv/sync/notes.json"))


if __name__ == "__main__":
    unittest.main()
