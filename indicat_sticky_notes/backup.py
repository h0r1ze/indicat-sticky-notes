"""Резервные копии заметок: ручные, автоматические и «перед восстановлением»."""
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import storage

KEEP = 30
AUTO_INTERVAL = timedelta(hours=20)
REASONS = ("auto", "manual", "before-restore")
_NAME = re.compile(r"^notes-(\d{8}-\d{6})(?:-\d+)?-([a-z-]+)\.json$")


def default_dir() -> Path:
    return storage.default_dir() / "backups"


@dataclass
class Backup:
    path: Path
    created: datetime
    reason: str


def create(notes, reason="manual", directory=None, now=None):
    """Записать копию. Путь файла или None, если копировать нечего."""
    if reason not in REASONS:
        raise ValueError(f"неизвестная причина копии: {reason}")
    if not notes:
        return None
    directory = Path(directory) if directory else default_dir()
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = directory / f"notes-{stamp}-{reason}.json"
    counter = 1
    while path.exists():  # две копии в одну секунду
        counter += 1
        path = directory / f"notes-{stamp}-{counter}-{reason}.json"
    storage.write_atomic(path, storage.dump_notes(notes))
    prune(directory)
    return path


def default_name(now=None) -> str:
    """Имя файла для ручной копии, которое предлагается по умолчанию."""
    return f"notes-{(now or datetime.now()).strftime('%Y%m%d-%H%M%S')}-manual.json"


def save_to(notes, path):
    """Записать копию в выбранный пользователем файл (без ограничения числа копий).

    Расширение .json добавляется, если его нет. Возвращает итоговый путь.
    """
    path = Path(path)
    if path.suffix.lower() != ".json":
        path = path.with_name(path.name + ".json")
    storage.write_atomic(path, storage.dump_notes(notes))
    return path


def list_backups(directory=None):
    """Копии из папки, новые первыми."""
    directory = Path(directory) if directory else default_dir()
    found = []
    for path in directory.glob("notes-*.json") if directory.exists() else []:
        match = _NAME.match(path.name)
        if match:
            created = datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
            found.append(Backup(path, created, match.group(2)))
    return sorted(found, key=lambda b: (b.created, b.path.name), reverse=True)


def prune(directory=None, keep=KEEP):
    """Оставить `keep` самых новых копий."""
    for old in list_backups(directory)[keep:]:
        old.path.unlink(missing_ok=True)


def auto_if_due(notes, directory=None, now=None):
    """Сделать автокопию, если свежей (моложе AUTO_INTERVAL) ещё нет."""
    now = now or datetime.now()
    for backup in list_backups(directory):
        if backup.reason == "auto" and now - backup.created < AUTO_INTERVAL:
            return None
    return create(notes, "auto", directory, now)


def load(path):
    """Заметки из файла копии. ValueError, если файл не похож на копию."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"не удалось прочитать файл: {exc}") from exc
    return storage.notes_from_data(data)
