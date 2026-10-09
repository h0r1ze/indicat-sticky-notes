#!/usr/bin/env python3
"""Скриншоты для README: docs/images/*.png.

Запускается внутри виртуального X-сервера, см. tools/make_screenshots.sh. Режимы:
  scenes   — «рабочий стол» с заметками и палитра (настоящие виджеты приложения,
             нарисованные в буфере с прозрачностью, поэтому видны скругления и тени);
  windows  — менеджер, настройки и меню как настоящие окна (снимается корневое окно).
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from indicat_sticky_notes.app import StickyApp  # noqa: E402
from indicat_sticky_notes.palette import PalettePopup  # noqa: E402
from indicat_sticky_notes.settings import Settings  # noqa: E402
from indicat_sticky_notes.storage import NoteStore  # noqa: E402

OUT = ROOT / "docs" / "images"
SCALE = 2  # масштаб рисунка: чёткие картинки на экранах с высоким разрешением


def pump(seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.01)


def fmt(text, *marks):
    """[(подстрока, формат), ...] -> диапазоны [начало, конец, формат] по тексту."""
    result = []
    for needle, name in marks:
        start = text.index(needle)
        result.append([start, start + len(needle), name])
    return result


def make_app(notes):
    folder = Path(tempfile.mkdtemp())
    store = NoteStore(folder / "notes.json")
    for kwargs in notes:
        store.add(**kwargs)
    app = StickyApp(store, folder / "backups", settings=Settings(folder / "settings.json"),
                    use_hotkeys=False)
    return app


# --- сцены из виджетов ---------------------------------------------------------

class Canvas:
    """Фон-«рабочий стол» и заметки, нарисованные поверх него."""

    def __init__(self, width, height, colors=("#355c7d", "#6c5b7b", "#c06c84"), panel=True):
        self.width, self.height = width, height
        self.surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width * SCALE, height * SCALE)
        self.surface.set_device_scale(SCALE, SCALE)
        self.cr = cairo.Context(self.surface)
        gradient = cairo.LinearGradient(0, 0, width, height)
        for i, color in enumerate(colors):
            r, g, b = (int(color[k:k + 2], 16) / 255 for k in (1, 3, 5))
            gradient.add_color_stop_rgb(i / (len(colors) - 1), r, g, b)
        self.cr.set_source(gradient)
        self.cr.paint()
        if panel:
            self._panel()
        self.items = []  # (окно буфера, x, y): держим ссылки до сохранения

    def _panel(self):
        cr = self.cr
        cr.set_source_rgba(0.08, 0.09, 0.12, 0.72)
        cr.rectangle(0, 0, self.width, 26)
        cr.fill()
        icon = GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(ROOT / "data/icons/hicolor/scalable/apps/indicat-sticky-notes.svg"), 18 * SCALE, 18 * SCALE
        )
        cr.save()
        cr.scale(1 / SCALE, 1 / SCALE)  # значок рисуем в настоящих пикселях
        Gdk.cairo_set_source_pixbuf(cr, icon, (self.width - 150) * SCALE, 4 * SCALE)
        cr.paint()
        cr.restore()
        cr.set_source_rgb(0.93, 0.94, 0.96)
        cr.select_font_face("Noto Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(12)
        cr.move_to(self.width - 120, 17)
        cr.show_text("Сб 10 окт  14:32")

    def place(self, widget, x, y, width, height=1):
        off = Gtk.OffscreenWindow()
        screen = Gdk.Screen.get_default()
        off.set_visual(screen.get_rgba_visual())
        off.set_app_paintable(True)
        off.add(widget)
        off.set_default_size(width, height)
        off.show_all()
        self.items.append((off, x, y))

    def save(self, name):
        pump(0.5)
        for off, x, y in self.items:
            self.cr.set_source_surface(off.get_surface(), x, y)
            self.cr.paint()
        OUT.mkdir(parents=True, exist_ok=True)
        self.surface.write_to_png(str(OUT / name))
        print("saved", name)


def note_card(window, collapsed=False):
    """Вынуть «карточку» заметки из её окна, чтобы нарисовать в буфере."""
    card = window.card
    window.remove(card)
    if collapsed:
        window._update_collapsed_class()
        for part in (window.body, window.grip):
            part.set_no_show_all(True)
            part.hide()
    return card


def scenes():
    Gdk.Screen.is_composited = lambda self: True  # скругление и тень, как с композитором
    text_a = "☑ хлеб\n☑ сыр\n☐ молоко\n☐ яйца\nНе забыть сумку и скидочную карту"
    text_b = "Идеи на неделю\n— тёмная тема\n— синхронизация\n— экспорт в Markdown"
    text_c = "☑ закончить отчёт\n☐ созвон с командой\n☐ купить билеты"
    text_f = "Жирный, курсив, подчёркнутый и зачёркнутый текст — всё как в редакторе"
    notes = [
        dict(title="Покупки", text=text_a, color="yellow", group="Дом", pinned=True, hidden=True,
             formats=fmt(text_a, ("сумку", "bold"), ("скидочную карту", "italic"))),
        dict(title="Проект", text=text_b, color="blue", group="Работа", hidden=True, font_size=14,
             formats=fmt(text_b, ("Идеи на неделю", "bold"))),
        dict(title="Пятница", text=text_c, color="graphite", group="Работа", hidden=True),
        dict(title="Рецепт блинов", text="молоко, яйца, мука", color="green", group="Дом",
             hidden=True, collapsed=True),
        dict(text="Позвонить маме\nв воскресенье", color="pink", hidden=True, font_size=17),
        dict(title="Форматирование", text=text_f, color="#c9f0e1", hidden=True,
             formats=fmt(text_f, ("Жирный", "bold"), ("курсив", "italic"),
                         ("подчёркнутый", "underline"), ("зачёркнутый", "strike"))),
    ]
    app = make_app(notes)
    app.setup()
    pump(0.3)
    windows = list(app.windows.values())

    canvas = Canvas(1000, 620)
    layout = [(30, 52, 330, 270), (385, 40, 310, 240), (720, 60, 270, 200),
              (700, 270, 300, 1), (40, 340, 320, 210), (385, 300, 310, 240)]
    for window, (x, y, w, h) in zip(windows, layout):
        collapsed = window.note.collapsed
        canvas.place(note_card(window, collapsed), x, y, w, h)
    canvas.save("hero.png")

    # палитра рядом с заметкой
    app2 = make_app([dict(title="Покупки", text=text_a, color="yellow", pinned=True, hidden=True,
                          formats=fmt(text_a, ("сумку", "bold"), ("скидочную карту", "italic")))])
    app2.setup()
    pump(0.2)
    window = list(app2.windows.values())[0]
    popup = PalettePopup(window, lambda _c: None, lambda: None)
    popup.show_all()
    card = popup.get_child()
    popup.remove(card)
    canvas = Canvas(640, 400, colors=("#2c5364", "#203a43", "#0f2027"), panel=False)
    canvas.place(note_card(window), 20, 24, 320, 270)
    canvas.place(card, 250, 70, 320, 1)
    canvas.save("palette.png")


# --- настоящие окна ------------------------------------------------------------

def grab(name):
    """Снять корневое окно, сделать прозрачным внешний чёрный фон и добавить мягкую тень."""
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / f"_{name}.png"
    subprocess.run(["import", "-window", "root", str(raw)], check=True)
    width, height = map(int, subprocess.run(
        ["identify", "-format", "%w %h", str(raw)], check=True, capture_output=True, text=True
    ).stdout.split())
    out = OUT / name
    # Заливка от углов убирает только внешний фон, а чёрные пиксели внутри окон не трогает.
    fill = ["-alpha", "set", "-fill", "none", "-fuzz", "0%"]
    for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        fill += ["-draw", f"color {x},{y} floodfill"]
    subprocess.run(
        ["convert", str(raw), *fill, "-trim", "+repage", "-bordercolor", "none", "-border", "2",
         "(", "+clone", "-background", "black", "-shadow", "35x10+0+6", ")", "+swap",
         "-background", "none", "-layers", "merge", "+repage", str(out)],
        check=True,
    )
    raw.unlink()
    print("saved", name)


def popup_at(menu, x, y):
    """Открыть меню в точке экрана (у настоящего клика есть «триггер», у скрипта его нет)."""
    menu.popup(None, None, lambda *_a: (x, y, True), None, 0, Gtk.get_current_event_time())


def windows():
    texts = [
        ("Покупки", "☑ хлеб\n☐ молоко\n☐ яйца", "yellow", "Дом", False),
        ("Проект", "Идеи на неделю: тёмная тема, синхронизация", "blue", "Работа", False),
        ("Пятница", "☑ отчёт\n☐ созвон", "graphite", "Работа", False),
        ("Рецепт блинов", "молоко, яйца, мука", "green", "Дом", True),
        ("", "Позвонить маме в воскресенье", "pink", "", True),
        ("План отпуска", "Билеты, отель, маршрут", "orange", "Дом", False),
    ]
    notes = [dict(title=t, text=x, color=c, group=g, hidden=h) for t, x, c, g, h in texts]
    old = dict(title="Старый черновик", text="не пригодился", group="Работа")
    app = make_app(notes + [old])
    app.setup()
    store = app.store
    app.delete_note(store.notes[-1].id)  # одна заметка в корзине
    pump(0.3)

    which = sys.argv[2]
    if which == "manager":
        app.open_manager()
        app.manager.move(0, 0)
        app.manager.resize(640, 470)
        pump(0.8)
        grab("manager.png")
    elif which == "settings":
        app.open_settings()
        app.settings_window.move(0, 0)
        pump(0.8)
        grab("settings.png")
    elif which == "tray":
        app.hide_all()  # на снимке только меню
        pump(0.3)
        menu = app.build_tray_menu()
        popup_at(menu, 8, 8)
        pump(0.6)
        grab("tray-menu.png")
    elif which == "help":
        app.hide_all()
        app.open_help()
        app.help_window.move(0, 0)
        app.help_window.resize(600, 520)
        pump(0.8)
        grab("help.png")
    elif which == "font-menu":
        window = list(app.windows.values())[0]
        menu = window.build_menu()
        app.hide_all()
        pump(0.3)
        popup_at(menu, 8, 8)
        pump(0.6)
        head = next(i for i in menu.get_children()
                    if isinstance(i, Gtk.MenuItem) and i.get_label() == "Размер шрифта")
        menu.select_item(head)  # как при наведении: раскрывается подменю с ползунком
        pump(1.0)
        grab("font-slider-menu.png")
    elif which == "note-menu":
        window = list(app.windows.values())[0]
        menu = window.build_menu()
        app.hide_all()
        pump(0.3)
        popup_at(menu, 8, 8)
        pump(0.6)
        grab("note-menu.png")


if __name__ == "__main__":
    {"scenes": scenes, "windows": windows}[sys.argv[1]]()
