import base64
import ctypes
import json
import os
import sys
import threading
from dataclasses import dataclass, field, asdict

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD_DATA_DIR = os.path.join(ROOT, "data")


def _data_dir():
    base = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else None
    if not base:
        return OLD_DATA_DIR
    return os.path.join(base, "FAAR Manager")


DATA_DIR = _data_dir()
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
os.makedirs(DATA_DIR, exist_ok=True)


def _migrate_old_data():
    if DATA_DIR == OLD_DATA_DIR or not os.path.isdir(OLD_DATA_DIR):
        return
    if os.path.exists(ACCOUNTS_FILE) or os.path.exists(SETTINGS_FILE):
        return
    import shutil
    for name in os.listdir(OLD_DATA_DIR):
        src = os.path.join(OLD_DATA_DIR, name)
        if os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(DATA_DIR, name))
            except OSError:
                pass


_migrate_old_data()

_lock = threading.RLock()


if sys.platform == "win32":
    import ctypes.wintypes as wt

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32")
    _ENTROPY = b"FishRNGManager-v1"

    def _blob(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def protect(text):
        data_in, _b1 = _blob(text.encode("utf-8"))
        ent, _b2 = _blob(_ENTROPY)
        out = DATA_BLOB()
        if not _crypt32.CryptProtectData(ctypes.byref(data_in), "FishRNGManager", ctypes.byref(ent),
                                         None, None, 0, ctypes.byref(out)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode()
        finally:
            _kernel32.LocalFree(out.pbData)

    def unprotect(token):
        raw = base64.b64decode(token)
        data_in, _b1 = _blob(raw)
        ent, _b2 = _blob(_ENTROPY)
        out = DATA_BLOB()
        if not _crypt32.CryptUnprotectData(ctypes.byref(data_in), None, ctypes.byref(ent),
                                           None, None, 0, ctypes.byref(out)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
        finally:
            _kernel32.LocalFree(out.pbData)
else:
    def protect(text):
        return "dev:" + base64.b64encode(text.encode()).decode()

    def unprotect(token):
        return base64.b64decode(token[4:]).decode()


FEATURES = ("rebirth", "boost_shop", "selene", "hallows_eve", "anti_afk", "rejoin", "ability")


@dataclass
class Account:
    user_id: int
    username: str
    display_name: str = ""
    cookie_enc: str = ""
    features: dict = field(default_factory=lambda: {
        "rebirth": False, "boost_shop": True, "selene": True,
        "hallows_eve": False, "anti_afk": True, "rejoin": True, "tile": True,
        "ability": False})
    avatar_url: str = ""

    pid: int = 0
    hwnd: int = 0
    status: str = "Offline"

    @property
    def cookie(self):
        return unprotect(self.cookie_enc) if self.cookie_enc else ""

    def label(self):
        if self.display_name and self.display_name != self.username:
            return f"{self.display_name} (@{self.username})"
        return self.username

    def to_json(self):
        d = asdict(self)
        for k in ("pid", "hwnd", "status"):
            d.pop(k, None)
        return d


def load_accounts():
    with _lock:
        if not os.path.exists(ACCOUNTS_FILE):
            return []
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    out = []
    for d in raw:
        feats = Account(0, "").features
        feats.update(d.get("features") or {})
        out.append(Account(user_id=int(d["user_id"]), username=d["username"],
                           display_name=d.get("display_name", ""), cookie_enc=d.get("cookie_enc", ""),
                           features=feats, avatar_url=d.get("avatar_url", "")))
    return out


def save_accounts(accounts):
    with _lock:
        tmp = ACCOUNTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([a.to_json() for a in accounts], f, indent=2)
        os.replace(tmp, ACCOUNTS_FILE)


DEFAULT_SETTINGS = {
    "place_id": 0,
    "game_link": "https://www.roblox.com/games/9582986239",
    "window_w": 960, "window_h": 540,
    "auto_arrange": True,
    "maximize_untiled": True,
    "untiled_monitor": 0,
    "fit_to_screen": True,
    "monitor": 1,
    "wait_for_idle_s": 1.5,
    "launch_gap_s": 12,

    "rebirth_every_min": 10,
    "rebirth_popup_wait_s": 6,
    "boost_every_min": 5,
    "boost_align_clock": True,
    "boost_offset_s": 8,
    "selene_check_s": 4,
    "selene_cooldown_min": 10,
    "selene_turn_wait_s": 8,
    "focus_settle_s": 10,

    "event_check_s": 3,
    "first_slot": 2,
    "last_slot": 4,
    "mutation_cycle": True,
    "mutation_word": "dracula",

    "opt_low_graphics": True,
    "opt_low_priority": True,
    "opt_trim_min": 5,
    "rejoin_check_s": 20,
    "anti_afk_min": 14,
    "anti_afk_clicks": 10,
    "restore_user_focus": True,
    "check_updates": True,

    "ability_key": "v",
    "ability_every_s": 10,
    "ability_only_ready": True,
    "ability_pos": None,
}


from . import items as _items
DEFAULT_SETTINGS.update(_items.default_settings())


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    with _lock:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    s.update(json.load(f))
            except Exception:
                pass
    return s


def save_settings(s):
    with _lock:
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SETTINGS_FILE)
