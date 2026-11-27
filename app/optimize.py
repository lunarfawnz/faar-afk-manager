import glob
import json
import os
import re
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


FPS_RE = re.compile(r'<int name="FramerateCap">\s*(-?\d+)\s*</int>')
FPS_LINE = re.compile(r'[ \t]*<int name="FramerateCap">\s*-?\d+\s*</int>[ \t]*\r?\n?')


def roblox_settings_file():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox")
    try:
        names = os.listdir(base)
    except OSError:
        return None
    found = []
    for name in names:
        m = re.fullmatch(r"GlobalBasicSettings_(\d+)\.xml", name)
        if m:
            found.append((int(m.group(1)), os.path.join(base, name)))
    return max(found)[1] if found else None


def read_fps_cap(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        m = FPS_RE.search(f.read())
    return int(m.group(1)) if m else None


def write_fps_cap(path, cap):
    if read_fps_cap(path) == cap:
        return False
    with open(path, "r", encoding="utf-8", newline="") as f:
        content = f.read()
    if cap is None:
        content = FPS_LINE.sub("", content, count=1)
    elif FPS_RE.search(content):
        content = FPS_RE.sub(f'<int name="FramerateCap">{int(cap)}</int>', content, count=1)
    else:
        if "<Properties>" not in content:
            raise ValueError("unexpected Roblox settings file")
        content = content.replace("<Properties>", f'<Properties>\n<int name="FramerateCap">{int(cap)}</int>', 1)
    tmp = path + ".faar.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    os.replace(tmp, path)
    return True


def apply_fps_cap(cap, store):
    path = roblox_settings_file()
    if path is None:
        return "Roblox's settings file wasn't found (start Roblox once first)."
    cap = int(cap or 0)
    if cap > 0:
        if "fps_restore" not in store:
            store["fps_restore"] = read_fps_cap(path)
        return f"FPS limit {cap} set in Roblox." if write_fps_cap(path, cap) else ""
    if "fps_restore" in store:
        old = store.pop("fps_restore")
        write_fps_cap(path, old)
        return "Roblox's own FPS setting was put back."
    return ""
