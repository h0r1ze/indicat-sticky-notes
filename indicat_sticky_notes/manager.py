"""Менеджер заметок: список всех заметок с поиском."""
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import theme  # noqa: E402

COL_ID, COL_DOT, COL_TITLE, COL_STATE, COL_UPDATED, COL_SORT = range(6)


def format_time(stamp: float, now: float = None) -> str:
    now = now or time.time()
    local, today = time.localtime(stamp), time.localtime(now)
    if local[:3] == today[:3]:
        return time.strftime("%H:%M", local)
    return time.strftime("%d.%m.%Y", local)


class ManagerWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title="Заметки")
        self.app = app
        self.store = app.store
        self._refresh_source = None

        self.set_default_size(560, 460)
        self.set_border_width(10)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(root)

        self.search = Gtk.SearchEntry(placeholder_text="Поиск по тексту заметок")
        self.search.connect("search-changed", lambda _e: self.refresh())
        root.pack_start(self.search, False, False, 0)

        self.model = Gtk.ListStore(str, str, str, str, str, float)
        self.model.set_sort_column_id(COL_SORT, Gtk.SortType.DESCENDING)
        self.tree = Gtk.TreeView(model=self.model)
        self.tree.set_headers_visible(False)
        dot = Gtk.CellRendererText()
        self.tree.append_column(Gtk.TreeViewColumn("", dot, markup=COL_DOT))
        title = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        title_col = Gtk.TreeViewColumn("Заметка", title, text=COL_TITLE)
        title_col.set_expand(True)
        self.tree.append_column(title_col)
        state = Gtk.CellRendererText(foreground="#888888")
        self.tree.append_column(Gtk.TreeViewColumn("", state, text=COL_STATE))
        updated = Gtk.CellRendererText(foreground="#888888")
        self.tree.append_column(Gtk.TreeViewColumn("", updated, text=COL_UPDATED))
        self.tree.connect("row-activated", lambda *_a: self._show_selected())
        self.tree.get_selection().connect("changed", lambda _s: self._update_buttons())

        scroll = Gtk.ScrolledWindow()
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self.tree)
        root.pack_start(scroll, True, True, 0)

        self.status = Gtk.Label(halign=Gtk.Align.START)
        root.pack_start(self.status, False, False, 0)

        buttons = Gtk.Box(spacing=6)
        self.new_button = Gtk.Button(label="Новая")
        self.new_button.connect("clicked", lambda _b: self.app.new_note())
        self.show_button = Gtk.Button(label="Показать")
        self.show_button.connect("clicked", lambda _b: self._show_selected())
        self.hide_button = Gtk.Button(label="Скрыть")
        self.hide_button.connect("clicked", lambda _b: self._hide_selected())
        self.delete_button = Gtk.Button(label="Удалить")
        self.delete_button.connect("clicked", lambda _b: self._delete_selected())
        for button in (self.new_button, self.show_button, self.hide_button):
            buttons.pack_start(button, False, False, 0)
        buttons.pack_end(self.delete_button, False, False, 0)
        root.pack_start(buttons, False, False, 0)

        self.store.listeners.append(self._schedule_refresh)
        self.connect("destroy", lambda _w: self.store.listeners.remove(self._schedule_refresh))
        self.connect("delete-event", lambda w, _e: w.hide() or True)
        self.refresh()
        root.show_all()

    # --- данные ---

    def present_with_search(self, focus_search=False):
        self.refresh()
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

    def refresh(self):
        selected = self._selected_id()
        notes = self.store.search(self.search.get_text())
        self.model.clear()
        for note in notes:
            self.model.append([
                note.id,
                f'<span foreground="{theme.bar_color(note.color)}" size="large">●</span>',
                note.preview() or "(пустая заметка)",
                "скрыта" if note.hidden else "",
                format_time(note.updated),
                note.updated,
            ])
        total = len(self.store.notes)
        shown = len(notes)
        self.status.set_text(
            f"Заметок: {total}" if shown == total else f"Найдено {shown} из {total}"
        )
        if selected:
            self._select(selected)
        self._update_buttons()

    def _selected_id(self):
        model, it = self.tree.get_selection().get_selected()
        return model[it][COL_ID] if it else None

    def _select(self, note_id):
        for row in self.model:
            if row[COL_ID] == note_id:
                self.tree.get_selection().select_iter(row.iter)
                return

    def _update_buttons(self):
        note = self.store.get(self._selected_id()) if self._selected_id() else None
        self.show_button.set_sensitive(note is not None)
        self.hide_button.set_sensitive(note is not None and not note.hidden)
        self.delete_button.set_sensitive(note is not None)

    # --- действия ---

    def _show_selected(self):
        note_id = self._selected_id()
        if note_id:
            self.app.show_note(note_id)

    def _hide_selected(self):
        note_id = self._selected_id()
        if note_id:
            self.app.hide_note(note_id)

    def _delete_selected(self):
        note_id = self._selected_id()
        note = self.store.get(note_id) if note_id else None
        if note is None:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Удалить заметку?",
            secondary_text=note.preview() or "Пустая заметка",
        )
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.YES:
            self.app.delete_note(note_id)
