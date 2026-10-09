"""Запуск приложения: автозапуск при входе и ярлык на рабочем столе."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "indicat-sticky-notes.desktop"
SHORTCUT_NAME = "Стикеры.desktop"


def autostart_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "autostart" / NAME


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def desktop_entry(autostart=True) -> str:
    """Содержимое ярлыка: установленная команда или запуск из папки с исходниками."""
    installed = shutil.which("indicat-sticky-notes")
    if installed:
        exec_line, path_line, icon = installed, "", "indicat-sticky-notes"
    else:
        exec_line = f"{sys.executable} -m indicat_sticky_notes"
        path_line = f"Path={_project_root()}\n"
        source_icon = _project_root() / "data/icons/hicolor/scalable/apps/indicat-sticky-notes.svg"
        icon = str(source_icon) if source_icon.exists() else "accessories-text-editor"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Стикеры\n"
        "Comment=Заметки на рабочем столе\n"
        f"Exec={exec_line}\n"
        f"{path_line}"
        f"Icon={icon}\n"
        "Terminal=false\n"
        + ("X-GNOME-Autostart-enabled=true\n" if autostart else "")
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


# --- ярлык на рабочем столе ---------------------------------------------------

def desktop_dir() -> Path:
    """Папка рабочего стола из ~/.config/user-dirs.dirs (бывает «Рабочий стол»), иначе ~/Desktop."""
    home = Path(os.path.expanduser("~"))
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    try:
        for line in (config / "user-dirs.dirs").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("XDG_DESKTOP_DIR="):
                value = line.split("=", 1)[1].strip().strip('"')
                path = Path(value.replace("$HOME", str(home)))
                if path != home:
                    return path
    except OSError:
        pass
    return home / "Desktop"


def create_desktop_shortcut() -> Path:
    """Создать на рабочем столе ярлык запуска. Возвращает путь к файлу."""
    folder = desktop_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SHORTCUT_NAME
    path.write_text(desktop_entry(autostart=False), encoding="utf-8")
    path.chmod(0o755)  # без права запуска файловые менеджеры показывают .desktop как текст
    if shutil.which("gio"):  # GNOME, Cinnamon, Nemo: ярлык надо пометить доверенным
        subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return path
