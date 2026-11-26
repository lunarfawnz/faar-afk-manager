import os
import random
import re
import threading
import time
import urllib.parse
import uuid

import requests

from . import win

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
TIMEOUT = 15


class RobloxError(Exception):
    pass


def clean_cookie(raw):
    c = raw.strip().strip('"').strip("'")
    if c.lower().startswith(".roblosecurity="):
        c = c.split("=", 1)[1]
    c = c.split(";")[0].strip()
    if "_|WARNING:-DO-NOT-SHARE-THIS" not in c or len(c) < 100:
        raise RobloxError("That doesn't look like a .ROBLOSECURITY cookie.")
    return c


def _session(cookie):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    s.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
    return s


def whoami(cookie):
    r = _session(cookie).get("https://users.roblox.com/v1/users/authenticated", timeout=TIMEOUT)
    if r.status_code == 401:
        raise RobloxError("Roblox rejected this cookie (expired or logged out).")
    r.raise_for_status()
    return r.json()


def headshot_url(user_id):
    try:
        r = requests.get("https://thumbnails.roblox.com/v1/users/avatar-headshot",
                         params={"userIds": user_id, "size": "150x150", "format": "Png",
                                 "isCircular": "true"},
                         headers={"User-Agent": UA}, timeout=TIMEOUT)
        return r.json()["data"][0]["imageUrl"] or ""
    except Exception:
        return ""


def auth_ticket(cookie):
    s = _session(cookie)
    s.headers.update({"Referer": "https://www.roblox.com/", "Origin": "https://www.roblox.com",
                      "RBXAuthenticationNegotiation": "1", "Content-Type": "application/json"})
    url = "https://auth.roblox.com/v1/authentication-ticket"
    r = s.post(url, data="{}", timeout=TIMEOUT)
    token = r.headers.get("x-csrf-token")
    if token:
        s.headers["X-CSRF-TOKEN"] = token
        r = s.post(url, data="{}", timeout=TIMEOUT)
    ticket = r.headers.get("rbx-authentication-ticket")
    if r.status_code == 401:
        raise RobloxError("Cookie expired. Remove the account and add it again with a fresh cookie.")
    if not ticket:
        raise RobloxError(f"Couldn't get a login ticket (HTTP {r.status_code}).")
    return ticket


def _universe_name(universe_id):
    r = requests.get("https://games.roblox.com/v1/games", params={"universeIds": universe_id},
                     headers={"User-Agent": UA}, timeout=TIMEOUT)
    data = r.json().get("data") or []
    return (data[0]["name"], data[0]["rootPlaceId"]) if data else (None, None)


def resolve_place(link_or_id):
    m = re.search(r"(\d{5,})", str(link_or_id))
    if not m:
        raise RobloxError("Paste the game's roblox.com link or its ID.")
    num = int(m.group(1))
    try:
        r = requests.get(f"https://apis.roblox.com/universes/v1/places/{num}/universe",
                         headers={"User-Agent": UA}, timeout=TIMEOUT)
        uni = r.json().get("universeId") if r.ok else None
        if uni:
            name, root = _universe_name(uni)
            if name:
                return num, name
    except Exception:
        pass
    name, root = _universe_name(num)
    if root:
        return int(root), name
    raise RobloxError(f"No Roblox game found for {num}.")


def _resolve_share_link(code, cookie):
    s = _session(cookie)
    s.headers.update({"Content-Type": "application/json", "Origin": "https://www.roblox.com",
                      "Referer": "https://www.roblox.com/"})
    url = "https://apis.roblox.com/sharelinks/v1/resolve-link"
    body = {"linkId": code, "linkType": "Server"}
    r = s.post(url, json=body, timeout=TIMEOUT)
    token = r.headers.get("x-csrf-token")
    if r.status_code == 403 and token:
        s.headers["X-CSRF-TOKEN"] = token
        r = s.post(url, json=body, timeout=TIMEOUT)
    if not r.ok:
        raise RobloxError(f"Couldn't open that private server link (HTTP {r.status_code}).")
    data = r.json().get("privateServerInviteData") or {}
    if data.get("status") not in (None, "Valid") or not data.get("linkCode"):
        raise RobloxError("That private server link is expired or invalid. Copy a fresh one.")
    return int(data["placeId"]), data["linkCode"]


