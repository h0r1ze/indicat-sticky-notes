"""Автозапуск при входе в систему через ~/.config/autostart."""
import os
import shutil
import sys
from pathlib import Path

NAME = "indicat-sticky-notes.desktop"


def autostart_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "autostart" / NAME


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def desktop_entry() -> str:
    """Содержимое ярлыка: установленная команда или запуск из папки с исходниками."""
    installed = shutil.which("indicat-sticky-notes")
    if installed:
        exec_line, path_line = installed, ""
    else:
        exec_line = f"{sys.executable} -m indicat_sticky_notes"
        path_line = f"Path={_project_root()}\n"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Стикеры\n"
        "Comment=Заметки на рабочем столе\n"
        f"Exec={exec_line}\n"
        f"{path_line}"
        "Icon=accessories-text-editor\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def is_enabled() -> bool:
    return autostart_path().exists()


def set_enabled(enabled: bool):
    path = autostart_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
