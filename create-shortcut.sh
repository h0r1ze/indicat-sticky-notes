#!/usr/bin/env bash
# Создаёт ярлык «Стикеры» в корне проекта и в меню приложений.
# Путь к проекту подставляется автоматически, поэтому ярлык не хранится в git.
set -eu

dir="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
entry="[Desktop Entry]
Type=Application
Name=Стикеры
Comment=Заметки на рабочем столе
Exec=\"$dir/run.sh\"
Path=$dir
Icon=accessories-text-editor
Terminal=false
Categories=Utility;
"

apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps"
for target in "$dir/Стикеры.desktop" "$apps/indicat-sticky-notes.desktop"; do
    printf '%s' "$entry" > "$target"
    chmod +x "$target"
    echo "Создан: $target"
done
