"""Помощники для клавиатуры."""
import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk  # noqa: E402


def is_key(event, latin_keyval):
    """Нажата ли клавиша с этой латинской буквой в любой раскладке (в том числе русской)."""
    if event.keyval in (latin_keyval, Gdk.keyval_to_upper(latin_keyval)):
        return True
    found, keys = Gdk.Keymap.get_default().get_entries_for_keyval(latin_keyval)
    return found and event.hardware_keycode in {k.keycode for k in keys}
