"""Хранилище заметок: один JSON-файл с атомарной записью."""
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_COLOR = "yellow"
FORMAT_VERSION = 1


def default_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "indicat-sticky-notes"


def default_path() -> Path:
    return default_dir() / "notes.json"


@dataclass
class Note:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    text: str = ""
    color: str = DEFAULT_COLOR
    x: int = 100
    y: int = 100
    width: int = 280
    height: int = 260
    pinned: bool = False  # всегда поверх остальных окон
    hidden: bool = False  # заметка спрятана (окно закрыто)
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    def preview(self, limit: int = 60) -> str:
        """Первая непустая строка текста для списков."""
        for line in self.text.splitlines():
            line = line.strip()
            if line:
                return line if len(line) <= limit else line[: limit - 1] + "…"
        return ""


def notes_from_data(data) -> list:
    """Заметки из разобранного JSON; неизвестные поля отбрасываются.

    Бросает ValueError, если структура не похожа на файл заметок.
    """
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        raise ValueError("нет списка заметок")
    known = {f.name for f in fields(Note)}
    notes = []
    for item in data["notes"]:
        if not isinstance(item, dict):
            raise ValueError("заметка не объект")
        notes.append(Note(**{k: v for k, v in item.items() if k in known}))
    return notes


def dump_notes(notes) -> str:
    return json.dumps(
        {"version": FORMAT_VERSION, "notes": [asdict(n) for n in notes]},
        ensure_ascii=False,
        indent=2,
    )


def write_atomic(path: Path, payload: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class NoteStore:
    def __init__(self, path: Path = None):
        self.path = Path(path) if path else default_path()
        self.notes = []
        self.listeners = []  # вызываются после каждого сохранения

    def load(self):
        try:
            self.notes = notes_from_data(json.loads(self.path.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            self.notes = []

    def save(self):
        write_atomic(self.path, dump_notes(self.notes))
        for listener in list(self.listeners):
            listener()

    def get(self, note_id: str):
        return next((n for n in self.notes if n.id == note_id), None)

    def touch(self, note: Note):
        note.updated = time.time()

    def add(self, **kwargs) -> Note:
        note = Note(**kwargs)
        self.notes.append(note)
        self.save()
        return note

    def remove(self, note_id: str):
        self.notes = [n for n in self.notes if n.id != note_id]
        self.save()

    def replace_all(self, notes):
        self.notes = list(notes)
        self.save()

    def search(self, query: str):
        """Заметки, в тексте которых есть query (без учёта регистра)."""
        query = query.strip().casefold()
        if not query:
            return list(self.notes)
        return [n for n in self.notes if query in n.text.casefold()]
