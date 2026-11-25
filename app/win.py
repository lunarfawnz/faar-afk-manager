import ctypes
import sys
import time

import numpy as np

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes.wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    ULONG_PTR = ctypes.c_size_t
    LRESULT = ctypes.c_ssize_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.SetWindowTextW.argtypes = [wt.HWND, wt.LPCWSTR]
    user32.IsWindow.argtypes = [wt.HWND]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsZoomed.argtypes = [wt.HWND]
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    except OSError:
        dwmapi = None
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
    user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wt.LONG
    user32.AdjustWindowRectEx.argtypes = [ctypes.POINTER(wt.RECT), wt.DWORD, wt.BOOL, wt.DWORD]
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.GetForegroundWindow.restype = wt.HWND
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetDC.argtypes = [wt.HWND]
    user32.GetDC.restype = wt.HDC
    user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    gdi32.SelectObject.restype = wt.HGDIOBJ
    gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
    gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wt.UINT]
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wt.HDC]
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

    MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
    user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.c_void_p, MONITORENUMPROC, wt.LPARAM]
    user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    kernel32.GetTickCount.restype = wt.DWORD
    kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel32.WaitForSingleObject.restype = wt.DWORD
    kernel32.ReleaseMutex.argtypes = [wt.HANDLE]
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = wt.HANDLE
    kernel32.GetCurrentThreadId.restype = wt.DWORD

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, KEYEVENTF_EXTENDEDKEY = 0x0002, 0x0008, 0x0001
SW_MAXIMIZE = 3
SW_RESTORE = 9
WS_CAPTION = 0x00C00000
DWMWA_EXTENDED_FRAME_BOUNDS = 9
GWL_STYLE, GWL_EXSTYLE = -16, -20
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
PW_CLIENTONLY, PW_RENDERFULLCONTENT = 0x1, 0x2
SRCCOPY = 0x00CC0020
SPI_GETWORKAREA = 0x0030

SCANCODES = {
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14, "y": 0x15,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31, "m": 0x32,
    "space": 0x39, "enter": 0x1C, "escape": 0x01, "tab": 0x0F, "backspace": 0x0E,
    "f11": 0x57, "i": 0x17, "o": 0x18, "u": 0x16, "p": 0x19, "j": 0x24, "k": 0x25, "l": 0x26, "shift": 0x2A, "comma": 0x33, "period": 0x34,
}
EXTENDED_SCANCODES = {"left": 0x4B, "right": 0x4D, "up": 0x48, "down": 0x50}

VK_F8, VK_F9 = 0x77, 0x78
VK_MENU = 0x12


def slot_key(n):
    return str(int(n) % 10)


