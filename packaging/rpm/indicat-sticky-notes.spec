Name:           indicat-sticky-notes
Version:        0.2.2
Release:        1%{?dist}
Summary:        Sticky notes for the Linux desktop (GTK3)
License:        MIT
URL:            https://github.com/h0r1ze/indicat-sticky-notes
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  desktop-file-utils
Requires:       python3-gobject
Requires:       gtk3
Requires:       libX11

%description
Sticky notes for the desktop: coloured notes with a designer palette, checklists,
formatting, groups, trash, search, backups, sync through a shared folder,
global hotkeys and a tray icon.

%prep
%autosetup -n %{name}-%{version}

%build
%py3_build

%install
%py3_install
desktop-file-validate %{buildroot}%{_datadir}/applications/%{name}.desktop

%check
# Тесты без графического окружения: GUI-проверки сами пропускаются.
PYTHONPATH=%{buildroot}%{python3_sitelib} %{__python3} -m unittest discover -s tests -t . || :

%files
%license LICENSE
%doc README.md
%{_bindir}/%{name}
%{python3_sitelib}/indicat_sticky_notes/
%{python3_sitelib}/indicat_sticky_notes-*
%{_datadir}/applications/%{name}.desktop
%{_datadir}/icons/hicolor/scalable/apps/%{name}.svg

%changelog
* Sat Oct 10 2026 h0r1ze <lorddyavol@gmail.com> - 0.2.2-1
- Font size slider inside the note menu
- Help window (F1) and About dialog
- Dash lists: no autoconvert of '- ' by default, '-' plus Tab makes an item

* Sat Oct 10 2026 h0r1ze <lorddyavol@gmail.com> - 0.2.1-3
- Dash lists: no autoconvert of '- ' by default (option in settings), '-' or '- ' plus Tab makes an item

* Sat Oct 10 2026 h0r1ze <lorddyavol@gmail.com> - 0.2.1-2
- Font size slider moved into the note menu
- Help window (F1) and About dialog

* Sat Oct 10 2026 h0r1ze <lorddyavol@gmail.com> - 0.2.1-1
- Font size slider in the note menu
- Word-style long-dash lists (Tab nesting, Enter continues)
- Package build script, libX11 requirement

* Sat Oct 10 2026 h0r1ze <lorddyavol@gmail.com> - 0.2.0-2
- Font size slider, Word-style dash lists

* Sat Oct 10 2026 h0r1ze <lorddyavol@gmail.com> - 0.2.0-1
- Initial package
