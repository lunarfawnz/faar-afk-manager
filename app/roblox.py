import os
import random
import re
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


def launch_uri(ticket, place_id, link_code=None):
    tracker = str(random.randint(100_000_000_000, 999_999_999_999))
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


def _wait_new_window(account, before, wait_s, status):
    end = time.time() + wait_s
    while time.time() < end:
        time.sleep(1)
        wins = win.roblox_windows()
        new = [pid for pid in wins if pid not in before]
        if new:
            pid = new[0]
            hwnd = wins[pid]
            win.set_title(hwnd, f"Roblox - {account.username}")
            return pid, hwnd
        status(f"Waiting for window... {int(end - time.time())}s")
    return None


def launch(account, place_id, status=lambda s: None, wait_s=100, link_code=None, tries=2):
    if not win.hold_multi_instance_lock() and win.roblox_pids():
        raise RobloxError("Multi-instance is off because a Roblox window was opened before it could be "
                          "turned on. Close every Roblox window, wait a few seconds, then launch again.")
    before = win.roblox_pids()
    for attempt in range(1, tries + 1):
        status("Getting login ticket...")
        ticket = auth_ticket(account.cookie)
        status("Starting Roblox..." if attempt == 1 else "Starting Roblox again...")
        os.startfile(launch_uri(ticket, place_id, link_code))
        got = _wait_new_window(account, before, wait_s, status)
        if got:
            return got
        time.sleep(3)
        wins = win.roblox_windows()
        late = [pid for pid in wins if pid not in before]
        if late:
            win.set_title(wins[late[0]], f"Roblox - {account.username}")
            return late[0], wins[late[0]]
    raise RobloxError("Roblox didn't open a window in time (tried twice).")


def close(account, wait_s=10):
    import time
    import psutil
    pids = {account.pid} if account.pid else set()
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
