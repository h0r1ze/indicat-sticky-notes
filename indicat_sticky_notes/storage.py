"""Хранилище заметок: один JSON-файл с атомарной записью."""
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_COLOR = "yellow"


def default_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "indicat-sticky-notes" / "notes.json"


@dataclass
class Note:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    text: str = ""
    color: str = DEFAULT_COLOR
    x: int = 100
    y: int = 100
    width: int = 280
    height: int = 260


class NoteStore:
    def __init__(self, path: Path = None):
        self.path = Path(path) if path else default_path()
        self.notes = []

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.notes = []
            return
        known = {f.name for f in fields(Note)}
        self.notes = [
            Note(**{k: v for k, v in item.items() if k in known})
            for item in data.get("notes", [])
        ]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"version": 1, "notes": [asdict(n) for n in self.notes]},
            ensure_ascii=False,
            indent=2,
        )
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise

    def add(self, **kwargs) -> Note:
        note = Note(**kwargs)
        self.notes.append(note)
        self.save()
        return note

    def remove(self, note_id: str):
        self.notes = [n for n in self.notes if n.id != note_id]
        self.save()
