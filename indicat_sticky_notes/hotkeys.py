"""Глобальные горячие клавиши. Только X11: XGrabKey через ctypes, без доп. пакетов.

На Wayland приложение не может перехватывать клавиши вне своих окон, поэтому
supported() там возвращает False, и остальные функции приложения работают как обычно.
"""
import ctypes
import ctypes.util
import os
import queue
import select
import threading

SHIFT, LOCK, CONTROL, MOD1, MOD2, MOD4 = 1, 2, 4, 8, 16, 64
RELEVANT = SHIFT | CONTROL | MOD1 | MOD4  # NumLock и CapsLock не мешают срабатыванию
LOCK_VARIANTS = (0, LOCK, MOD2, LOCK | MOD2)
KEY_PRESS = 2
_STOP = object()


def to_x_modifiers(gdk_mods: int) -> int:
    """Маска модификаторов GDK -> маска X11."""
    result = 0
    if gdk_mods & 1:  # SHIFT_MASK
        result |= SHIFT
    if gdk_mods & 4:  # CONTROL_MASK
        result |= CONTROL
    if gdk_mods & 8:  # MOD1_MASK (Alt)
        result |= MOD1
    if gdk_mods & (64 | (1 << 26)):  # MOD4_MASK / SUPER_MASK
        result |= MOD4
    return result


class _XKeyEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong),
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint), ("keycode", ctypes.c_uint), ("same_screen", ctypes.c_int),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xkey", _XKeyEvent), ("pad", ctypes.c_long * 24)]


_ErrorHandler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_error_seen = []


def _on_x_error(_display, _event):
    _error_seen.append(True)
    return 0


_error_handler = _ErrorHandler(_on_x_error)  # держим ссылку, иначе соберёт сборщик мусора


def _load_x11():
    name = ctypes.util.find_library("X11")
    if not name:
        return None
    x11 = ctypes.CDLL(name)
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XConnectionNumber.argtypes = [ctypes.c_void_p]
    x11.XKeysymToKeycode.restype = ctypes.c_ubyte
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int]
    x11.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XPending.argtypes = [ctypes.c_void_p]
    x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    x11.XSetErrorHandler.restype = ctypes.c_void_p
    x11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x11


def supported() -> bool:
    if not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return False
    return _load_x11() is not None


class _Worker(threading.Thread):
    """Поток со своим соединением с X-сервером: ждёт нажатия и применяет привязки."""

    def __init__(self):
        super().__init__(daemon=True, name="global-hotkeys")
        self.requests = queue.Queue()
        self.wake_r, self.wake_w = os.pipe()
        self.ready = threading.Event()
        self.ok = False

    def post(self, request):
        self.requests.put(request)
        os.write(self.wake_w, b"x")

    def run(self):
        from gi.repository import GLib

        x11 = _load_x11()
        dpy = x11.XOpenDisplay(None) if x11 else None
        self.ok = bool(dpy)
        self.ready.set()
        if not dpy:
            return
        root = x11.XDefaultRootWindow(dpy)
        fd = x11.XConnectionNumber(dpy)
        grabs = {}  # (keycode, модификаторы) -> функция
        event = _XEvent()
        while True:
            readable, _, _ = select.select([fd, self.wake_r], [], [])
            if self.wake_r in readable:
                os.read(self.wake_r, 64)
                while not self.requests.empty():
                    request = self.requests.get()
                    if request is _STOP:
                        x11.XUngrabKey(dpy, 0, 1 << 15, root)
                        x11.XCloseDisplay(dpy)
                        return
                    grabs = self._apply(x11, dpy, root, *request)
            while x11.XPending(dpy):
                x11.XNextEvent(dpy, ctypes.byref(event))
                if event.type == KEY_PRESS:
                    callback = grabs.get((event.xkey.keycode, event.xkey.state & RELEVANT))
                    if callback:
                        GLib.idle_add(lambda cb=callback: (cb(), False)[1])

    @staticmethod
    def _apply(x11, dpy, root, wanted, results, done):
        """Заменить все привязки на wanted: {имя: (keysym, x-модификаторы, функция)}."""
        x11.XUngrabKey(dpy, 0, 1 << 15, root)  # AnyKey, AnyModifier
        grabs = {}
        for name, (keysym, mods, callback) in wanted.items():
            keycode = x11.XKeysymToKeycode(dpy, keysym)
            if keycode == 0 or mods == 0:
                results[name] = False
                continue
            _error_seen.clear()
            previous = x11.XSetErrorHandler(ctypes.cast(_error_handler, ctypes.c_void_p))
            for extra in LOCK_VARIANTS:
                x11.XGrabKey(dpy, keycode, mods | extra, root, 1, 1, 1)
            x11.XSync(dpy, 0)  # ошибки (клавиша уже занята) придут сюда
            x11.XSetErrorHandler(previous)
            if _error_seen:
                for extra in LOCK_VARIANTS:
                    x11.XUngrabKey(dpy, keycode, mods | extra, root)
                results[name] = False
            else:
                grabs[(keycode, mods)] = callback
                results[name] = True
        done.set()
        return grabs


class GlobalHotkeys:
    def __init__(self):
        self._worker = None

    def set(self, accels):
        """Задать все сочетания сразу: {имя: ("<Primary><Alt>n", функция)}.

        Возвращает {имя: удалось ли}. Сочетание без модификаторов не принимается.
        """
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        if not supported():
            return {name: False for name in accels}
        wanted, results = {}, {}
        for name, (accel, callback) in accels.items():
            keysym, mods = Gtk.accelerator_parse(accel) if accel else (0, 0)
            if not keysym:
                results[name] = False
            else:
                wanted[name] = (int(keysym), to_x_modifiers(int(mods)), callback)
        worker = self._ensure_worker()
        if worker is None:
            return {name: False for name in accels}
        done = threading.Event()
        worker.post((wanted, results, done))
        done.wait(3)
        return {name: results.get(name, False) for name in accels}

    def _ensure_worker(self):
        if self._worker is None:
            worker = _Worker()
            worker.start()
            worker.ready.wait(3)
            if not worker.ok:
                return None
            self._worker = worker
        return self._worker

    def stop(self):
        if self._worker is not None:
            self._worker.post(_STOP)
            self._worker.join(2)
            self._worker = None
