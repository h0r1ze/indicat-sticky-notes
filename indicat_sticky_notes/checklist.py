"""Чекбоксы в тексте заметки: строки, начинающиеся с «☐ » или «☑ »."""

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
