"""Оформление заметок: палитра и CSS."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .storage import DEFAULT_COLOR  # noqa: E402,F401

# имя цвета -> (фон листа, фон шапки)
PALETTE = {
    "yellow": ("#fff7b8", "#ffe97d"),
    "green": ("#dcf3c8", "#bce6a0"),
    "blue": ("#d6eafc", "#acd2f7"),
    "pink": ("#fde0ea", "#f7b9cf"),
    "orange": ("#ffe4c0", "#ffca8c"),
    "purple": ("#e8defa", "#cfc0f2"),
}
SHADOW_MARGIN = 14  # место вокруг листа под тень

_CSS_TEMPLATE = """
window.sticky { background-color: rgba(0,0,0,0); }

.note {
    border-radius: 12px;
    box-shadow: 0 8px 18px rgba(0,0,0,0.28), 0 1px 3px rgba(0,0,0,0.22);
}
.note.flat { border-radius: 0; border: 1px solid rgba(0,0,0,0.35); box-shadow: none; }

.note .bar { border-radius: 12px 12px 0 0; padding: 4px 6px; }
.note.flat .bar { border-radius: 0; }
.note .bar button {
    min-width: 26px; min-height: 26px; padding: 0;
    border: none; border-radius: 13px; box-shadow: none; background: none;
    color: rgba(40,30,0,0.50); font-size: 16px; font-weight: bold;
    transition: all 150ms ease-in-out;
}
.note .bar button:hover { background-color: rgba(0,0,0,0.12); color: rgba(40,30,0,0.90); }
.note .bar button.danger:hover { background-color: rgba(200,40,40,0.85); color: #fff; }

.note textview, .note textview text {
    background-color: rgba(0,0,0,0);
    color: #3b3320;
    font-family: "Open Sans", "Noto Sans", sans-serif;
    font-size: 13pt;
}
.note textview text selection { background-color: rgba(60,40,0,0.25); color: #3b3320; }
.note .placeholder { color: rgba(59,51,32,0.40); font-size: 13pt; font-style: italic; }
.note .grip { color: rgba(40,30,0,0.35); font-size: 12px; }

.swatch {
    min-width: 24px; min-height: 24px; padding: 0; border-radius: 12px;
    border: 2px solid rgba(255,255,255,0.9); box-shadow: 0 1px 3px rgba(0,0,0,0.35);
    transition: all 120ms ease-in-out;
}
.swatch:hover { box-shadow: 0 2px 6px rgba(0,0,0,0.5); }
"""


def build_css() -> str:
    parts = [_CSS_TEMPLATE]
    for name, (body, bar) in PALETTE.items():
        parts.append(
            f".note.{name} {{ background-color: {body}; }}"
            f".note.{name} .bar {{ background-color: {bar}; }}"
            f".swatch.{name} {{ background-color: {bar}; background-image: none; }}"
        )
    return "\n".join(parts)


_installed = False


def install():
    """Подключить CSS ко всему приложению (один раз)."""
    global _installed
    if _installed:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(build_css().encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _installed = True
