import ctypes
import time
from contextlib import contextmanager

_k32 = ctypes.WinDLL("kernel32")
_k32.CreateMutexW.restype = ctypes.c_void_p
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_k32.WaitForSingleObject.restype = ctypes.c_uint32
_k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
_handle = _k32.CreateMutexW(None, False, "FishRNG_InputLock")


@contextmanager
def my_turn(timeout_s=120):
    r = _k32.WaitForSingleObject(_handle, int(timeout_s * 1000))
    got = r in (0, 0x80)
    try:
        if got:
            time.sleep(0.15)
        yield got
    finally:
        if got:
            _k32.ReleaseMutex(_handle)
