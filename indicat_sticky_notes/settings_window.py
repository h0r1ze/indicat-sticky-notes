"""Окно настроек: изменения применяются сразу."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import autostart, colors, hotkeys, storage  # noqa: E402

THEME_LABELS = (("system", "Как в системе"), ("light", "Светлая"), ("dark", "Тёмная"))
TRAY_LABELS = (("toggle", "Показать или скрыть все заметки"), ("manager", "Открыть менеджер заметок"))
HOTKEYS = (("hotkey_new", "new", "Новая заметка"), ("hotkey_toggle", "toggle", "Показать или скрыть все"))
ACCEL_MASK = (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK
              | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.SUPER_MASK)


def accel_label(accel: str) -> str:
    """'<Primary><Alt>n' -> 'Ctrl+Alt+N' для показа пользователю."""
    if not accel:
        return "не задано"
    key, mods = Gtk.accelerator_parse(accel)
    return Gtk.accelerator_get_label(key, mods) if key else accel


class SettingsWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title="Настройки")
        self.app = app
        self.settings = app.settings
        self._capturing = None  # ключ настройки, для которой ждём сочетание
        self._loading = True

        self.set_default_size(520, -1)
        self.set_border_width(14)
        self.set_resizable(False)

        grid = Gtk.Grid(row_spacing=10, column_spacing=14)
        self.add(grid)
        self._row = 0

        self.theme_combo = self._combo("Тема интерфейса", THEME_LABELS, self._on_theme)
        self.color_combo = self._combo("Цвет новых заметок", self._color_choices(), self._on_color)
        self.font_spin = self._spin("Размер шрифта по умолчанию, пт", 8, 40, self._on_font)
        self.tray_combo = self._combo("Клик по значку в трее", TRAY_LABELS, self._on_tray)
        self.trash_spin = self._spin("Хранить удалённые заметки, дней", 1, 365, self._on_trash)

        self.autostart_switch = Gtk.Switch(halign=Gtk.Align.START)
        self.autostart_switch.connect(
            "notify::active", lambda s, _p: autostart.set_enabled(s.get_active())
        )
        self._attach("Запускать при входе в систему", self.autostart_switch)

        shortcut = Gtk.Button(label="Создать ярлык на рабочем столе", halign=Gtk.Align.START)
        shortcut.connect("clicked", lambda _b: self.app.create_desktop_shortcut())
        self._attach("Ярлык запуска", shortcut)

        self._section("Синхронизация")
        self.dir_label = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=44)
        self._attach("Папка с заметками", self.dir_label)
        buttons = Gtk.Box(spacing=6)
        choose = Gtk.Button(label="Выбрать папку…")
        choose.connect("clicked", lambda _b: self._choose_dir())
        reset = Gtk.Button(label="По умолчанию")
        reset.connect("clicked", lambda _b: self.settings.update(data_dir=""))
        buttons.pack_start(choose, False, False, 0)
        buttons.pack_start(reset, False, False, 0)
        self._attach("", buttons)
        self._note(
            "Чтобы синхронизировать заметки между компьютерами, выберите папку, которую "
            "синхронизирует Syncthing, Nextcloud, Яндекс.Диск и т. п. Изменения с других "
            "компьютеров подхватываются автоматически; при конфликте побеждает более новая правка."
        )

        self._section("Горячие клавиши")
        self.hotkey_buttons, self.hotkey_labels = {}, {}
        for key, name, label in HOTKEYS:
            button = Gtk.Button()
            button.connect("clicked", lambda _b, k=key: self._start_capture(k))
            status = Gtk.Label(xalign=0)
            row = Gtk.Box(spacing=10)
            row.pack_start(button, False, False, 0)
            row.pack_start(status, False, False, 0)
            self._attach(label, row)
            self.hotkey_buttons[key], self.hotkey_labels[name] = button, status
        self.hotkey_note = self._note("")
        self.connect("key-press-event", self._on_key_press)

        self.settings.listeners.append(self._on_settings_changed)
        self.connect("destroy", lambda _w: self.settings.listeners.remove(self._on_settings_changed))
        self.connect("delete-event", lambda w, _e: w.hide() or True)
        self._load_values()
        grid.show_all()
        self._grid = grid

    # --- построение ---

    def _attach(self, label, widget):
        grid = self.get_child()
        if label:
            grid.attach(Gtk.Label(label=label, xalign=0), 0, self._row, 1, 1)
        grid.attach(widget, 1, self._row, 1, 1)
        self._row += 1

    def _section(self, title):
        label = Gtk.Label(xalign=0, margin_top=8)
        label.set_markup(f"<b>{title}</b>")
        self.get_child().attach(label, 0, self._row, 2, 1)
        self._row += 1

    def _note(self, text):
        label = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=60)
        label.get_style_context().add_class("dim-label")
        self.get_child().attach(label, 0, self._row, 2, 1)
        self._row += 1
        return label

    def _combo(self, title, choices, callback):
        combo = Gtk.ComboBoxText()
        for value, label in choices:
            combo.append(value, label)
        combo.connect("changed", lambda c: None if self._loading else callback(c.get_active_id()))
        self._attach(title, combo)
        return combo

    def _spin(self, title, low, high, callback):
        spin = Gtk.SpinButton.new_with_range(low, high, 1)
        spin.connect("value-changed", lambda s: None if self._loading else callback(s.get_value_as_int()))
        self._attach(title, spin)
        return spin

    def _color_choices(self):
        choices = list(colors.NAMED_LABELS.items())
        current = self.settings["default_color"]
        if current not in colors.NAMED:
            choices.append((current, f"Особый ({current})"))
        return choices

    # --- значения ---

    def present_window(self):
        self._load_values()
        self.show_all()
        self.present()

    def _load_values(self):
        self._loading = True
        s = self.settings
        self.theme_combo.set_active_id(s["theme"])
        self.tray_combo.set_active_id(s["tray_click"])
        self.font_spin.set_value(s["default_font_size"])
        self.trash_spin.set_value(s["trash_days"])
        if not self.color_combo.set_active_id(s["default_color"]):
            self.color_combo.append(s["default_color"], f"Особый ({s['default_color']})")
            self.color_combo.set_active_id(s["default_color"])
        self.autostart_switch.set_active(autostart.is_enabled())
        folder = s["data_dir"]
        self.dir_label.set_text(folder or f"По умолчанию ({storage.default_dir()})")
        self._refresh_hotkeys()
        self._loading = False

    def _on_settings_changed(self, _changed):
        self._load_values()

    def _on_theme(self, value):
        self.settings.update(theme=value)

    def _on_color(self, value):
        self.settings.update(default_color=value)

    def _on_font(self, value):
        self.settings.update(default_font_size=value)

    def _on_tray(self, value):
        self.settings.update(tray_click=value)

    def _on_trash(self, value):
        self.settings.update(trash_days=value)

    def _choose_dir(self):
        dialog = Gtk.FileChooserDialog(
            title="Папка с заметками", transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Выбрать", Gtk.ResponseType.OK)
        folder = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        if folder:
            self.settings.update(data_dir=folder)

    # --- горячие клавиши ---

    def _refresh_hotkeys(self):
        for key, name, _label in HOTKEYS:
            capturing = self._capturing == key
            self.hotkey_buttons[key].set_label(
                "Нажмите сочетание…" if capturing else accel_label(self.settings[key])
            )
            status = self.app.hotkey_status.get(name)
            if not self.settings[key]:
                text = "отключено"
            elif not hotkeys.supported():
                text = ""
            elif status is None:
                text = ""
            else:
                text = "✓ работает" if status else "⚠ занято другой программой"
            self.hotkey_labels[name].set_text(text)
        self.hotkey_note.set_text(
            "Нажмите на кнопку и затем сочетание с Ctrl, Alt, Shift или Super. "
            "Backspace отключает сочетание, Esc отменяет."
            if hotkeys.supported()
            else "Глобальные горячие клавиши недоступны: они работают только в сеансе X11 (не Wayland)."
        )

    def _start_capture(self, key):
        self._capturing = key
        self._refresh_hotkeys()

    def _on_key_press(self, _widget, event):
        if self._capturing is None:
            if event.keyval == Gdk.KEY_F1:
                self.app.open_help()
                return True
            return False
        key, self._capturing = self._capturing, None
        keyval = Gdk.keyval_to_lower(event.keyval)
        if keyval == Gdk.KEY_Escape:
            pass
        elif keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete):
            self.settings.update(**{key: ""})
        elif event.state & ACCEL_MASK and not _is_modifier_key(keyval):
            accel = Gtk.accelerator_name(keyval, event.state & ACCEL_MASK)
            self.settings.update(**{key: accel})
        self._refresh_hotkeys()
        return True


def _is_modifier_key(keyval):
    return keyval in (
        Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
        Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R,
        Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift,
    )
