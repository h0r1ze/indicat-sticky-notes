#!/usr/bin/env bash
# Запуск стикеров из корня проекта: ./run.sh
cd "$(dirname "$(readlink -f "$0")")" || exit 1
exec python3 -m indicat_sticky_notes "$@"