def resolve_link(link, cookie=None):
    link = str(link).strip()
    share = re.search(r"/share\?.*?code=([A-Za-z0-9]+)", link)
    if share and "type=server" in link.lower():
        if not cookie:
            raise RobloxError("Add an account first: private server share links need one to open.")
        place_id, code = _resolve_share_link(share.group(1), cookie)
        try:
            _, name = resolve_place(place_id)
        except Exception:
            name = "private server"
        return place_id, code, name
    code = re.search(r"privateServerLinkCode=([A-Za-z0-9_-]+)", link)
    games = re.search(r"/games/(\d+)", link)
    place_id, name = resolve_place(games.group(1) if games else link)
    return place_id, (code.group(1) if code else None), name


def launch_uri(ticket, place_id, link_code=None, tracker=None):
    tracker = tracker or str(random.randint(100_000_000_000, 999_999_999_999))
    if link_code:
        place_url = ("https://www.roblox.com/Game/PlaceLauncher.ashx?request=RequestPrivateGame"
                     f"&browserTrackerId={tracker}&placeId={place_id}&accessCode=&linkCode={link_code}"
                     f"&joinAttemptId={uuid.uuid4()}&joinAttemptOrigin=PlayButton")
    else:
        place_url = ("https://www.roblox.com/Game/PlaceLauncher.ashx?request=RequestGame"
                     f"&browserTrackerId={tracker}&placeId={place_id}&isPlayTogetherGame=false"
                     f"&joinAttemptId={uuid.uuid4()}&joinAttemptOrigin=PlayButton")
    parts = [
        "roblox-player:1",
        "launchmode:play",
        f"gameinfo:{ticket}",
        f"launchtime:{int(time.time() * 1000)}",
        f"placelauncherurl:{urllib.parse.quote(place_url, safe='')}",
        f"browsertrackerid:{tracker}",
        "robloxLocale:en_us",
        "gameLocale:en_us",
        "channel:",
    ]
    return "+".join(parts)


class Pending:
    def __init__(self, account, tracker, before):
        self.account = account
        self.tracker = tracker
        self.before = before
        self.t = time.time()
        self.got = None
        self.pid = None
        self.adopted = False
        self.done = False


_pending = []
_trackers = set()
_plock = threading.Lock()
_claimed = set()
_cmd_cache = {}


def _cmdline(pid):
    if pid in _cmd_cache:
        return _cmd_cache[pid]
    import psutil
    try:
        cmd = " ".join(psutil.Process(pid).cmdline())
    except Exception:
        cmd = None
    if cmd is not None:
        _cmd_cache[pid] = cmd
    return cmd


def _pids_with_tracker(tracker):
    out = []
    for pid in win.roblox_pids():
        cmd = _cmdline(pid)
        if cmd and tracker in cmd:
            out.append(pid)
    return out


def start(account, place_id, link_code=None):
    if not win.hold_multi_instance_lock() and win.roblox_pids():
        raise RobloxError("Multi-instance is off because a Roblox window was opened before it could be "
                          "turned on. Close every Roblox window, wait a few seconds, then launch again.")
    ticket = auth_ticket(account.cookie)
    tracker = str(random.randint(100_000_000_000, 999_999_999_999))
    p = Pending(account, tracker, win.roblox_pids())
    with _plock:
        _pending.append(p)
        _trackers.add(tracker)
    os.startfile(launch_uri(ticket, place_id, link_code, tracker))
    return p


_ctime = {}
ORPHAN_AFTER = 15


def _created(pid):
    if pid not in _ctime:
        import psutil
        try:
            _ctime[pid] = psutil.Process(pid).create_time()
        except Exception:
            return time.time()
    return _ctime[pid]


