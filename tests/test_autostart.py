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

    def test_entry_when_installed(self):
        with mock.patch("shutil.which", return_value="/usr/bin/indicat-sticky-notes"):
            text = autostart.desktop_entry()
        self.assertIn("Exec=/usr/bin/indicat-sticky-notes\n", text)
        self.assertNotIn("Path=", text)


if __name__ == "__main__":
    unittest.main()
