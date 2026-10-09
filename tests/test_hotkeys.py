"""Проверка глобальных клавиш настоящими нажатиями через XTest. Нужен X-сервер (xvfb-run)."""
import ctypes
import ctypes.util
import os
import time
import unittest

from indicat_sticky_notes import hotkeys

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    HAVE_DISPLAY = Gtk.init_check()[0]
except (ImportError, ValueError):
    HAVE_DISPLAY = False

XTEST = ctypes.util.find_library("Xtst")
XK_CONTROL_L, XK_ALT_L, XK_N, XK_S = 0xFFE3, 0xFFE9, 0x6E, 0x73


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.01)


def press_combo(*keysyms):
    """Нажать и отпустить сочетание, как пользователь (через XTest)."""
    x11, xtst = hotkeys._load_x11(), ctypes.CDLL(XTEST)
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    dpy = x11.XOpenDisplay(None)
    codes = [x11.XKeysymToKeycode(dpy, k) for k in keysyms]
    for code in codes:
        xtst.XTestFakeKeyEvent(dpy, code, 1, 0)
    for code in reversed(codes):
        xtst.XTestFakeKeyEvent(dpy, code, 0, 0)
    x11.XSync(dpy, 0)
    x11.XCloseDisplay(dpy)


class ModifiersTest(unittest.TestCase):
    def test_gdk_to_x_modifiers(self):
        self.assertEqual(hotkeys.to_x_modifiers(4 | 8), hotkeys.CONTROL | hotkeys.MOD1)
        self.assertEqual(hotkeys.to_x_modifiers(1 << 26), hotkeys.MOD4)  # Super
        self.assertEqual(hotkeys.to_x_modifiers(1), hotkeys.SHIFT)
        self.assertEqual(hotkeys.to_x_modifiers(0), 0)

    def test_unsupported_without_display(self):
        old = os.environ.pop("DISPLAY", None)
        try:
            self.assertFalse(hotkeys.supported())
            self.assertEqual(hotkeys.GlobalHotkeys().set({"a": ("<Primary><Alt>n", lambda: None)}),
                             {"a": False})
        finally:
            if old is not None:
                os.environ["DISPLAY"] = old

    def test_unsupported_on_wayland_session(self):
        old = os.environ.get("XDG_SESSION_TYPE")
        os.environ["XDG_SESSION_TYPE"] = "wayland"
        try:
            self.assertFalse(hotkeys.supported())
        finally:
            if old is None:
                del os.environ["XDG_SESSION_TYPE"]
            else:
                os.environ["XDG_SESSION_TYPE"] = old


@unittest.skipUnless(HAVE_DISPLAY and XTEST and hotkeys.supported(), "нужен X11 и libXtst")
class GrabTest(unittest.TestCase):
    def setUp(self):
        self.keys = hotkeys.GlobalHotkeys()
        self.addCleanup(self.keys.stop)

    def test_combo_triggers_callback_and_other_combo_does_not(self):
        hits = []
        result = self.keys.set({"new": ("<Primary><Alt>n", lambda: hits.append("new")),
                                "toggle": ("<Primary><Alt>s", lambda: hits.append("toggle"))})
        self.assertEqual(result, {"new": True, "toggle": True})
        press_combo(XK_CONTROL_L, XK_ALT_L, XK_N)
        pump(0.4)
        self.assertEqual(hits, ["new"])
        press_combo(XK_CONTROL_L, XK_ALT_L, XK_S)
        pump(0.4)
        self.assertEqual(hits, ["new", "toggle"])

    def test_rebinding_replaces_old_combo(self):
        hits = []
        self.keys.set({"a": ("<Primary><Alt>n", lambda: hits.append("n"))})
        self.keys.set({"a": ("<Primary><Alt>s", lambda: hits.append("s"))})
        press_combo(XK_CONTROL_L, XK_ALT_L, XK_N)
        pump(0.3)
        self.assertEqual(hits, [])  # старое сочетание освобождено
        press_combo(XK_CONTROL_L, XK_ALT_L, XK_S)
        pump(0.3)
        self.assertEqual(hits, ["s"])

    def test_clearing_releases_everything(self):
        hits = []
        self.keys.set({"a": ("<Primary><Alt>n", lambda: hits.append(1))})
        self.assertEqual(self.keys.set({}), {})
        press_combo(XK_CONTROL_L, XK_ALT_L, XK_N)
        pump(0.3)
        self.assertEqual(hits, [])

    def test_taken_combo_and_bad_accels_report_failure(self):
        other = hotkeys.GlobalHotkeys()
        self.addCleanup(other.stop)
        self.assertEqual(other.set({"x": ("<Primary><Alt>n", lambda: None)}), {"x": True})
        # то же сочетание уже занято другим соединением -> BadAccess, но приложение не падает
        self.assertEqual(self.keys.set({"y": ("<Primary><Alt>n", lambda: None)}), {"y": False})
        self.assertEqual(self.keys.set({"plain": ("n", lambda: None),       # без модификатора
                                        "junk": ("не сочетание", lambda: None),
                                        "empty": ("", lambda: None)}),
                         {"plain": False, "junk": False, "empty": False})


if __name__ == "__main__":
    unittest.main()
