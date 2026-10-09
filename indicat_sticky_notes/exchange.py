"""Экспорт заметок в Markdown/txt и импорт из файлов и из Mint Sticky."""
import json
import os
import re
from datetime import datetime
from pathlib import Path

from . import checklist, storage
from .storage import Note

EXPORT_MARK = "<!-- indicat-sticky-notes export v1 -->"
_META = re.compile(r"^<!-- group: (.*?); updated: (.*?) -->$")

# формат -> (открывающий, закрывающий) маркер в Markdown
MARKERS = {
    "bold": ("**", "**"),
    "italic": ("*", "*"),
    "strike": ("~~", "~~"),
    "underline": ("<u>", "</u>"),
}


# --- Markdown ---------------------------------------------------------------

def _line_ranges(text, start, end):
    """Разбить диапазон по переводам строк: маркеры форматирования не должны их пересекать."""
    pos = start
    while pos < end:
        nl = text.find("\n", pos, end)
        stop = end if nl == -1 else nl
        if stop > pos:
            yield pos, stop
        pos = stop + 1


def apply_formats(text, formats):
    """Расставить markdown-маркеры по диапазонам форматирования."""
    events = []  # (смещение, порядок, маркер): закрывающие раньше открывающих
    for item in formats:
        try:
            start, end, name = item
        except (TypeError, ValueError):
            continue
        if name not in MARKERS or not (0 <= start < end <= len(text)):
            continue
        opening, closing = MARKERS[name]
        for a, b in _line_ranges(text, start, end):
            if text[a:b].strip():
                events.append((a, 1, opening))
                events.append((b, 0, closing))
    out, last = [], 0
    for offset, _order, marker in sorted(events, key=lambda e: (e[0], e[1])):
        out.append(text[last:offset])
        out.append(marker)
        last = offset
    out.append(text[last:])
    return "".join(out)


def _tasks_to_markdown(text, formats):
    """☐/☑ -> '- [ ] '/'- [x] ' с пересчётом смещений форматирования."""
    out, shifts, pos = [], [], 0  # shifts: (смещение начала строки, на сколько вырастет)
    lines = text.split("\n")
    for line in lines:
        if checklist.is_item(line):
            box = "- [x] " if checklist.is_done(line) else "- [ ] "
            out.append(box + line[2:])
            shifts.append((pos, len(box) - 2))
        else:
            out.append(line)
        pos += len(line) + 1

    def move(offset, is_start):
        total = 0
        for line_start, grow in shifts:
            if offset > line_start + 1:
                total += grow
            elif offset == line_start and is_start:
                total += grow + 2  # формат, начатый на квадратике, начинаем после него
        return offset + total

    moved = []
    for item in formats:
        try:
            start, end, name = item
        except (TypeError, ValueError):
            continue
        moved.append([move(start, True), move(end, False), name])
    return "\n".join(out), moved


def note_to_markdown(note):
    title = note.display_title(80) or "Без названия"
    text, formats = _tasks_to_markdown(note.text, note.formats)
    updated = datetime.fromtimestamp(note.updated).strftime("%Y-%m-%d %H:%M")
    group = note.group.replace("\n", " ").replace("-->", "")
    return "\n".join([
        f"## {title}",
        f"<!-- group: {group}; updated: {updated} -->",
        "",
        apply_formats(text, formats).rstrip("\n"),
        "",
    ])


def export_markdown(notes):
    notes = [n for n in notes if n.active and not n.is_blank()]
    header = [EXPORT_MARK, "# Стикеры", ""]
    return "\n".join(header + [note_to_markdown(n) for n in notes])


def _markdown_to_text(markdown):
    """Обратное преобразование для нашего экспорта: задачи и разметка -> текст + форматы."""
    tokens = re.compile(r"\*\*|~~|</u>|<u>|\*")
    names = {"**": "bold", "~~": "strike", "<u>": "underline", "</u>": "underline", "*": "italic"}
    text, formats, opened = [], [], {}
    pos = 0
    for line in markdown.split("\n"):
        for prefix, box in (("- [ ] ", checklist.OFF), ("- [x] ", checklist.ON), ("- [X] ", checklist.ON)):
            if line.startswith(prefix):
                line = box + line[len(prefix):]
                break
        last = 0
        for match in tokens.finditer(line):
            chunk = line[last:match.start()]
            text.append(chunk)
            pos += len(chunk)
            name = names[match.group()]
            if name in opened:
                formats.append([opened.pop(name), pos, name])
            else:
                opened[name] = pos
            last = match.end()
        chunk = line[last:] + "\n"
        text.append(chunk)
        pos += len(chunk)
    result = "".join(text)
    return result[:-1], [f for f in formats if f[0] < f[1] <= len(result) - 1]


def import_markdown_export(content):
    """Заметки из файла, выгруженного export_markdown."""
    notes, current = [], None
    for line in content.split("\n"):
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "group": "", "body": []}
            notes.append(current)
        elif current is not None:
            meta = _META.match(line)
            if meta and not current["body"]:
                current["group"] = meta.group(1).strip()
            else:
                current["body"].append(line)
    result = []
    for item in notes:
        body = "\n".join(item["body"]).strip("\n")
        text, formats = _markdown_to_text(body)
        result.append(Note(text=text, formats=formats, title=item["title"], group=item["group"]))
    return result


