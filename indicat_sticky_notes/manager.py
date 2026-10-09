"""Менеджер заметок: список с поиском, группами и корзиной."""
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import theme  # noqa: E402
from .keys import is_key  # noqa: E402

COL_ID, COL_DOT, COL_TITLE, COL_GROUP, COL_STATE, COL_TIME, COL_SORT = range(7)
# Не "\0..." : GTK обрезает строки по NUL, и оба идентификатора превращались в "".
ALL_GROUPS = "\x1fall"
NO_GROUP = "\x1fnone"


def format_time(stamp: float, now: float = None) -> str:
    now = now or time.time()
    local, today = time.localtime(stamp), time.localtime(now)
    if local[:3] == today[:3]:
        return time.strftime("%H:%M", local)
    return time.strftime("%d.%m.%Y", local)


def _dim(renderer_args=None):
    return Gtk.CellRendererText(foreground="#888888")


class ManagerWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title="Заметки")
        self.app = app
        self.store = app.store
        self._refresh_source = None
        self._updating_groups = False

        self.set_default_size(620, 500)
        self.set_border_width(10)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(root)

        self.stack = Gtk.Stack()
        switcher = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.CENTER)
        root.pack_start(switcher, False, False, 0)
        root.pack_start(self.stack, True, True, 0)

        self.notes_page = self._build_notes_page()
        self.trash_page = self._build_trash_page()
        self.stack.add_titled(self.notes_page, "notes", "Заметки")
        self.stack.add_titled(self.trash_page, "trash", "Корзина")

        self.store.listeners.append(self._schedule_refresh)
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_f1)
        self.connect("delete-event", lambda w, _e: w.hide() or True)
        self.refresh()
        root.show_all()

    def _on_destroy(self, _widget):
        if self._refresh_source is not None:
            GLib.source_remove(self._refresh_source)
            self._refresh_source = None
        if self._schedule_refresh in self.store.listeners:
            self.store.listeners.remove(self._schedule_refresh)

    def _on_f1(self, _widget, event):
        if event.keyval == Gdk.KEY_F1:
            self.app.open_help()
            return True
        return False

    # --- построение ---

    def _make_tree(self, with_group):
        model = Gtk.ListStore(str, str, str, str, str, str, float)
        model.set_sort_column_id(COL_SORT, Gtk.SortType.DESCENDING)
        tree = Gtk.TreeView(model=model)
        tree.set_headers_visible(False)
        tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        tree.connect("key-press-event", self._on_tree_key, model)
        tree.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), markup=COL_DOT))
        title_col = Gtk.TreeViewColumn(
            "Заметка", Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END), text=COL_TITLE
        )
        title_col.set_expand(True)
        tree.append_column(title_col)
        if with_group:
            tree.append_column(Gtk.TreeViewColumn("", _dim(), text=COL_GROUP))
            tree.append_column(Gtk.TreeViewColumn("", _dim(), text=COL_STATE))
        tree.append_column(Gtk.TreeViewColumn("", _dim(), text=COL_TIME))
        scroll = Gtk.ScrolledWindow()
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(tree)
        return model, tree, scroll

    def _build_notes_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        top = Gtk.Box(spacing=6)
        self.search = Gtk.SearchEntry(placeholder_text="Поиск по заголовкам и тексту")
        self.search.connect("search-changed", lambda _e: self.refresh())
        top.pack_start(self.search, True, True, 0)
        self.group_combo = Gtk.ComboBoxText()
        self.group_combo.connect("changed", self._on_group_changed)
        top.pack_start(self.group_combo, False, False, 0)
        page.pack_start(top, False, False, 0)

        self.model, self.tree, scroll = self._make_tree(with_group=True)
        self.tree.connect("row-activated", lambda *_a: self._show_selected())
        self.tree.get_selection().connect("changed", lambda _s: self._update_buttons())
        page.pack_start(scroll, True, True, 0)

        self.status = Gtk.Label(halign=Gtk.Align.START)
        page.pack_start(self.status, False, False, 0)

        buttons = Gtk.Box(spacing=6)
        self.new_button = self._button("Новая", self.app.new_note)
        self.show_button = self._button("Показать", self._show_selected)
        self.hide_button = self._button("Скрыть", self._hide_selected)
        self.show_group_button = self._button("Показать группу", lambda: self._set_group_visible(True))
        self.hide_group_button = self._button("Скрыть группу", lambda: self._set_group_visible(False))
        self.trash_button = self._button("В корзину", self._trash_selected)
        for button in (self.new_button, self.show_button, self.hide_button,
                       self.show_group_button, self.hide_group_button):
            buttons.pack_start(button, False, False, 0)
        buttons.pack_end(self.trash_button, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    def _build_trash_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        hint = Gtk.Label(halign=Gtk.Align.START, wrap=True)
        hint.set_markup(
            f'<span size="small">Заметки хранятся в корзине {self.app.settings["trash_days"]} '
            "дн., потом удаляются навсегда.</span>"
        )
        self.trash_hint = hint
        page.pack_start(hint, False, False, 0)

        self.trash_model, self.trash_tree, scroll = self._make_tree(with_group=False)
        self.trash_tree.get_selection().connect("changed", lambda _s: self._update_buttons())
        page.pack_start(scroll, True, True, 0)

        buttons = Gtk.Box(spacing=6)
        self.restore_button = self._button("Восстановить", self._restore_selected)
        self.purge_button = self._button("Удалить навсегда", self._purge_selected)
        self.empty_button = self._button("Очистить корзину", self._empty_trash)
        buttons.pack_start(self.restore_button, False, False, 0)
        buttons.pack_end(self.empty_button, False, False, 0)
        buttons.pack_end(self.purge_button, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    @staticmethod
    def _button(label, callback):
        button = Gtk.Button(label=label)
        button.connect("clicked", lambda _b: callback())
        return button

    # --- данные ---

    def present_with_search(self, focus_search=False):
        self.refresh()
        self.stack.set_visible_child_name("notes")
        self.show_all()
        self.present()
        if focus_search:
            self.search.grab_focus()

    def _schedule_refresh(self):
        if self._refresh_source is None and self.get_visible():
            self._refresh_source = GLib.idle_add(self._refresh_idle)

    def _refresh_idle(self):
        self._refresh_source = None
        self.refresh()
        return False

    def current_group(self):
        """None — все группы, "" — без группы, иначе название группы."""
        active = self.group_combo.get_active_id()
        if active in (None, ALL_GROUPS):
            return None
        return "" if active == NO_GROUP else active

    def _fill_groups(self):
        previous = self.group_combo.get_active_id() or ALL_GROUPS
        groups = self.store.groups()
        self._updating_groups = True
        self.group_combo.remove_all()
        self.group_combo.append(ALL_GROUPS, "Все группы")
        self.group_combo.append(NO_GROUP, "Без группы")
        for name in groups:
            self.group_combo.append(name, name)
        if not self.group_combo.set_active_id(previous):
            self.group_combo.set_active_id(ALL_GROUPS)
        self._updating_groups = False

    def _on_group_changed(self, _combo):
        if not self._updating_groups:
            self.refresh()

    def refresh(self):
        selected = self._selected(self.tree)
        selected_trash = self._selected(self.trash_tree)
        self._fill_groups()
        notes = self.store.search(self.search.get_text(), group=self.current_group())
        self.model.clear()
        for note in notes:
            self.model.append([
                note.id, self._dot(note),
                note.display_title() or "(пустая заметка)",
                note.group, "скрыта" if note.hidden else "",
                format_time(note.updated), note.updated,
            ])
        total = len(self.store.active_notes)
        self.status.set_text(
            f"Заметок: {total}" if len(notes) == total else f"Найдено {len(notes)} из {total}"
        )
        self._select(self.tree, selected)

        trash = self.store.trash_notes
        self.trash_model.clear()
        for note in trash:
            self.trash_model.append([
                note.id, self._dot(note),
                note.display_title() or "(пустая заметка)",
                "", "", f"удалена {format_time(note.deleted_at)}", note.deleted_at,
            ])
        self._select(self.trash_tree, selected_trash)
        self.stack.child_set_property(
            self.trash_page, "title", f"Корзина ({len(trash)})" if trash else "Корзина"
        )
        self.trash_hint.set_markup(
            f'<span size="small">Заметки хранятся в корзине {self.app.settings["trash_days"]} '
            "дн., потом удаляются навсегда.</span>"
        )
        self._update_buttons()

    @staticmethod
    def _dot(note):
        return f'<span foreground="{theme.bar_color(note.color)}" size="large">●</span>'

    @staticmethod
    def _selected(tree):
        """Идентификаторы выбранных строк, в порядке списка."""
        model, paths = tree.get_selection().get_selected_rows()
        return [model[path][COL_ID] for path in paths]

    def _selected_id(self):
        selected = self._selected(self.tree)
        return selected[0] if selected else None

    @staticmethod
    def _select(tree, note_ids):
        selection = tree.get_selection()
        wanted = set(note_ids)
        for row in tree.get_model():
            if row[COL_ID] in wanted:
                selection.select_iter(row.iter)

    def _on_tree_key(self, tree, event, _model):
        """Ctrl+A выбирает все заметки списка, Delete убирает выбранные."""
        if event.state & Gdk.ModifierType.CONTROL_MASK and is_key(event, Gdk.KEY_a):
            tree.get_selection().select_all()
            return True
        if event.keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            if tree is self.trash_tree:
                self._purge_selected()
            else:
                self._trash_selected()
            return True
        return False

    def _update_buttons(self):
        notes = [self.store.get(i) for i in self._selected(self.tree)]
        notes = [n for n in notes if n is not None]
        self.show_button.set_sensitive(bool(notes))
        self.hide_button.set_sensitive(any(not n.hidden for n in notes))
        self.trash_button.set_sensitive(bool(notes))
        group_chosen = self.current_group() is not None
        self.show_group_button.set_sensitive(group_chosen)
        self.hide_group_button.set_sensitive(group_chosen)
        in_trash = bool(self._selected(self.trash_tree))
        self.restore_button.set_sensitive(in_trash)
        self.purge_button.set_sensitive(in_trash)
        self.empty_button.set_sensitive(len(self.trash_model) > 0)

    # --- действия над заметками ---

    def _show_selected(self):
        for note_id in self._selected(self.tree):
            self.app.show_note(note_id, highlight=self.search.get_text())

    def _hide_selected(self):
        for note_id in self._selected(self.tree):
            self.app.hide_note(note_id)

    def _trash_selected(self):
        for note_id in self._selected(self.tree):
            self.app.delete_note(note_id)

    def _set_group_visible(self, visible):
        group = self.current_group()
        if group is not None:
            self.app.set_group_visible(group, visible)

    # --- действия над корзиной ---

    def _restore_selected(self):
        for note_id in self._selected(self.trash_tree):
            self.app.restore_note(note_id)

    def _confirm(self, title, text):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO, text=title, secondary_text=text,
        )
        answer = dialog.run()
        dialog.destroy()
        return answer == Gtk.ResponseType.YES

    def _purge_selected(self):
        ids = self._selected(self.trash_tree)
        if not ids:
            return
        what = "Удалить заметку навсегда?" if len(ids) == 1 else f"Удалить навсегда заметки ({len(ids)})?"
        if self._confirm(what, "Восстановить их будет нельзя."):
            for note_id in ids:
                self.app.purge_note(note_id)

    def _empty_trash(self):
        if self._confirm("Очистить корзину?", "Все заметки в ней будут удалены навсегда."):
            self.app.empty_trash()
