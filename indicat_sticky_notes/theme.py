"""Оформление заметок: палитры и CSS."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import colors  # noqa: E402
from .storage import DEFAULT_COLOR  # noqa: E402,F401

# Основные цвета: имя -> (фон листа, фон шапки)
PALETTE = {
    "yellow": ("#fff7b8", "#ffe97d"),
    "green": ("#dcf3c8", "#bce6a0"),
    "blue": ("#d6eafc", "#acd2f7"),
    "pink": ("#fde0ea", "#f7b9cf"),
    "orange": ("#ffe4c0", "#ffca8c"),
    "purple": ("#e8defa", "#cfc0f2"),
}

# Дизайнерская палитра, 4 ряда по 8: пастельные, яркие, глубокие, тёмные.
# Цвет текста и шапки для них подбирается автоматически (см. colors.py).
DESIGNER_PALETTE = (
    "#ffd6d6", "#ffe0cc", "#fff1c1", "#e4f5c5", "#c9f0e1", "#c7ecf5", "#cfd9ff", "#e4d4fa",
    "#ff8a80", "#ffab6b", "#ffd54f", "#aed581", "#4db6ac", "#4fc3f7", "#7986cb", "#ba68c8",
    "#c62828", "#d84315", "#f9a825", "#558b2f", "#00796b", "#0277bd", "#3949ab", "#7b1fa2",
    "#2b2d31", "#3b3f46", "#2e3b32", "#1f3a4d", "#2c2a4a", "#4a2c3a", "#4a3b2c", "#111111",
)
PALETTE_COLUMNS = 8

SHADOW_MARGIN = 14  # место вокруг листа под тень

_STATIC_CSS = """
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
    font-size: 16px; font-weight: bold;
    transition: all 150ms ease-in-out;
}

.note .bar button.pin { opacity: 0.45; }
.note .bar button.pin:hover, .note .bar button.pin.active { opacity: 1; }
.note .bar button.pin.active { background-color: rgba(0,0,0,0.16); }

.note textview, .note textview text {
    background-color: rgba(0,0,0,0);
    font-family: "Open Sans", "Noto Sans", sans-serif;
    font-size: 13pt;
}
.note .placeholder { font-size: 13pt; font-style: italic; }
.note .grip { font-size: 12px; }

.swatch {
    min-width: 24px; min-height: 24px; padding: 0; border-radius: 12px;
    border: 2px solid rgba(255,255,255,0.9); box-shadow: 0 1px 4px rgba(0,0,0,0.45);
    background-image: none;
    transition: all 120ms ease-in-out;
}
.swatch:hover { box-shadow: 0 2px 7px rgba(0,0,0,0.6); }
window.palette-popup { background-color: rgba(0,0,0,0); }
.palette-card {
    background-color: #f7f6f4; color: #3b3320; border-radius: 10px;
    box-shadow: 0 8px 18px rgba(0,0,0,0.28), 0 1px 3px rgba(0,0,0,0.22);
}
.palette-card.flat { border-radius: 0; border: 1px solid rgba(0,0,0,0.35); box-shadow: none; }
.palette-card button { color: #3b3320; }
.palette-caption { font-size: 10px; font-weight: bold; color: rgba(59,51,32,0.6); }
"""


def _rgba(color, alpha):
    r, g, b = colors.parse_hex(color)
    return f"rgba({r},{g},{b},{alpha})"


def note_css(cls, body, bar):
    """CSS всего, что зависит от цвета листа; текст подбирается под фон."""
    text = colors.text_color_for(body)
    return f"""
.note.{cls} {{ background-color: {body}; }}
.note.{cls} .bar {{ background-color: {bar}; }}
.note.{cls} .bar button {{ color: {_rgba(text, 0.60)}; }}
.note.{cls} .bar button:hover {{ background-color: {_rgba(text, 0.16)}; color: {_rgba(text, 0.95)}; }}
.note.{cls} .bar button.danger:hover {{ background-color: rgba(200,40,40,0.9); color: #ffffff; }}
.note.{cls} textview, .note.{cls} textview text {{ color: {text}; caret-color: {text}; }}
.note.{cls} textview text selection {{ background-color: {_rgba(text, 0.30)}; color: {text}; }}
.note.{cls} .placeholder {{ color: {_rgba(text, 0.45)}; }}
.note.{cls} .grip {{ color: {_rgba(text, 0.40)}; }}
"""


def style_class(color):
    """Нормализованный цвет заметки: имя из PALETTE или '#rrggbb'."""
    if color in PALETTE:
        return color
    return colors.normalize(color) or DEFAULT_COLOR


def bar_color(color):
    """Цвет шапки для имени из PALETTE или для произвольного '#rrggbb'."""
    color = style_class(color)
    return PALETTE[color][1] if color in PALETTE else colors.bar_for(color)


_installed = False
_custom_classes = set()


def _add_to_screen(css):
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def install():
    """Подключить базовый CSS и стили основных цветов (один раз)."""
    global _installed
    if _installed:
        return
    parts = [_STATIC_CSS]
    parts += [note_css(name, body, bar) for name, (body, bar) in PALETTE.items()]
    _add_to_screen("\n".join(parts))
    _installed = True


def css_class_for(color):
    """CSS-класс для цвета заметки; стиль для нового цвета создаётся один раз."""
    color = style_class(color)
    if color in PALETTE:
        return color
    cls = "c-" + color[1:]
    if cls not in _custom_classes:
        _add_to_screen(note_css(cls, color, bar_color(color)))
        _custom_classes.add(cls)
    return cls


def paint_swatch(button, color):
    """Закрасить кнопку-кружок в нужный цвет."""
    provider = Gtk.CssProvider()
    provider.load_from_data(
        f"button.swatch {{ background-color: {color}; background-image: none; }}".encode()
    )
    button.get_style_context().add_provider(
        provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
