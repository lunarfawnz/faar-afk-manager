import glob
import json
import os
import sys

from . import win

IS_WIN = sys.platform == "win32"

LOW_GFX_FLAGS = {
    "DFIntDebugFRMQualityLevelOverride": 1,
    "DFFlagTextureQualityOverrideEnabled": True,
    "DFIntTextureQualityOverride": 0,
    "FIntDebugForceMSAASamples": 0,
    "FIntFRMMaxGrassDistance": 0,
    "FIntFRMMinGrassDistance": 0,
}
MARK_FILE = "FishRNGManager_flags.json"


def version_dirs():
    dirs = set()
    local = os.environ.get("LOCALAPPDATA", "")
    for exe in glob.glob(os.path.join(local, "Roblox", "Versions", "*", "RobloxPlayerBeta.exe")):
        dirs.add(os.path.dirname(exe))
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info["name"] or "").lower() == "robloxplayerbeta.exe" and p.info["exe"]:
                dirs.add(os.path.dirname(p.info["exe"]))
    except Exception:
        pass
    return sorted(dirs)


def apply_graphics(low):
    changed = 0
    for d in version_dirs():
        path = os.path.join(d, "ClientSettings", "ClientAppSettings.json")
        mark = os.path.join(d, "ClientSettings", MARK_FILE)
        try:
            data = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            ours = []
            if os.path.exists(mark):
                with open(mark, "r", encoding="utf-8") as f:
                    ours = json.load(f) or []
            before = json.dumps(data, sort_keys=True)
            data.pop("_FishRNGManager", None)
            for k in ours:
                data.pop(k, None)
            added = []
            if low:
                for k, v in LOW_GFX_FLAGS.items():
                    if k not in data:
                        data[k] = v
                        added.append(k)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if added:
                with open(mark, "w", encoding="utf-8") as f:
                    json.dump(added, f)
            elif os.path.exists(mark):
                os.remove(mark)
            if json.dumps(data, sort_keys=True) == before:
                continue
            if data:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            elif os.path.exists(path):
                os.remove(path)
            changed += 1
        except Exception:
            continue
    return changed


if IS_WIN:
    import ctypes
    import ctypes.wintypes as wt
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _k32.OpenProcess.restype = wt.HANDLE
    _k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    _psapi.EmptyWorkingSet.argtypes = [wt.HANDLE]
    PROCESS_SET_QUOTA, PROCESS_QUERY_LIMITED_INFORMATION = 0x0100, 0x1000


def set_low_priority(pid, low=True):
    if not IS_WIN or not pid:
        return False
    try:
        import psutil
        p = psutil.Process(pid)
        want = psutil.BELOW_NORMAL_PRIORITY_CLASS if low else psutil.NORMAL_PRIORITY_CLASS
        if p.nice() != want:
            p.nice(want)
        return True
    except Exception:
        return False


def trim_memory(pid):
    if not IS_WIN or not pid:
        return False
    h = _k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        return bool(_psapi.EmptyWorkingSet(h))
    finally:
        _k32.CloseHandle(h)
