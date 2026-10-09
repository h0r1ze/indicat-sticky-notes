"""Хранилище заметок: один JSON-файл с атомарной записью."""
import hashlib
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
    title: str = ""
    collapsed: bool = False  # свёрнута до одной шапки
    opacity: float = 1.0
    font_size: int = 0  # пт; 0 — размер по умолчанию из настроек
    group: str = ""
    formats: list = field(default_factory=list)  # [[начало, конец, "bold"], ...]
    deleted_at: float = 0.0  # когда отправлена в корзину; 0 — не в корзине
    purged: bool = False  # удалена из корзины; остаётся «надгробием» для синхронизации

    @property
    def in_trash(self) -> bool:
        return self.deleted_at > 0 and not self.purged

    @property
    def active(self) -> bool:
        return self.deleted_at == 0 and not self.purged

    def preview(self, limit: int = 60) -> str:
        """Первая непустая строка текста для списков."""
        for line in self.text.splitlines():
            line = line.strip()
            if line:
                return line if len(line) <= limit else line[: limit - 1] + "…"
        return ""

    def display_title(self, limit: int = 60) -> str:
        """Заголовок, а если его нет — начало текста."""
        return self.title.strip() or self.preview(limit)

    def is_blank(self) -> bool:
        return not self.text.strip() and not self.title.strip()


# Поля, которые на каждом компьютере свои: при слиянии у уже известных заметок
# не перезаписываются (окно лежит в разных местах разных экранов).
LOCAL_FIELDS = ("x", "y", "width", "height", "pinned", "hidden", "collapsed")
TRASH_DAYS = 30
TOMBSTONE_DAYS = 30


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


def digest(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


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
        self.last_digest = None  # отпечаток того, что мы сами записали в файл
        self.corrupt_file = None  # куда отложен повреждённый файл при загрузке
        self.merge_hook = None  # вызывается (добавлены, изменены), если при записи слились чужие правки

    def load(self):
        try:
            self.notes = self.read_disk()
            self.last_digest = digest(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.notes = []
        except (OSError, ValueError) as exc:
            # Файл есть, но не читается: откладываем его в сторону, чтобы
            # следующее сохранение не затёрло то, что в нём осталось.
            self.notes = []
            self._set_aside_corrupt(exc)

    def read_disk(self):
        """Заметки из файла. FileNotFoundError, если файла нет; ValueError, если он битый."""
        try:
            return notes_from_data(json.loads(self.path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise ValueError(f"неверный JSON: {exc}") from exc

    def _set_aside_corrupt(self, exc):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            os.replace(self.path, target)
            self.corrupt_file = target
        except OSError:
            self.corrupt_file = None

    def save(self):
        # Если файл за это время изменили снаружи (синхронизация, другой компьютер),
        # сначала вливаем чужие правки, иначе наша запись их затёрла бы.
        added, changed = self.sync_from_disk()
        payload = dump_notes(self.notes)
        write_atomic(self.path, payload)
        self.last_digest = digest(payload)
        if (added or changed) and self.merge_hook is not None:
            self.merge_hook(added, changed)
        for listener in list(self.listeners):
            listener()

    def sync_from_disk(self):
        """Влить правки, сделанные в файле не нами. Возвращает (добавлены, изменены).

        Ничего не записывает. Если файла нет, он не читается или мы его ещё не
        загружали, ничего не делает.
        """
        if self.last_digest is None or not self.disk_changed_externally():
            return [], []
        try:
            return self.merge(self.read_disk())
        except (OSError, ValueError):
            return [], []  # синхронизатор мог не дописать файл: попробуем при следующей записи

    def disk_changed_externally(self):
        """True, если файл на диске отличается от того, что мы записали последним."""
        try:
            return digest(self.path.read_text(encoding="utf-8")) != self.last_digest
        except OSError:
            return False

    # --- выборки ---

    @property
    def active_notes(self):
        return [n for n in self.notes if n.active]

    @property
    def trash_notes(self):
        return [n for n in self.notes if n.in_trash]

    def groups(self):
        """Названия групп, в которых есть живые заметки, по алфавиту."""
        return sorted({n.group for n in self.active_notes if n.group}, key=str.casefold)

    def get(self, note_id: str):
        return next((n for n in self.notes if n.id == note_id), None)

    def search(self, query: str, group=None, notes=None):
        """Живые заметки, где query встречается в тексте или заголовке.

        group: None — любая группа, "" — без группы, иначе — название группы.
        """
        query = query.strip().casefold()
        found = []
        for note in self.active_notes if notes is None else notes:
            if group is not None and note.group != group:
                continue
            if query and query not in note.text.casefold() and query not in note.title.casefold():
                continue
            found.append(note)
        return found

    # --- изменения ---

    def touch(self, note: Note):
        note.updated = time.time()

    def add(self, **kwargs) -> Note:
        note = Note(**kwargs)
        self.notes.append(note)
        self.save()
        return note

    def remove(self, note_id: str):
        """Стереть заметку совсем (без корзины)."""
        self.notes = [n for n in self.notes if n.id != note_id]
        self.save()

    def move_to_trash(self, note_id: str):
        note = self.get(note_id)
        if note is not None and note.active:
            note.deleted_at = note.updated = time.time()
            self.save()

    def restore(self, note_id: str):
        note = self.get(note_id)
        if note is not None and note.in_trash:
            note.deleted_at = 0.0
            note.hidden = False
            note.updated = time.time()
            self.save()

    def purge(self, note_id: str):
        """Удалить из корзины навсегда. Остаётся «надгробие» без текста,
        чтобы удаление дошло до других компьютеров при синхронизации."""
        note = self.get(note_id)
        if note is not None and not note.purged:
            self._purge_note(note, time.time())
            self.save()

    def empty_trash(self):
        now = time.time()
        for note in self.trash_notes:
            self._purge_note(note, now)
        self.save()

    @staticmethod
    def _purge_note(note, now):
        note.purged = True
        note.text = note.title = note.group = ""
        note.formats = []
        note.updated = now
        if not note.deleted_at:
            note.deleted_at = now

    def cleanup(self, now=None, trash_days=TRASH_DAYS):
        """Старую корзину — в «надгробия», старые «надгробия» — стереть.
        Возвращает True, если что-то изменилось (и файл сохранён)."""
        now = now or time.time()
        changed = False
        for note in list(self.notes):
            if note.purged and now - note.updated > TOMBSTONE_DAYS * 86400:
                self.notes.remove(note)
                changed = True
            elif note.in_trash and now - note.deleted_at > trash_days * 86400:
                self._purge_note(note, now)
                changed = True
        if changed:
            self.save()
        return changed

    def replace_all(self, notes):
        self.notes = list(notes)
        self.save()

    # --- слияние (синхронизация) ---

    def merge(self, other_notes):
        """Влить заметки с диска/другого компьютера: побеждает более новая правка.

        У уже известных заметок свои координаты и состояние окна сохраняются
        (LOCAL_FIELDS). Возвращает (добавлены, изменены) — списки id.
        Файл не сохраняется: это решает вызывающий.
        """
        mine = {n.id: n for n in self.notes}
        added, changed = [], []
        for theirs in other_notes:
            known = mine.get(theirs.id)
            if known is None:
                self.notes.append(theirs)
                added.append(theirs.id)
            elif theirs.updated > known.updated:
                for f in fields(Note):
                    if f.name not in LOCAL_FIELDS:
                        setattr(known, f.name, getattr(theirs, f.name))
                changed.append(known.id)
        return added, changed