# --- txt-файлы ---------------------------------------------------------------

def slug(name, fallback="заметка"):
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)[:60].strip(" .")
    return cleaned or fallback


def export_text_files(notes, directory):
    """По одному .txt на заметку; имена не повторяются. Возвращает список путей."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for note in notes:
        if not note.active or note.is_blank():
            continue
        base = slug(note.display_title(60))
        path, n = directory / f"{base}.txt", 1
        while path.exists():
            n += 1
            path = directory / f"{base} ({n}).txt"
        path.write_text(note.text, encoding="utf-8")
        paths.append(path)
    return paths


# --- Mint Sticky ---------------------------------------------------------------

MINT_COLORS = {
    "red": "#ffb4ab", "green": "green", "blue": "blue", "yellow": "yellow",
    "purple": "purple", "teal": "#b2dfdb", "orange": "orange", "magenta": "pink",
    "cycle": "yellow",
}
MINT_TAGS = {"bold": "bold", "italic": "italic", "underline": "underline", "strikethrough": "strike"}
_MINT_TOKEN = re.compile(r"##|#tag:([^:#\s]+):|#check:([01])|#bullet:")


def default_mint_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "sticky" / "notes.json"


def mint_markup_to_text(markup):
    """Внутренняя разметка Mint Sticky -> (текст, форматы)."""
    text, formats, opened = [], [], {}
    pos = last = 0

    def add(chunk):
        nonlocal pos
        text.append(chunk)
        pos += len(chunk)

    skip_space = False
    for match in _MINT_TOKEN.finditer(markup):
        chunk = markup[last:match.start()]
        if skip_space and chunk.startswith(" "):
            chunk = chunk[1:]
        skip_space = False
        add(chunk)
        last = match.end()
        token = match.group()
        if token == "##":
            add("#")
        elif token == "#bullet:":
            add("• ")
        elif match.group(2) is not None:
            add(checklist.ON if match.group(2) == "1" else checklist.OFF)
            skip_space = True
        else:
            name = match.group(1)
            if name in opened:
                start = opened.pop(name)
                if name in MINT_TAGS and start < pos:
                    formats.append([start, pos, MINT_TAGS[name]])
            else:
                opened[name] = pos
    tail = markup[last:]
    add(tail[1:] if skip_space and tail.startswith(" ") else tail)
    for name, start in opened.items():  # незакрытые теги тянутся до конца
        if name in MINT_TAGS and start < pos:
            formats.append([start, pos, MINT_TAGS[name]])
    return "".join(text), formats


def looks_like_mint(data):
    if not isinstance(data, dict) or "notes" in data:
        return False
    groups = data.get("notes_lists", data)
    return isinstance(groups, dict) and any(
        isinstance(v, list) and v and isinstance(v[0], dict) and "text" in v[0]
        for v in groups.values()
    )


def notes_from_mint(data):
    groups = data.get("notes_lists", data)
    notes = []
    for group, items in groups.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            text, formats = mint_markup_to_text(str(item.get("text", "")))
            notes.append(Note(
                text=text,
                formats=formats,
                title="" if item.get("title") in (None, "Untitled") else str(item["title"]),
                color=MINT_COLORS.get(item.get("color"), storage.DEFAULT_COLOR),
                group=str(group) if group not in ("Active Notes", "Notes") else "",
                x=_int(item.get("x"), 100), y=_int(item.get("y"), 100),
                width=_int(item.get("width"), 280), height=_int(item.get("height"), 260),
            ))
    return notes


def _int(value, default):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


# --- общий вход ---------------------------------------------------------------

def read_notes_file(path):
    """Заметки из .json (наш формат, копия или Mint Sticky), .md (наш экспорт или
    обычный текст) и .txt. ValueError — если файл не удалось разобрать."""
    path = Path(path)
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"не удалось прочитать {path.name}: {exc}") from exc
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}: неверный JSON") from exc
        if looks_like_mint(data):
            return notes_from_mint(data)
        return storage.notes_from_data(data)
    if suffix == ".md" and content.lstrip().startswith(EXPORT_MARK):
        return import_markdown_export(content)
    return [_plain_note(path, content, markdown=suffix == ".md")]


def _plain_note(path, content, markdown):
    title, body = path.stem, content.rstrip("\n")
    if markdown:
        first, _, rest = body.partition("\n")
        if first.startswith("# "):
            title, body = first[2:].strip(), rest.lstrip("\n")
        lines = []
        for line in body.split("\n"):
            for prefix, box in (("- [ ] ", checklist.OFF), ("- [x] ", checklist.ON), ("- [X] ", checklist.ON)):
                if line.startswith(prefix):
                    line = box + line[len(prefix):]
                    break
            lines.append(line)
        body = "\n".join(lines)
    return Note(text=body, title=title)