def _require():
    if not IS_WIN:
        raise RuntimeError("This feature only works on Windows.")


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_pid(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_window(hwnd):
    return bool(IS_WIN and hwnd and user32.IsWindow(hwnd))


def top_windows():
    if not IS_WIN:
        return []
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = window_title(hwnd)
            if title:
                out.append((hwnd, window_pid(hwnd), title))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def roblox_pids():
    import psutil
    pids = set()
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == "robloxplayerbeta.exe":
                pids.add(p.pid)
        except Exception:
            pass
    return pids


def roblox_windows():
    pids = roblox_pids()
    found = {}
    for hwnd, pid, title in top_windows():
        if pid in pids and title.lower().startswith("roblox"):
            found.setdefault(pid, hwnd)
    return found


def set_title(hwnd, text):
    if is_window(hwnd):
        user32.SetWindowTextW(hwnd, text)


def client_rect(hwnd):
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def monitors():
    if not IS_WIN:
        return [{"n": 1, "primary": True, "work": (0, 0, 1920, 1040), "size": (1920, 1080)}]
    found = []

    def cb(hmon, hdc, rect, _):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        m, w = mi.rcMonitor, mi.rcWork
        found.append({"primary": bool(mi.dwFlags & 1), "work": (w.left, w.top, w.right, w.bottom),
                      "size": (m.right - m.left, m.bottom - m.top), "left": m.left})
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    found.sort(key=lambda m: (not m["primary"], m["left"]))
    for i, m in enumerate(found):
        m["n"] = i + 1
    return found


def monitor_label(m):
    w, h = m["size"]
    return f"Monitor {m['n']}{' (main)' if m['primary'] else ''} - {w}x{h}"


def work_area(n=1):
    mons = monitors()
    m = next((m for m in mons if m["n"] == int(n)), mons[0])
    return m["work"]


def idle_seconds():
    if not IS_WIN:
        return 999.0
    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(LASTINPUTINFO)
    user32.GetLastInputInfo(ctypes.byref(li))
    return ((kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


class InputLock:
    NAME = "FishRNG_InputLock"

    def __init__(self):
        self.h = kernel32.CreateMutexW(None, False, self.NAME) if IS_WIN else None

    def acquire(self, timeout_s):
        if not self.h:
            return True
        r = kernel32.WaitForSingleObject(self.h, int(timeout_s * 1000))
        return r in (0, 0x80)

    def release(self):
        if self.h:
            kernel32.ReleaseMutex(self.h)


def window_rect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def visible_rect(hwnd):
    if dwmapi:
        r = wt.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r),
                                        ctypes.sizeof(r)) == 0:
            return r.left, r.top, r.right, r.bottom
    return window_rect(hwnd)


def has_title_bar(hwnd):
    return bool((user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF) & WS_CAPTION == WS_CAPTION)


def make_windowed(hwnd):
    _require()
    changed = False
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        changed = True
        time.sleep(0.3)
    if not has_title_bar(hwnd):
        prev = foreground()
        if focus(hwnd):
            time.sleep(0.2)
            press_key("f11")
            time.sleep(1.2)
            changed = True
        restore_focus(prev)
    return changed


def is_maximized(hwnd):
    return bool(user32.IsZoomed(hwnd)) and has_title_bar(hwnd)


def _on_monitor(hwnd, work):
    l, t, r, b = visible_rect(hwnd)
    cx, cy = (l + r) // 2, (t + b) // 2
    return work[0] <= cx < work[2] and work[1] <= cy < work[3]


def maximize(hwnd, monitor=0):
    _require()
    changed = False
    if not has_title_bar(hwnd):
        if focus(hwnd):
            time.sleep(0.2)
            press_key("f11")
            time.sleep(1.2)
            changed = True
    if monitor:
        work = work_area(monitor)
        if not _on_monitor(hwnd, work):
            if user32.IsZoomed(hwnd) or user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
                time.sleep(0.3)
            l, t, r, b = work
            user32.SetWindowPos(hwnd, None, l + 40, t + 40, max(400, (r - l) // 2), max(300, (b - t) // 2),
                                SWP_NOZORDER | SWP_NOACTIVATE)
            time.sleep(0.3)
            changed = True
    if not user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        changed = True
        time.sleep(0.3)
    return changed


def frame_extra(hwnd):
    vl, vt, vr, vb = visible_rect(hwnd)
    _, _, cw, ch = client_rect(hwnd)
    return (vr - vl) - cw, (vb - vt) - ch


def place_window(hwnd, x, y, client_w, client_h):
    _require()
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    style = user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    r = wt.RECT(0, 0, client_w, client_h)
    user32.AdjustWindowRectEx(ctypes.byref(r), style, False, exstyle)
    ow, oh = r.right - r.left, r.bottom - r.top
    flags = SWP_NOZORDER | SWP_NOACTIVATE
    ox, oy = x, y
    for _ in range(4):
        user32.SetWindowPos(hwnd, None, ox, oy, ow, oh, flags)
        time.sleep(0.05)
        _, _, cw, ch = client_rect(hwnd)
        wl, wtp, _, _ = window_rect(hwnd)
        vl, vt, _, _ = visible_rect(hwnd)
        if (cw, ch) == (client_w, client_h) and (vl, vt) == (x, y):
            return
        ow += client_w - cw
        oh += client_h - ch
        ox, oy = x - (vl - wl), y - (vt - wtp)


def best_grid(n, area_w, area_h, extra_w, extra_h, aspect=16 / 9, max_w=None):
    best = (1, 320, 180)
    for cols in range(1, n + 1):
        rows = -(-n // cols)
        cw = min(area_w // cols - extra_w, int((area_h // rows - extra_h) * aspect))
        if max_w:
            cw = min(cw, max_w)
        if cw > best[1]:
            best = (cols, cw, int(cw / aspect))
    return best


def foreground():
    return user32.GetForegroundWindow() if IS_WIN else None


def focus(hwnd, timeout=1.5):
    _require()
    if not is_window(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    end = time.time() + timeout
    while time.time() < end:
        if user32.GetForegroundWindow() == hwnd:
            return True
        fg = user32.GetForegroundWindow()
        me = kernel32.GetCurrentThreadId()
        other = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(other and other != me and user32.AttachThreadInput(me, other, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(me, other, False)
        if user32.GetForegroundWindow() == hwnd:
            return True
        _key_vk(VK_MENU, down=True)
        _key_vk(VK_MENU, down=False)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
    return user32.GetForegroundWindow() == hwnd


def restore_focus(hwnd):
    if hwnd and is_window(hwnd):
        try:
            focus(hwnd, timeout=0.6)
        except Exception:
            pass


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(dx, dy, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, 0)
    return i


def _key_vk(vk, down):
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(vk, 0, 0 if down else KEYEVENTF_KEYUP, 0, 0)
    _send(i)


def cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_to(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    _send(_mouse(MOUSEEVENTF_MOVE, 1, 0))
    time.sleep(0.02)
    _send(_mouse(MOUSEEVENTF_MOVE, -1, 0))
    time.sleep(0.03)


def click(x, y, hold=0.05):
    move_to(x, y)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN))
    time.sleep(hold)
    _send(_mouse(MOUSEEVENTF_LEFTUP))


def mouse_click(hold=0.05):
    _send(_mouse(MOUSEEVENTF_LEFTDOWN))
    time.sleep(hold)
    _send(_mouse(MOUSEEVENTF_LEFTUP))


def wheel_raw(units, chunk=100):
    sign = 1 if units > 0 else -1
    left = abs(int(units))
    while left > 0:
        n = min(chunk, left)
        _send(_mouse(MOUSEEVENTF_WHEEL, data=sign * n))
        left -= n
        time.sleep(0.03)


def wheel(notches):
    _send(_mouse(MOUSEEVENTF_WHEEL, data=int(120 * notches)))


def press_key(name, hold=0.06):
    name = name.lower()
    flags = KEYEVENTF_SCANCODE
    if name in EXTENDED_SCANCODES:
        sc = EXTENDED_SCANCODES[name]
        flags |= KEYEVENTF_EXTENDEDKEY
    elif name in SCANCODES:
        sc = SCANCODES[name]
    else:
        raise ValueError(f"Unknown key: {name}")
    down = INPUT(type=INPUT_KEYBOARD)
    down.u.ki = KEYBDINPUT(0, sc, flags, 0, 0)
    up = INPUT(type=INPUT_KEYBOARD)
    up.u.ki = KEYBDINPUT(0, sc, flags | KEYEVENTF_KEYUP, 0, 0)
    _send(down)
    time.sleep(hold)
    _send(up)


ROUTE_KEYS = {"w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44, "space": 0x20, "shift": 0xA0,
              "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
              "comma": 0xBC, "period": 0xBE, "i": 0x49, "o": 0x4F}
VK_F7 = 0x76


def key_event(name, down):
    name = name.lower()
    flags = KEYEVENTF_SCANCODE
    if name in EXTENDED_SCANCODES:
        sc = EXTENDED_SCANCODES[name]
        flags |= KEYEVENTF_EXTENDEDKEY
    else:
        sc = SCANCODES[name]
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(0, sc, flags | (0 if down else KEYEVENTF_KEYUP), 0, 0)
    _send(i)


def key_down_now(vk):
    return bool(IS_WIN and (user32.GetAsyncKeyState(vk) & 0x8000))


def _dib_to_array(hdc_mem, hbmp, w, h):
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = w, -h
    bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
    return arr[:, :, :3].copy()


def capture_window(hwnd):
    _require()
    _, _, w, h = client_rect(hwnd)
    if w <= 0 or h <= 0:
        return None
    img = None
    hdc_win = user32.GetDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        if user32.PrintWindow(hwnd, hdc_mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            img = _dib_to_array(hdc_mem, hbmp, w, h)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_win)
    if img is None or img.mean() < 2:
        img = capture_screen_rect(*client_rect(hwnd))
    return img


def capture_screen_rect(x, y, w, h):
    _require()
    hdc_scr = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_scr)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_scr, w, h)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_scr, x, y, SRCCOPY)
        return _dib_to_array(hdc_mem, hbmp, w, h)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_scr)


SINGLETON_NAMES = ("ROBLOX_singletonEvent", "ROBLOX_singletonMutex")
_mutex_handles = {}
ERROR_ALREADY_EXISTS, ERROR_INVALID_HANDLE = 183, 6


def multi_instance_status():
    if not IS_WIN:
        return "off"
    hold_multi_instance_lock()
    return "on" if "ROBLOX_singletonEvent" in _mutex_handles else "blocked"


def hold_multi_instance_lock():
    if not IS_WIN:
        return False
    for name in SINGLETON_NAMES:
        if name in _mutex_handles:
            continue
        ctypes.set_last_error(0)
        h = kernel32.CreateMutexW(None, True, name)
        if h:
            _mutex_handles[name] = h
    return "ROBLOX_singletonEvent" in _mutex_handles
    for name in ("ROBLOX_singletonMutex", "ROBLOX_singletonEvent"):
        h = kernel32.CreateMutexW(None, True, name)
        if h:
            _mutex_handles.append(h)
    return bool(_mutex_handles)
