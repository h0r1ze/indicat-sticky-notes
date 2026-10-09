import os
import tempfile
import unittest
from unittest import mock

from indicat_sticky_notes import autostart


class AutostartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_disabled_by_default(self):
        self.assertFalse(autostart.is_enabled())

    def test_enable_and_disable(self):
        autostart.set_enabled(True)
        self.assertTrue(autostart.is_enabled())
        self.assertTrue(str(autostart.autostart_path()).startswith(self.tmp.name))
        autostart.set_enabled(True)  # повторно — без ошибок
        autostart.set_enabled(False)
        self.assertFalse(autostart.is_enabled())
        autostart.set_enabled(False)  # и выключать выключенное тоже можно

    def test_entry_when_run_from_sources(self):
        with mock.patch("shutil.which", return_value=None):
            text = autostart.desktop_entry()
        self.assertIn("-m indicat_sticky_notes", text)
        self.assertIn("Path=", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Icon=", text)
        self.assertIn("indicat-sticky-notes.svg", text)  # значок из дерева исходников

    def test_entry_when_installed(self):
        with mock.patch("shutil.which", return_value="/usr/bin/indicat-sticky-notes"):
            text = autostart.desktop_entry()
        self.assertIn("Exec=/usr/bin/indicat-sticky-notes\n", text)
        self.assertNotIn("Path=", text)
        self.assertIn("Icon=indicat-sticky-notes\n", text)

    def test_shortcut_entry_has_no_autostart_key(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIn("X-GNOME-Autostart-enabled", autostart.desktop_entry())
            self.assertNotIn("X-GNOME-Autostart-enabled", autostart.desktop_entry(autostart=False))


class DesktopShortcutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        patcher = mock.patch.dict(os.environ, {"HOME": self.home, "XDG_CONFIG_HOME": f"{self.home}/.config"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def write_user_dirs(self, text):
        path = os.path.join(self.home, ".config")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "user-dirs.dirs"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_default_is_desktop_folder_in_home(self):
        self.assertEqual(str(autostart.desktop_dir()), f"{self.home}/Desktop")

    def test_localized_desktop_folder_is_read_from_user_dirs(self):
        self.write_user_dirs('# comment\nXDG_DESKTOP_DIR="$HOME/Рабочий стол"\nXDG_MUSIC_DIR="$HOME/Музыка"\n')
        self.assertEqual(str(autostart.desktop_dir()), f"{self.home}/Рабочий стол")

    def test_desktop_dir_equal_to_home_is_ignored(self):
        self.write_user_dirs('XDG_DESKTOP_DIR="$HOME/"\n')  # так XDG помечает «рабочего стола нет»
        self.assertEqual(str(autostart.desktop_dir()), f"{self.home}/Desktop")

    def test_create_shortcut_makes_executable_launcher_and_creates_folder(self):
        self.write_user_dirs('XDG_DESKTOP_DIR="$HOME/Рабочий стол"\n')
        with mock.patch("shutil.which", return_value=None):
            path = autostart.create_desktop_shortcut()
        self.assertEqual(str(path), f"{self.home}/Рабочий стол/Стикеры.desktop")
        self.assertTrue(os.access(path, os.X_OK))
        text = path.read_text(encoding="utf-8")
        self.assertIn("Name=Стикеры", text)
        self.assertIn("-m indicat_sticky_notes", text)
        self.assertNotIn("Autostart", text)

    def test_create_shortcut_twice_overwrites_without_error(self):
        with mock.patch("shutil.which", return_value=None):
            first = autostart.create_desktop_shortcut()
            second = autostart.create_desktop_shortcut()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
