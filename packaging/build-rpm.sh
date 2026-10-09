#!/usr/bin/env bash
# Собирает .rpm (RED OS, Fedora и другие rpm-системы): ./packaging/build-rpm.sh
# Нужны: rpm-build, python3-devel, python3-rpm-macros, python3-setuptools, desktop-file-utils.
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$root"

if ! command -v rpmbuild >/dev/null; then
    echo "Не найден rpmbuild. Установите: sudo dnf install rpm-build python3-devel python3-rpm-macros" >&2
    exit 1
fi

version="$(python3 -c 'import indicat_sticky_notes as m; print(m.__version__)')"
top="$root/build/rpm"
rm -rf "$top"
mkdir -p "$top"/{SOURCES,SPECS,BUILD,RPMS,SRPMS,BUILDROOT}

# Исходники: файлы под контролем git (текущее состояние рабочей папки).
git ls-files -z | tar --null -T - \
    --transform "s,^,indicat-sticky-notes-${version}/," \
    -czf "$top/SOURCES/indicat-sticky-notes-${version}.tar.gz"

rpmbuild -ba --define "_topdir $top" packaging/rpm/indicat-sticky-notes.spec

mkdir -p "$root/build"
find "$top/RPMS" "$top/SRPMS" -name '*.rpm' -exec cp -v {} "$root/build/" \;
