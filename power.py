"""Win32 power/session notifications via a hidden top-level window (pythonw has no console to hook).

Message-only windows don't get broadcasts, so this is a real but never-shown window.
Callbacks run on the window thread and must finish quickly: Windows waits only a few seconds
on suspend/shutdown before carrying on.
"""
import ctypes
import threading
from ctypes import wintypes

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def watch(on_sleep, on_wake):
    """on_sleep: suspend, shutdown, logoff. on_wake: resume from suspend. Returns the daemon thread."""

    def wndproc(hwnd, msg, wparam, lparam):
        try:
            if msg == WM_POWERBROADCAST and wparam == PBT_APMSUSPEND:
                on_sleep("suspend")
            elif msg == WM_POWERBROADCAST and wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                on_wake("resume")
            elif msg == WM_QUERYENDSESSION:
                return 1
            elif msg == WM_ENDSESSION and wparam:
                on_sleep("endsession")
                return 0
        except Exception as e:  # never let a callback error kill the message loop
            print("power callback error:", e, flush=True)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def loop():
        proc = WNDPROC(wndproc)
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=proc, hInstance=hinst, lpszClassName="DitooUsagePower")
        user32.RegisterClassW(ctypes.byref(wc))
        user32.CreateWindowExW(0, wc.lpszClassName, "DitooUsagePower", 0, 0, 0, 0, 0, None, None, hinst, None)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    t = threading.Thread(target=loop, name="power", daemon=True)
    t.start()
    return t
