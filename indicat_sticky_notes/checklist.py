"""Списки в тексте заметки: чекбоксы («☐ », «☑ ») и списки с длинным тире («— »)."""
import re

OFF = "☐ "
ON = "☑ "


def is_item(line: str) -> bool:
    return line.startswith((OFF, ON))


def is_done(line: str) -> bool:
    return line.startswith(ON)


def toggled(line: str) -> str:
    """Переключить галочку; строка без чекбокса возвращается как есть."""
    if line.startswith(OFF):
        return ON + line[len(OFF):]
    if line.startswith(ON):
        return OFF + line[len(ON):]
    return line


def converted(line: str) -> str:
    """'[ ] дело' -> '☐ дело', '[x] дело' -> '☑ дело'; иначе без изменений."""
    for marker, box in (("[ ] ", OFF), ("[x] ", ON), ("[X] ", ON)):
        if line.startswith(marker):
            return box + line[len(marker):]
    return line


def on_enter(line: str):
    """Что вставить после Enter на строке `line`.

    Возвращает "☐ " для продолжения списка, "" если строка — пустой чекбокс
    (Enter завершает список и убирает его), None если это не чекбокс.
    """
    if not is_item(line):
        return None
    return OFF if line[2:].strip() else ""


# --- список с длинным тире, как маркированный список в Word ---------------------

DASH = "— "
INDENT = "    "  # один уровень вложенности
MAX_INDENT = 3 * len(INDENT)
_DASH_ITEM = re.compile(r"^( *)— ")
_HYPHEN_ITEM = re.compile(r"^( *)- ")


def dash_indent(line: str):
    """Отступ (число пробелов) пункта списка с тире или None, если строка — не пункт."""
    match = _DASH_ITEM.match(line)
    return len(match.group(1)) if match else None


def is_dash_item(line: str) -> bool:
    return dash_indent(line) is not None


def dash_converted(line: str) -> str:
    """'- пункт' -> '— пункт' (с сохранением отступа); остальные строки без изменений."""
    match = _HYPHEN_ITEM.match(line)
    return match.group(1) + DASH + line[match.end():] if match else line


def indented(line: str) -> str:
    """Вложить пункт глубже (до трёх уровней); не-пункты не трогаем."""
    indent = dash_indent(line)
    if indent is None or indent >= MAX_INDENT:
        return line
    return INDENT + line


def outdented(line: str) -> str:
    """Вынести пункт на уровень выше; на верхнем уровне ничего не меняется."""
    indent = dash_indent(line)
    if not indent:
        return line
    return line[min(len(INDENT), indent):]


def dash_enter(line: str):
    """Что делать по Enter на строке `line`.

    None — это не пункт списка. ("continue", префикс) — начать следующий пункт с этим префиксом.
    Пустой вложенный пункт выносится на уровень выше ("outdent", новый префикс), пустой пункт
    верхнего уровня заканчивает список ("end", ""): замените строку этим префиксом.
    """
    indent = dash_indent(line)
    if indent is None:
        return None
    if line[indent + len(DASH):].strip():
        return "continue", " " * indent + DASH
    if indent > 0:
        return "outdent", " " * max(0, indent - len(INDENT)) + DASH
    return "end", ""