def _poll(known_pids=()):
    with _plock:
        live = [p for p in _pending if not p.done and p.got is None]
        if not live:
            return
        pids = win.roblox_pids()
        cmds = {pid: _cmdline(pid) for pid in pids}
        for p in live:
            if p.pid is not None and p.pid not in pids:
                p.pid = None
        taken = set(_claimed) | set(known_pids) | {p.pid for p in _pending if p.pid}
        for p in live:
            if p.pid is None:
                own = [pid for pid, c in cmds.items() if c and p.tracker in c and pid not in taken]
                if own:
                    p.pid = min(own, key=_created)
                    taken.add(p.pid)
        spare = sorted((pid for pid in pids if pid not in taken
                        and not (cmds.get(pid) and any(tr in cmds[pid] for tr in _trackers))), key=_created)
        for pid in spare:
            fits = [p for p in live if p.pid is None and pid not in p.before and _created(pid) >= p.t - 2]
            if fits:
                p = min(fits, key=lambda x: x.t)
                p.pid = pid
                taken.add(pid)
        wins = win.roblox_windows(any_title=True)
        for p in live:
            if p.pid is not None and p.pid in wins:
                p.got = (p.pid, wins[p.pid])
                _claimed.add(p.pid)
        now = time.time()
        for p in sorted(live, key=lambda x: x.t):
            if p.got or p.pid is not None or now - p.t < ORPHAN_AFTER:
                continue
            busy = set(_claimed) | set(known_pids) | {o.pid for o in _pending if o is not p and o.pid}
            plain = [pid for pid in wins if pid not in busy
                     and not (cmds.get(pid) and any(tr in cmds[pid] for tr in _trackers if tr != p.tracker))
                     and win.window_title(wins[pid]).strip().lower() == "roblox"]
            if not plain:
                continue
            fresh = [pid for pid in plain if pid not in p.before]
            pid = min(fresh or plain, key=_created)
            p.pid, p.got = pid, (pid, wins[pid])
            p.adopted = pid in p.before
            _claimed.add(pid)


def wait_window(p, wait_s=100, status=lambda s: None, cancelled=lambda: False, known_pids=lambda: ()):
    end = time.time() + wait_s
    extended = False
    try:
        while True:
            if cancelled():
                for pid in _pids_with_tracker(p.tracker):
                    _kill(pid)
                return None
            _poll(known_pids())
            if p.got:
                pid, hwnd = p.got
                win.set_title(hwnd, f"Roblox - {p.account.username}")
                return pid, hwnd
            left = int(end - time.time())
            if left <= 0:
                if not extended and _pids_with_tracker(p.tracker):
                    extended = True
                    end = time.time() + 90
                    continue
                return None
            status(f"Waiting for window... {left}s" + (" (Roblox is still starting)" if extended else ""))
            time.sleep(0.5)
    finally:
        with _plock:
            p.done = True
            if p in _pending:
                _pending.remove(p)


def forget(pid):
    with _plock:
        _claimed.discard(pid)
        _cmd_cache.pop(pid, None)
        _ctime.pop(pid, None)


def launch(account, place_id, status=lambda s: None, wait_s=100, link_code=None, tries=2,
           cancelled=lambda: False, known_pids=lambda: ()):
    for attempt in range(1, tries + 1):
        status("Getting login ticket..." if attempt == 1 else "Starting Roblox again...")
        p = start(account, place_id, link_code)
        got = wait_window(p, wait_s, status, cancelled, known_pids)
        if got:
            return got
        if cancelled():
            raise RobloxError("Cancelled.")
    raise RobloxError(f"Roblox didn't open a window in time (tried {tries} times).")


def _kill(pid):
    import psutil
    try:
        pr = psutil.Process(pid)
        if (pr.name() or "").lower().startswith("roblox"):
            pr.kill()
    except Exception:
        pass


def close(account, wait_s=10):
    import time
    import psutil
    pids = {account.pid} if account.pid else set()
    try:
        for pid, hwnd in win.roblox_windows().items():
            if win.window_title(hwnd) == f"Roblox - {account.username}":
                pids.add(pid)
    except Exception:
        pass
    if account.hwnd and win.is_window(account.hwnd):
        try:
            p = win.window_pid(account.hwnd)
            if p:
                pids.add(p)
        except Exception:
            pass
    procs = []
    for pid in pids:
        try:
            pr = psutil.Process(pid)
            if (pr.name() or "").lower().startswith("roblox"):
                pr.terminate()
                procs.append(pr)
        except Exception:
            pass
    for pid in pids:
        forget(pid)
    if not procs:
        return
    _, alive = psutil.wait_procs(procs, timeout=wait_s)
    for pr in alive:
        try:
            pr.kill()
        except Exception:
            pass
    psutil.wait_procs(alive, timeout=5)


def reattach(accounts):
    if not win.IS_WIN:
        return
    wins = win.roblox_windows()
    for pid, hwnd in wins.items():
        title = win.window_title(hwnd)
        for a in accounts:
            if title == f"Roblox - {a.username}" and not a.hwnd:
                a.pid, a.hwnd, a.status = pid, hwnd, "In game"
