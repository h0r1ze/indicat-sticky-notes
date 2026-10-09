"""Настройки приложения: один JSON-файл в ~/.config (всегда локальный)."""
import json
import os
from pathlib import Path

from . import colors, storage

DEFAULTS = {
    "data_dir": "",  # "" — папка по умолчанию; иначе, например, папка Syncthing
    "default_color": "yellow",  # имя из colors.NAMED или #rrggbb
    "default_font_size": 13,  # пт
    "tray_click": "toggle",  # toggle — показать/скрыть все, manager — открыть менеджер
    "theme": "system",  # system | light | dark
    "hotkey_new": "<Primary><Alt>n",
    "hotkey_toggle": "<Primary><Alt>s",
    "trash_days": storage.TRASH_DAYS,
    "dash_autoconvert": False,  # «- » в начале строки сразу превращать в длинное тире
}
CHOICES = {
    "tray_click": ("toggle", "manager"),
    "theme": ("system", "light", "dark"),
}
RANGES = {
    "default_font_size": (8, 40),
    "trash_days": (1, 365),
}


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "indicat-sticky-notes" / "settings.json"


def validate(key, value):
    """Значение, если оно допустимо для ключа; иначе значение по умолчанию."""
    default = DEFAULTS[key]
    if key in CHOICES:
        return value if value in CHOICES[key] else default
    if key in RANGES:
        low, high = RANGES[key]
        ok = isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
        return value if ok else default
    if key == "default_color":
        ok = isinstance(value, str) and (value in colors.NAMED or colors.normalize(value))
        return colors.normalize(value) or value if ok else default
    if key == "dash_autoconvert":
        return value if isinstance(value, bool) else default
    if key == "data_dir":
        return value if isinstance(value, str) else default
    return value if isinstance(value, str) else default  # горячие клавиши


class Settings:
    def __init__(self, path: Path = None):
        self.path = Path(path) if path else default_path()
        self.values = dict(DEFAULTS)
        self.listeners = []  # вызываются с именами изменившихся ключей

    def __getitem__(self, key):
        return self.values[key]

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        self.values = {k: validate(k, data.get(k, d)) for k, d in DEFAULTS.items()}

    def save(self):
        storage.write_atomic(self.path, json.dumps(self.values, ensure_ascii=False, indent=2))

    def update(self, **changes):
        """Изменить настройки, сохранить и сообщить подписчикам."""
        unknown = set(changes) - set(DEFAULTS)
        if unknown:
            raise KeyError(f"нет таких настроек: {', '.join(sorted(unknown))}")
        changed = []
        for key, value in changes.items():
            value = validate(key, value)
            if value != self.values[key]:
                self.values[key] = value
                changed.append(key)
        if changed:
            self.save()
            for listener in list(self.listeners):
                listener(changed)
        return changed

    def notes_path(self) -> Path:
        """Где лежит notes.json: в выбранной папке данных или по умолчанию."""
        folder = self.values["data_dir"]
        return Path(folder) / "notes.json" if folder else storage.default_path()
