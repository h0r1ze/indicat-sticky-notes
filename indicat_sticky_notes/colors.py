"""Цветовая математика без GTK: подбор шапки и цвета текста под фон заметки."""
import re

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

DARK_TEXT = "#2b2518"
LIGHT_TEXT = "#f5f1e8"
MIN_CONTRAST = 4.5  # WCAG AA для основного текста


def normalize(color):
    """'#AABBCC' -> '#aabbcc'; None, если это не цвет в формате #rrggbb."""
    if isinstance(color, str) and _HEX.match(color):
        return color.lower()
    return None


def parse_hex(color):
    color = normalize(color)
    if color is None:
        raise ValueError(f"не цвет #rrggbb: {color!r}")
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def luminance(color):
    """Относительная яркость по WCAG: 0 (чёрный) … 1 (белый)."""
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in parse_hex(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """Коэффициент контрастности WCAG, от 1 до 21."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a, b, amount):
    """Смешать цвет a с цветом b: amount=0 даёт a, amount=1 даёт b."""
    ra, rb = parse_hex(a), parse_hex(b)
    return to_hex(x + (y - x) * amount for x, y in zip(ra, rb))


def text_color_for(body):
    """Цвет текста с контрастом не ниже 4.5 на любом фоне.

    Сначала пробуем мягкие тёмный и светлый; на средней яркости ни один из них
    может не дотянуть, тогда берём чистый чёрный или белый (их лучший контраст
    не бывает ниже ~4.58).
    """
    best = max((DARK_TEXT, LIGHT_TEXT), key=lambda text: contrast(body, text))
    if contrast(body, best) >= MIN_CONTRAST:
        return best
    return max(("#000000", "#ffffff"), key=lambda text: contrast(body, text))


def bar_for(body):
    """Шапка: на светлом листе чуть темнее, на тёмном чуть светлее."""
    if luminance(body) > 0.4:
        return mix(body, "#000000", 0.13)
    return mix(body, "#ffffff", 0.10)
