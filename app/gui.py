import io
import os
import sys
import queue
import threading
import time
import collections
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import cv2
import requests
from PIL import Image, ImageTk

from . import win, roblox
from .engine import Engine
from .storage import (load_accounts, save_accounts, load_settings, save_settings, Account,
                      DATA_DIR, protect)
from . import builtin, hallows, optimize, update, ability, items, engine, remote
from .version import __version__

BG = "#0e1016"
PANEL = "#151823"
CARD = "#1c2030"
CARD_HI = "#232840"
BORDER = "#2a3048"
ACCENT = "#7c5cff"
ACCENT_HI = "#9479ff"
PINK = "#ff5c9a"
TEXT = "#e8eaf2"
MUTED = "#8a90a6"
GOOD = "#3ddc97"
WARN = "#ffb84d"
BAD = "#ff5c6c"

ctk.set_appearance_mode("dark")

FEATURE_LABELS = [
    ("boost_shop", "Boost shop"),
    ("selene", "Selene"),
    ("rebirth", "Auto rebirth"),
    ("hallows_eve", "Hallow's Eve"),
    ("anti_afk", "Anti-AFK"),
    ("ability", "Auto ability"),
    ("rejoin", "Rejoin"),
    ("tile", "Tile"),
]


def F(size=13, weight="normal"):
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def bgr_to_pil(img):
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def status_color(status):
    s = status.lower()
    if s.startswith("in game") or s.startswith("running"):
        return GOOD
    if s.startswith("failed") or "error" in s:
        return BAD
    if s.startswith("offline"):
        return MUTED
    return WARN


def pill_button(master, text, cmd, color=ACCENT, hover=ACCENT_HI, width=110, **kw):
    return ctk.CTkButton(master, text=text, command=cmd, fg_color=color, hover_color=hover,
                         corner_radius=10, height=34, width=width, font=F(13, "bold"), **kw)


def ghost_button(master, text, cmd, width=90, **kw):
    return ctk.CTkButton(master, text=text, command=cmd, fg_color="transparent", border_width=1,
                         border_color=BORDER, hover_color=CARD_HI, text_color=TEXT,
                         corner_radius=10, height=32, width=width, font=F(12), **kw)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Fish an Anime RNG Multi Account Manager")
        self._set_icon()
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(fg_color=BG)

        self.settings = load_settings()
        self.accounts = load_accounts()
        self._ui_q = queue.Queue()
        self._launch_lock = threading.Lock()
        self.launching = {}
        self._arrange_guard = threading.Lock()
        self._arrange_due = 0.0
        self._arrange_waiting = False
        self.log_lines = queue.Queue()
        self.log_ring = collections.deque(maxlen=400)
        self.log_seq = 0
        self._log_guard = threading.Lock()
        self._log_file = open(os.path.join(DATA_DIR, "log.txt"), "a", encoding="utf-8")

        self.engine = Engine(lambda: self.accounts, lambda: self.settings, self.log)
        self.engine.on_status = lambda st: self.ui(lambda: self._set_engine_status(st))
        self.engine.relaunch = self.relaunch_blocking
        self.remote = remote.Remote(self)
        self.engine.notify = self.remote.notify
        roblox.IDENTIFY = self.engine.logwatch.user_for_pid
        threading.Thread(target=self._linker, daemon=True).start()
        self._lowered, self._prio_warned, self._next_trim = set(), set(), time.time() + 120
        self._past_taskbar_warned = {}
        self._maxed, self._seen, self._maxing = set(), {}, False

        self._multi = "off"
        if win.IS_WIN:
            self._multi = win.multi_instance_status()
            roblox.reattach(self.accounts)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._page_makers = {"accounts": AccountsPage, "automation": AutomationPage, "log": LogPage,
                             "remote": RemotePage}
        self.pages = {}
        self._current = None
        self.show("accounts")
        self._set_engine_status("Stopped")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._pump)
        self.after(1000, self._tick)
        self.after(120, self._prebuild_pages)
        if self.settings.get("remote_enabled") and self.remote.has_pin():
            self.after(800, self.remote.start)
        if self.settings.get("check_updates", True):
            self.after(1500, lambda: threading.Thread(target=self._check_updates, daemon=True).start())
        if win.IS_WIN:
            threading.Thread(target=self.apply_graphics, kwargs={"quiet": True}, daemon=True).start()
        if not win.IS_WIN:
            self.log("Not running on Windows: launching and automation are disabled.", level="warn")
        elif self._multi == "on":
            self.log("Multi-instance is on: you can open as many Roblox clients as you like "
                     "(no other multi-instance tool needed).")
        else:
            self.log("Multi-instance is OFF because a Roblox window was already open when this app started. "
                     "Close every Roblox window (including your main); it turns on by itself within a few "
                     "seconds. Then open your clients again.", level="warn")

    def ui(self, fn):
        self._ui_q.put(fn)

    def _pump(self):
        try:
            while True:
                self._ui_q.get_nowait()()
        except queue.Empty:
            pass
        if "log" in self.pages:
            self.pages["log"].drain()
        self.after(100, self._pump)

    def _check_updates(self):
        info = update.check()
        if info and info.get("newer"):
            self._update_info = info
            self.ui(lambda: self._show_update_button(info["version"]))

    def _show_update_button(self, version):
        self.update_btn.configure(text=f"\u2b06  Update to v{version}")
        self.update_btn.grid()

    def _do_update(self):
        info = self._update_info
        if not info:
            return
        notes = (info.get("notes") or "").strip()
        if len(notes) > 500:
            notes = notes[:500] + "\u2026"
        msg = f"Update to v{info['version']}?\n\n{notes}" if notes else f"Update to v{info['version']}?"
        if update.is_frozen():
            msg += "\n\nThe app will close, swap in the new version, and reopen."
        else:
            msg += "\n\nThe app's files will be updated; restart to apply."
        if not messagebox.askyesno("Update available", msg):
            return
        self.update_btn.configure(text="Updating\u2026", state="disabled")
        threading.Thread(target=self._run_update, args=(info,), daemon=True).start()

    def _run_update(self, info):
        try:
            if update.is_frozen():
                update.update_exe(info)
                self.ui(lambda: self._update_done_exe())
            else:
                result = update.update_source()
                self.ui(lambda: self._update_done_source(result))
        except Exception as e:
            self.log(f"Update failed: {e}", level="error")
            self.ui(lambda: (messagebox.showerror("Update failed", str(e)),
                             self.update_btn.configure(text="\u2b06  Try update again", state="normal")))

    def _update_done_exe(self):
        messagebox.showinfo("Updating", "Downloaded. The app will now close and reopen on the new version.")
        self._on_close()
        os._exit(0)

    def _update_done_source(self, result):
        if messagebox.askyesno("Update ready", result + "\n\nRestart now?"):
            self._on_close()
            update.restart()
        else:
            self.update_btn.grid_remove()

    def apply_graphics(self, quiet=False):
        if not win.IS_WIN:
            return
        low = bool(self.settings.get("opt_low_graphics"))
        try:
            n = optimize.apply_graphics(low)
        except Exception as e:
            self.log(f"Couldn't change the Roblox graphics settings: {e}", level="warn")
            return
        if n and not quiet:
            self.log("Low graphics " + ("turned on" if low else "turned off") +
                     ". Restart the Roblox clients for it to take effect.")

    def _optimize_tick(self):
        if not win.IS_WIN:
            return
        s = self.settings
        now = time.time()
        trim_every = float(s.get("opt_trim_min", 0) or 0) * 60
        do_trim = trim_every > 0 and now >= self._next_trim
        if do_trim:
            self._next_trim = now + trim_every
        accs = [a for a in self.accounts if a.pid and a.hwnd]

        def work():
            for a in accs:
                tiled = a.features.get("tile", True)
                if s.get("opt_low_priority") and tiled:
                    if optimize.set_low_priority(a.pid, True):
                        self._lowered.add(a.pid)
                    elif a.user_id not in self._prio_warned:
                        self._prio_warned.add(a.user_id)
                        self.log("Couldn't lower this client's priority (Windows refused). Harmless: it only "
                                 "means this window keeps normal CPU priority.", a, "warn")
                elif a.pid in self._lowered:
                    optimize.set_low_priority(a.pid, False)
                    self._lowered.discard(a.pid)
                if do_trim and tiled:
                    optimize.trim_memory(a.pid)
        threading.Thread(target=work, daemon=True).start()

    def _maximize_tick(self):
        if not win.IS_WIN:
            return
        now = time.time()
        live = set()
        for a in self.accounts:
            if not (a.hwnd and win.is_window(a.hwnd)):
                continue
            live.add(a.hwnd)
            if a.features.get("tile", True):
                self._maxed.discard(a.hwnd)
                self._seen.pop(a.hwnd, None)
                continue
            if not self.settings.get("maximize_untiled", True) or a.hwnd in self._maxed:
                continue
            first = self._seen.setdefault(a.hwnd, now)
            if now - first < 4 or self._maxing:
                continue
            self._maxed.add(a.hwnd)
            self._maxing = True
            threading.Thread(target=self._maximize_one, args=(a,), daemon=True).start()
        self._maxed &= live
        for h in list(self._seen):
            if h not in live:
                self._seen.pop(h, None)

    def _maximize_one(self, acc):
        lock = self.engine.input_lock
        got = lock.acquire(timeout_s=60)
        try:
            if win.is_maximized(acc.hwnd):
                return
            prev = win.foreground()
            if win.maximize(acc.hwnd, int(self.settings.get("untiled_monitor", 0) or 0)):
                self.log("Maximized the window (Tile is off).", acc)
            if prev and prev != acc.hwnd:
                win.restore_focus(prev)
        except Exception as e:
            self.log(f"Couldn't maximize the window: {e}", acc, "warn")
        finally:
            if got:
                lock.release()
            self._maxing = False

    def _linker(self):
        while True:
            time.sleep(5)
            if not win.IS_WIN:
                continue
            try:
                for a in roblox.link_unclaimed(self.accounts, set(self.launching)):
                    self.log("Found this account's Roblox window and linked it.", a)
                    self._arrange_soon()
            except Exception:
                pass

    def _tick(self):
        if "accounts" in self.pages:
            self.pages["accounts"].refresh_status()
        self._maximize_tick()
        self._opt_count = getattr(self, "_opt_count", 0) + 1
        if self._opt_count % 30 == 1:
            self._optimize_tick()
        if win.IS_WIN and self._multi != "on":
            self._multi = win.multi_instance_status()
            if self._multi == "on":
                self.log("Multi-instance is now on. You can open your Roblox clients.")
        self._show_multi()
        self.after(1000, self._tick)

    def _show_multi(self):
        if self._multi == "on":
            self.multi_lbl.configure(text="● Multi-instance on", text_color=GOOD)
        elif self._multi == "blocked":
            self.multi_lbl.configure(text="● Multi-instance off:\nclose all Roblox windows", text_color=BAD)
        else:
            self.multi_lbl.configure(text="", text_color=MUTED)

    def log(self, msg, acc=None, level="info"):
        who = f"[{acc.username}] " if acc else ""
        line = f"{time.strftime('%H:%M:%S')}  {who}{msg}"
        self.log_lines.put((line, level))
        with self._log_guard:
            self.log_seq += 1
            self.log_ring.append((self.log_seq, line, level))
        try:
            self._log_file.write(line + "\n")
            self._log_file.flush()
        except Exception:
            pass

    def log_since(self, since):
        with self._log_guard:
            rows = [r for r in self.log_ring if r[0] > since]
        return [{"id": i, "text": line, "level": lvl} for i, line, lvl in rows[-200:]]

    def find_account(self, uid):
        return next((a for a in self.accounts if a.user_id == uid), None)

    def save_settings_now(self):
        save_settings(self.settings)

    def screenshot_jpeg(self, acc):
        if not (acc.hwnd and win.is_window(acc.hwnd)):
            return None
        img = win.capture_window(acc.hwnd)
        if img is None:
            return None
        h, w = img.shape[:2]
        if w > 960:
            img = cv2.resize(img, (960, int(h * 960 / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
        return buf.tobytes() if ok else None

    def remote_engine(self, action):
        if action == "start":
            if not any(a.hwnd for a in self.accounts):
                return "Launch at least one account first."
            self.engine.start()
            return "Automation started."
        if action == "pause":
            self.engine.pause()
            return f"Automation {self.engine.status.lower()}."
        if action == "stop":
            self.engine.remote_stop = True
            threading.Thread(target=self.engine.stop, daemon=True).start()
            return "Stopping automation."
        return "Unknown action."

    def remote_account(self, acc, action):
        alive = bool(acc.hwnd) and win.is_window(acc.hwnd)
        if action == "launch":
            if alive:
                return "It's already open."
            self.log("Phone remote: launching.", acc)
            self.ui(lambda: self.launch([acc]))
            return "Launching."
        if action == "cancel":
            self.cancel_launch(acc)
            return "Cancelling."
        if action == "close":
            if not alive:
                return "It's not open."
            threading.Thread(target=roblox.close, args=(acc,), daemon=True).start()
            acc.hwnd, acc.pid, acc.status = 0, 0, "Offline"
            self.log("Phone remote: closed Roblox.", acc)
            return "Closed."
        if action == "rejoin":
            self.log("Phone remote: rejoining.", acc)

            def go():
                roblox.close(acc)
                acc.hwnd, acc.pid, acc.status = 0, 0, "Offline"
                time.sleep(3)
                self.ui(lambda: self.launch([acc]))
            threading.Thread(target=go, daemon=True).start()
            return "Rejoining."
        return "Unknown action."

    def remote_feature(self, acc, key, on):
        acc.features[key] = on
        self.save()
        self.log(f"Phone remote: {dict(remote.FEATURES).get(key, key)} turned {'on' if on else 'off'}.", acc)
        page = self.pages.get("accounts")
        if page is not None:
            self.ui(page.rebuild)

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, width=230)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=16, pady=(24, 4))
        ctk.CTkLabel(brand, text="🎣", font=F(30)).pack(side="left")
        box = ctk.CTkFrame(brand, fg_color="transparent")
        box.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(box, text="FAAR", font=F(22, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(box, text="Multi Account Manager", font=F(11), text_color=MUTED,
                     wraplength=140, justify="left").pack(anchor="w")

        self.nav = {}
        items = [("accounts", "👥   Accounts"), ("automation", "⚙️   Settings"),
                 ("log", "📜   Activity log"), ("remote", "📱   Phone remote")]
        for i, (key, label) in enumerate(items):
            b = ctk.CTkButton(sb, text=label, anchor="w", font=F(14), height=42, corner_radius=10,
                              fg_color="transparent", hover_color=CARD, text_color=TEXT,
                              command=lambda k=key: self.show(k))
            b.grid(row=i + 1, column=0, sticky="ew", padx=14, pady=3)
            self.nav[key] = b
        sb.grid_rowconfigure(10, weight=1)

        ctrl = ctk.CTkFrame(sb, fg_color=CARD, corner_radius=14)
        ctrl.grid(row=11, column=0, sticky="ew", padx=14, pady=16)
        ctrl.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(ctrl, text="AUTOMATION", font=F(11, "bold"), text_color=MUTED).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 0))
        self.status_lbl = ctk.CTkLabel(ctrl, text="● Stopped", font=F(16, "bold"), text_color=MUTED)
        self.status_lbl.grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 10))
        self.start_btn = pill_button(ctrl, "▶  Start", self._start, color=GOOD, hover="#2fc283",
                                     text_color="#0b1a12")
        self.start_btn.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
        self.pause_btn = ghost_button(ctrl, "Pause", lambda: self.engine.pause())
        self.pause_btn.grid(row=3, column=0, sticky="ew", padx=(12, 4), pady=(0, 12))
        self.stop_btn = ghost_button(ctrl, "Stop", lambda: threading.Thread(
            target=self.engine.stop, daemon=True).start())
        self.stop_btn.grid(row=3, column=1, sticky="ew", padx=(4, 12), pady=(0, 12))
        self.multi_lbl = ctk.CTkLabel(sb, text="", font=F(12, "bold"), text_color=MUTED, justify="center")
        self.multi_lbl.grid(row=12, column=0, pady=(0, 6))
        ctk.CTkLabel(sb, text="F8 pause / resume   ·   F9 stop", font=F(11), text_color=MUTED).grid(
            row=13, column=0, pady=(0, 2))
        self.update_btn = pill_button(sb, "", self._do_update, color=GOOD, hover="#2fc283",
                                      text_color="#0b1a12", width=180)
        self.update_btn.grid(row=14, column=0, pady=(0, 4))
        self.update_btn.grid_remove()
        self._update_info = None
        ctk.CTkLabel(sb, text=f"v{__version__}", font=F(11), text_color=MUTED).grid(
            row=15, column=0, pady=(0, 14))

    def _start(self):
        if not win.IS_WIN:
            messagebox.showerror("Windows only", "Automation only works on Windows.")
            return
        if not any(a.hwnd for a in self.accounts):
            messagebox.showinfo("Nothing running", "Launch at least one account first.")
            return
        self.engine.start()

    def _set_engine_status(self, st):
        color = {"Running": GOOD, "Paused": WARN}.get(st, MUTED)
        self.status_lbl.configure(text=f"● {st}", text_color=color)
        self.pause_btn.configure(text="Resume" if st == "Paused" else "Pause")

    def _ensure_page(self, key):
        if key not in self.pages:
            page = self._page_makers[key](self.content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
            if self._current and self._current != key and self._current in self.pages:
                self.pages[self._current].tkraise()
        return self.pages[key]

    def _prebuild_pages(self):
        for key in self._page_makers:
            if key not in self.pages:
                self._ensure_page(key)
        if self._current:
            self.pages[self._current].tkraise()

    def show(self, key):
        page = self._ensure_page(key)
        self._current = key
        for k in self._page_makers:
            self.nav[k].configure(fg_color=CARD_HI if k == key else "transparent")
        page.tkraise()
        if hasattr(page, "on_show"):
            page.on_show()

    def save(self):
        save_accounts(self.accounts)

    def ensure_place(self):
        s = self.settings
        if s.get("place_id") and s.get("place_link_resolved") == s["game_link"]:
            return int(s["place_id"]), s.get("link_code") or None
        cookie = self.accounts[0].cookie if self.accounts else None
        pid, code, name = roblox.resolve_link(s["game_link"], cookie)
        s.update(place_id=pid, link_code=code or "", place_link_resolved=s["game_link"], game_name=name)
        save_settings(s)
        self.log(f"Game: {name} (place {pid}){'  ·  private server' if code else ''}")
        return pid, code

    def _known_pids(self):
        return {a.pid for a in self.accounts if a.pid and a.hwnd}

    def is_launching(self, acc):
        return acc.user_id in self.launching

    def cancel_launch(self, acc):
        job = self.launching.get(acc.user_id)
        if job is not None:
            job["cancel"] = True
            acc.status = "Cancelling..."

    def _arrange_soon(self):
        if not self.settings.get("auto_arrange"):
            return
        with self._arrange_guard:
            self._arrange_due = time.time() + 2.5
            if self._arrange_waiting:
                return
            self._arrange_waiting = True

        def go():
            while True:
                with self._arrange_guard:
                    left = self._arrange_due - time.time()
                    if left <= 0:
                        self._arrange_waiting = False
                        break
                time.sleep(min(left, 0.5))
            self.arrange()

        threading.Thread(target=go, daemon=True).start()

    def launch(self, accs):
        if not win.IS_WIN:
            messagebox.showerror("Windows only", "Launching Roblox only works on Windows.")
            return
        todo = [a for a in accs if not (a.hwnd and win.is_window(a.hwnd)) and a.user_id not in self.launching]
        if not todo:
            return
        for a in todo:
            self.launching[a.user_id] = {"cancel": False}
            a.status = "Queued..."

        def wait_for(a, job, p):
            try:
                got = roblox.wait_window(p, 300, status=lambda t: setattr(a, "status", t),
                                         cancelled=lambda: job["cancel"], known_pids=self._known_pids)
                if job["cancel"] == "linked":
                    return
                if got:
                    a.pid, a.hwnd = got
                    a.status = "In game"
                    if getattr(p, "adopted", False):
                        self.log("Took over a Roblox window that wasn't linked to any account. If it's the "
                                 "wrong account, close it with Close and launch again.", a, "warn")
                    else:
                        self.log("Roblox window opened.", a)
                    self._arrange_soon()
                elif job["cancel"]:
                    a.status = "Offline"
                    self.log("Launch cancelled.", a)
                else:
                    a.status = "Failed"
                    seen = roblox.describe_windows({x.pid: x.username for x in self.accounts if x.pid and x.hwnd})
                    self.log("No Roblox window could be matched to this account in 5 minutes. If its window is "
                             "open, use ⋯ → Link an open Roblox window. Roblox windows FAAR can see: " + seen,
                             a, "error")
            finally:
                self.launching.pop(a.user_id, None)

        def run():
            with self._launch_lock:
                try:
                    place, link_code = self.ensure_place()
                except Exception as e:
                    self.log(f"Couldn't look up the game: {e}", level="error")
                    for a in todo:
                        a.status = "Failed"
                        self.launching.pop(a.user_id, None)
                    return
                self.apply_graphics(quiet=True)
                gap = max(0.0, float(self.settings["launch_gap_s"]))
                for i, a in enumerate(todo):
                    job = self.launching.get(a.user_id)
                    if job is None or job["cancel"]:
                        a.status = "Offline"
                        self.launching.pop(a.user_id, None)
                        continue
                    a.status = "Starting Roblox..."
                    try:
                        p = roblox.start(a, place, link_code)
                    except Exception as e:
                        a.status = "Failed"
                        self.launching.pop(a.user_id, None)
                        self.log(f"Launch failed: {e}", a, "error")
                        continue
                    threading.Thread(target=wait_for, args=(a, job, p), daemon=True).start()
                    rest = [b for b in todo[i + 1:] if not self.launching.get(b.user_id, {"cancel": True})["cancel"]]
                    if rest:
                        end = time.time() + gap
                        while time.time() < end and rest and not all(
                                self.launching.get(b.user_id, {"cancel": True})["cancel"] for b in rest):
                            time.sleep(0.2)

        threading.Thread(target=run, daemon=True).start()

    def _set_icon(self):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ico = os.path.join(base, "assets", "icon.ico")
        if not os.path.exists(ico):
            return
        try:
            if win.IS_WIN:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FAAR.Manager")
                self.iconbitmap(ico)
                self.after(250, lambda: self.iconbitmap(ico))
        except Exception:
            pass

    def relaunch_blocking(self, acc):
        with self._launch_lock:
            try:
                place, link_code = self.ensure_place()
                self.apply_graphics(quiet=True)
                acc.status = "Rejoining..."
                acc.pid, acc.hwnd = roblox.launch(acc, place, status=lambda t: setattr(acc, "status", t),
                                                  link_code=link_code, known_pids=self._known_pids)
                self.log("Rejoined: Roblox window opened.", acc)
                self._arrange_soon()
                time.sleep(max(0.0, float(self.settings.get("launch_gap_s", 0))))
                return True
            except Exception as e:
                acc.status = "Rejoin failed"
                self.log(f"Rejoin launch failed: {e}", acc, "error")
                return False

    def arrange(self):
        if not win.IS_WIN:
            return
        lock = self.engine.input_lock
        got = lock.acquire(timeout_s=45)
        try:
            self._arrange_now()
        finally:
            if got:
                lock.release()

    def _arrange_now(self):
        running = [a for a in self.accounts if a.hwnd and win.is_window(a.hwnd)
                   and a.features.get("tile", True)]
        hwnds = [a.hwnd for a in running]
        if not hwnds:
            return
        names = {a.hwnd: a.username for a in running}
        for h in hwnds:
            if win.make_windowed(h):
                self.log(f"Took {names.get(h, 'a Roblox window')} out of fullscreen so it can be resized.")
        left, top, right, bottom = win.work_area(self.settings.get("monitor", 1))
        ew, eh = win.frame_extra(hwnds[0])
        if eh <= 0:
            ew, eh = 2, 32
        if self.settings.get("fit_to_screen", True):
            cols, cw, ch = win.best_grid(len(hwnds), right - left, bottom - top, ew, eh)
        else:
            cw, ch = int(self.settings["window_w"]), int(self.settings["window_h"])
            cols = max(1, (right - left) // (cw + ew))
        for i, h in enumerate(hwnds):
            x = left + (i % cols) * (cw + ew)
            y = top + (i // cols) * (ch + eh)
            try:
                win.place_window(h, x, y, cw, ch)
            except Exception as e:
                self.log(f"Couldn't move {names.get(h, 'a window')}: {e}", level="warn")
        time.sleep(1.0)
        for i, h in enumerate(hwnds):
            vl, vt, vr, vb = win.visible_rect(h)
            if vb > bottom + 2 or vr > right + 2 or not win.has_title_bar(h):
                x = left + (i % cols) * (cw + ew)
                y = top + (i // cols) * (ch + eh)
                win.make_windowed(h)
                win.place_window(h, x, y, cw, ch)
                vl, vt, vr, vb = win.visible_rect(h)
                if vb > bottom + 2:
                    last = self._past_taskbar_warned.get(h, 0.0)
                    if time.time() - last > 900:
                        self._past_taskbar_warned[h] = time.time()
                        self.log(f"{names.get(h, 'A Roblox window')} still runs past the taskbar. Press F11 in it "
                                 "and click Arrange windows again.", level="warn")
        if self.settings.get("window_w") != cw:
            self.settings["window_w"], self.settings["window_h"] = cw, ch
            save_settings(self.settings)
            self.log(f"Windows arranged at {cw}x{ch} on monitor {self.settings.get('monitor', 1)}.")

    def _on_close(self):
        try:
            self.remote.notify("stopped", "FAAR Manager closed", "The app was closed on the PC.")
            if self.engine.status != "Stopped":
                self.engine.user_closing = True
                self.engine.stop()
        finally:
            save_settings(self.settings)
            self.save()
            self.destroy()


class AccountsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 10))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Accounts", font=F(26, "bold"), text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.sub = ctk.CTkLabel(head, text="", font=F(12), text_color=MUTED)
        self.sub.grid(row=1, column=0, sticky="w")
        btns = ctk.CTkFrame(head, fg_color="transparent")
        btns.grid(row=0, column=1, rowspan=2, sticky="e")
        ghost_button(btns, "Arrange windows", lambda: threading.Thread(
            target=app.arrange, daemon=True).start(), width=140).pack(side="left", padx=4)
        ghost_button(btns, "Launch all", lambda: app.launch(app.accounts), width=110).pack(side="left", padx=4)
        pill_button(btns, "+  Add account", self._add, width=140).pack(side="left", padx=4)

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.list.grid_columnconfigure(0, weight=1)
        self.cards = {}
        self.rebuild()

    def rebuild(self):
        for c in self.list.winfo_children():
            c.destroy()
        self.cards = {}
        if not self.app.accounts:
            empty = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=16)
            empty.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
            ctk.CTkLabel(empty, text="No accounts yet", font=F(18, "bold"), text_color=TEXT).pack(pady=(30, 4))
            ctk.CTkLabel(empty, text="Click “+ Add account” and paste an account's .ROBLOSECURITY cookie.",
                         font=F(13), text_color=MUTED).pack(pady=(0, 30))
        for i, a in enumerate(self.app.accounts):
            card = AccountCard(self.list, self.app, a, self)
            card.grid(row=i, column=0, sticky="ew", padx=10, pady=7)
            self.cards[a.user_id] = card
        n = len(self.app.accounts)
        self.sub.configure(text=f"{n} account{'s' if n != 1 else ''}  ·  "
                                f"{self.app.settings.get('game_name') or 'Fish an Anime RNG'}")

    def refresh_status(self):
        for c in self.cards.values():
            c.refresh()

    def _add(self):
        AddAccountDialog(self.app, self)


class AccountCard(ctk.CTkFrame):
    def __init__(self, master, app, acc, page):
        super().__init__(master, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        self.app, self.acc, self.page = app, acc, page
        self.grid_columnconfigure(1, weight=1)

        self.avatar = ctk.CTkLabel(self, text="🙂", font=F(26), width=56, height=56,
                                   fg_color=CARD_HI, corner_radius=28)
        self.avatar.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=16)
        threading.Thread(target=self._load_avatar, daemon=True).start()

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=1, sticky="ew", pady=(14, 0))
        name = acc.display_name or acc.username
        ctk.CTkLabel(top, text=name, font=F(17, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(top, text=f"  @{acc.username}", font=F(12), text_color=MUTED).pack(side="left")
        self.status = ctk.CTkLabel(top, text="", font=F(12, "bold"))
        self.status.pack(side="left", padx=14)

        feats = ctk.CTkFrame(self, fg_color="transparent")
        feats.grid(row=1, column=1, sticky="w", pady=(4, 14))
        self.switches = {}
        for key, label in FEATURE_LABELS:
            v = tk.BooleanVar(value=bool(acc.features.get(key)))
            sw = ctk.CTkSwitch(feats, text=label, variable=v, font=F(12), text_color=TEXT,
                               progress_color=ACCENT, button_color="#ffffff", width=40,
                               command=lambda k=key, v=v: self._toggle(k, v))
            sw.pack(side="left", padx=(0, 12))
            self.switches[key] = v

        act = ctk.CTkFrame(self, fg_color="transparent")
        act.grid(row=0, column=2, rowspan=2, padx=16)
        self.launch_btn = pill_button(act, "Launch", self._launch, width=96)
        self.launch_btn.pack(side="left", padx=3)
        ghost_button(act, "Show", self._show, width=64).pack(side="left", padx=3)
        ctk.CTkButton(act, text="⋯", width=36, height=32, corner_radius=10, fg_color="transparent",
                      hover_color=CARD_HI, text_color=MUTED, font=F(16),
                      command=self._menu).pack(side="left", padx=3)
        self.refresh()

    def _load_avatar(self):
        try:
            url = self.acc.avatar_url or roblox.headshot_url(self.acc.user_id)
            if not url:
                return
            raw = requests.get(url, timeout=10).content
            img = Image.open(io.BytesIO(raw)).convert("RGBA")
            self.app.ui(lambda: self.avatar.configure(
                image=ctk.CTkImage(img, size=(52, 52)), text="", fg_color="transparent"))
        except Exception:
            pass

    def refresh(self):
        alive = bool(self.acc.hwnd) and win.is_window(self.acc.hwnd)
        busy = not alive and self.app.is_launching(self.acc)
        st = self.acc.status if (alive or self.acc.status != "In game") else "Offline"
        state = (st, alive, busy)
        if state == getattr(self, "_last_state", None):
            return
        self._last_state = state
        self.status.configure(text=f"● {st}", text_color=status_color(st))
        if busy:
            self.launch_btn.configure(text="Cancel", fg_color=CARD_HI, hover_color=BAD)
        else:
            self.launch_btn.configure(text="Close" if alive else "Launch",
                                      fg_color=BAD if alive else ACCENT,
                                      hover_color="#e04a59" if alive else ACCENT_HI)

    def _toggle(self, key, var):
        self.acc.features[key] = bool(var.get())
        self.app.save()

    def _launch(self):
        if not (self.acc.hwnd and win.is_window(self.acc.hwnd)) and self.app.is_launching(self.acc):
            self.app.cancel_launch(self.acc)
            return
        if self.acc.hwnd and win.is_window(self.acc.hwnd):
            acc = self.acc
            threading.Thread(target=roblox.close, args=(acc,), daemon=True).start()
            self.acc.hwnd, self.acc.pid, self.acc.status = 0, 0, "Offline"
            self.app.log("Closed Roblox.", self.acc)
        else:
            self.app.launch([self.acc])

    def _show(self):
        if self.acc.hwnd and win.is_window(self.acc.hwnd):
            threading.Thread(target=win.focus, args=(self.acc.hwnd,), daemon=True).start()

    def _menu(self):
        m = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT, bd=0)
        m.add_command(label="Test detection (what the app sees)", command=lambda: test_detection(self.app, self.acc))
        m.add_command(label="Link an open Roblox window", command=lambda: LinkWindowDialog(self.app, self.acc))
        m.add_command(label="Update cookie", command=lambda: AddAccountDialog(self.app, self.page))
        m.add_separator()
        m.add_command(label="Remove account", command=self._remove)
        m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def _remove(self):
        if messagebox.askyesno("Remove account", f"Remove {self.acc.username}? Its saved cookie is deleted."):
            self.app.accounts.remove(self.acc)
            self.app.save()
            self.page.rebuild()


class LinkWindowDialog(ctk.CTkToplevel):
    def __init__(self, app, acc):
        super().__init__(app)
        self.app, self.acc = app, acc
        self.title(f"Link a window to {acc.username}")
        self.geometry("560x420")
        self.configure(fg_color=BG)
        self.transient(app)
        ctk.CTkLabel(self, text=f"Which Roblox window is {acc.username}?", font=F(17, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(self, text="Click Show to bring a window to the front and check it's the right account, "
                     "then Link.", font=F(12), text_color=MUTED, wraplength=520, justify="left").pack(
            anchor="w", padx=20, pady=(0, 10))
        self.box = ctk.CTkScrollableFrame(self, fg_color=PANEL, corner_radius=12)
        self.box.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(0, 16))
        ghost_button(bar, "Refresh", self._fill, width=90).pack(side="left")
        ghost_button(bar, "Close", self.destroy, width=90).pack(side="right")
        self._fill()
        self.after(150, self.lift)

    def _fill(self):
        for w in self.box.winfo_children():
            w.destroy()
        known = {a.pid: a.username for a in self.app.accounts if a.pid and a.hwnd and win.is_window(a.hwnd)}
        rows = roblox.all_windows(known.keys()) if win.IS_WIN else []
        if not rows:
            ctk.CTkLabel(self.box, text="No Roblox windows found.", font=F(13), text_color=MUTED).pack(pady=20)
            return
        for r in rows:
            row = ctk.CTkFrame(self.box, fg_color=CARD, corner_radius=10)
            row.pack(fill="x", padx=6, pady=4)
            owner = known.get(r["pid"])
            info = f"{r['title']}\n{r['exe']} · {r['size'][0]}×{r['size'][1]}" + (f" · linked to {owner}" if owner else "")
            ctk.CTkLabel(row, text=info, font=F(12), text_color=MUTED if owner else TEXT, justify="left").pack(
                side="left", padx=12, pady=8)
            pill_button(row, "Link", lambda r=r: self._link(r), width=70).pack(side="right", padx=(4, 10))
            ghost_button(row, "Show", lambda r=r: threading.Thread(target=win.focus, args=(r["hwnd"],),
                                                                     daemon=True).start(), width=70).pack(side="right")

    def _link(self, r):
        for a in self.app.accounts:
            if a is not self.acc and a.pid == r["pid"]:
                if not messagebox.askyesno("Already linked", f"That window is linked to {a.username}. Move it to "
                                           f"{self.acc.username}?", parent=self):
                    return
                a.pid, a.hwnd, a.status = 0, 0, "Offline"
        job = self.app.launching.get(self.acc.user_id)
        if job is not None:
            job["cancel"] = "linked"
            self.app.launching.pop(self.acc.user_id, None)
        roblox.link(self.acc, r["pid"], r["hwnd"])
        self.acc.status = "In game"
        self.app.log(f"Linked to the Roblox window you picked (pid {r['pid']}).", self.acc)
        self.app._arrange_soon()
        self.destroy()


class AddAccountDialog(ctk.CTkToplevel):
    def __init__(self, app, page):
        super().__init__(app)
        self.app, self.page = app, page
        self.title("Add account")
        self.geometry("560x520")
        self.configure(fg_color=PANEL)
        self.transient(app)
        self.after(50, self.grab_set)

        ctk.CTkLabel(self, text="Add a Roblox account", font=F(20, "bold"), text_color=TEXT).pack(
            anchor="w", padx=24, pady=(22, 4))
        steps = ("1. In your browser, log into the account on roblox.com.\n"
                 "2. Press F12 → Application (Chrome/Edge) or Storage (Firefox) → Cookies → roblox.com.\n"
                 "3. Copy the value of .ROBLOSECURITY and paste it below.\n"
                 "Tip: closing that browser tab is fine, but clicking “Log out” kills the cookie.")
        ctk.CTkLabel(self, text=steps, font=F(12), text_color=MUTED, justify="left").pack(anchor="w", padx=24)

        warn = ctk.CTkFrame(self, fg_color="#2a1c22", corner_radius=12, border_width=1, border_color="#5a2a36")
        warn.pack(fill="x", padx=24, pady=14)
        ctk.CTkLabel(warn, text="⚠  This cookie IS your login. Anyone who has it can use your account.\n"
                                "It's stored encrypted to your Windows user and only sent to roblox.com.\n"
                                "Never paste it into a site or tool you don't trust.",
                     font=F(12), text_color="#ffb3c0", justify="left").pack(anchor="w", padx=14, pady=10)

        self.box = ctk.CTkTextbox(self, height=120, font=("Consolas", 11), fg_color=CARD,
                                  border_color=BORDER, border_width=1, corner_radius=10)
        self.box.pack(fill="x", padx=24)
        self.msg = ctk.CTkLabel(self, text="", font=F(12), text_color=MUTED)
        self.msg.pack(anchor="w", padx=24, pady=8)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 20))
        self.ok = pill_button(row, "Verify & save", self._verify, width=150)
        self.ok.pack(side="right")
        ghost_button(row, "Cancel", self.destroy).pack(side="right", padx=8)

    def _verify(self):
        raw = self.box.get("1.0", "end")
        self.ok.configure(state="disabled")
        self.msg.configure(text="Checking with Roblox...", text_color=MUTED)

        def run():
            try:
                cookie = roblox.clean_cookie(raw)
                me = roblox.whoami(cookie)
                avatar = roblox.headshot_url(me["id"])
                enc = protect(cookie)
            except Exception as e:
                err = str(e)
                self.app.ui(lambda: (self.msg.configure(text=f"✖ {err}", text_color=BAD),
                                     self.ok.configure(state="normal")))
                return

            def done():
                existing = next((a for a in self.app.accounts if a.user_id == me["id"]), None)
                if existing:
                    existing.cookie_enc, existing.username = enc, me["name"]
                    existing.display_name = me.get("displayName", "")
                    self.app.log("Cookie updated.", existing)
                else:
                    a = Account(user_id=me["id"], username=me["name"],
                                display_name=me.get("displayName", ""), cookie_enc=enc, avatar_url=avatar)
                    self.app.accounts.append(a)
                    self.app.log("Account added.", a)
                self.app.save()
                self.page.rebuild()
                self.destroy()
            self.app.ui(done)

        threading.Thread(target=run, daemon=True).start()


KEEP_MONITOR = "Wherever it opens"

SETTINGS_FORM = [
    ("Game", [
        ("game_link", "Game or private server link", str,
         "A normal game link, or a private server link (either the …privateServerLinkCode=… kind or the "
         "roblox.com/share?code=…&type=Server kind). Every account joins it."),
    ]),
    ("Windows", [
        ("monitor", "Put game windows on", "monitor",
         "Accounts with “Tile” on go to this monitor. Turn “Tile” off for an account you play/script yourself."),
        ("fit_to_screen", "Size windows to fit the screen automatically", bool,
         "Picks the biggest size where every window fits above the taskbar."),
        ("window_w", "Window width (when auto-fit is off)", int, ""),
        ("window_h", "Window height (when auto-fit is off)", int, ""),
        ("auto_arrange", "Arrange windows after launch", bool, "Tiles windows so they don't overlap."),
        ("maximize_untiled", "Maximize windows with Tile off", bool,
         "When an untiled window (like your main) opens, it's maximized: a normal window filling the "
         "screen, not Roblox fullscreen. Once per window, so you can still resize it yourself."),
        ("untiled_monitor", "Put windows with Tile off on", "monitor_keep",
         "Where untiled windows are maximized. “Wherever it opens” leaves them on their own monitor."),
        ("launch_gap_s", "Seconds between launches", float,
         "Time between starting each Roblox. It no longer waits for the window to open first, so "
         "accounts load side by side. Raise it if your PC struggles with several opening at once."),
    ]),
    ("Boost shop", [
        ("boost_every_min", "Restock every (min)", float, ""),
        ("boost_align_clock", "Line up with the clock (:00, :05, :10...)", bool,
         "Turn off if the restocks don't happen on round times."),
        ("boost_offset_s", "Seconds after restock", float, "Small delay so the new stock has loaded. "
         "The account must stand at the boosts stand: it checks for the 'Boosts Store' prompt, then presses E."),
    ]),
    ("Selene", [
        ("selene_check_s", "Look for her every (s)", float, "Your AFK spot has to be near where she appears."),
        ("selene_cooldown_min", "After buying, ignore her for (min)", float, ""),
        ("selene_turn_wait_s", "Selene round: look for her on each account for (s)", float,
         "The game only draws the window in front, so when one window (your main) sees Selene, every "
         "other Selene account gets brought forward in turn and checked."),
        ("focus_settle_s", "After bringing a window forward, wait up to (s)", float,
         "For the game to draw it again before anything is read or clicked."),
    ]),
    ("Boost shop items", [
        *[(items.setting_key("boost", k), name, bool, "") for k, name in items.BOOST_ITEMS],
    ]),
    ("Selene items", [
        *[(items.setting_key("selene", k), name, bool, "") for k, name in items.SELENE_ITEMS],
        (items.setting_key("selene", "character"), "The character (when Selene sells one)", bool,
         "It appears in her first slot and pushes Luck Lvl 3 one place right; that's how the app spots it. "
         "Abilities (the star icon) are never bought."),
        ("buy_unknown_items", "Buy items it doesn't recognise", bool,
         "New potions the game adds later. Off: they're skipped and named in the log so you know."),
    ]),
    ("Rebirth", [
        ("rebirth_every_min", "Try rebirth every (min)", float,
         "If you can't afford it, the 'Skip Rebirth' Robux pop-up is closed and it tries again later."),
        ("rebirth_popup_wait_s", "Watch for 'Skip Rebirth' pop-up for (s)", float,
         "Raise this if the pop-up shows up late on your PC."),
    ]),
    ("Auto ability", [
        ("ability_key", "Ability key", str,
         "The key that fires your ability (V by default). Switch it on per account with 'Auto ability' on the "
         "Accounts page, so you can run it on some windows and not on others."),
        ("ability_every_s", "Look / press every (s)", float,
         "How often each switched-on window is checked. Every check brings that window forward for a moment, so "
         "don't set it very low with many windows."),
        ("ability_only_ready", "Press only when the button is ready (green)", bool,
         "Needs the button marked below. Without a marked button the key is simply pressed on the timer."),
    ]),
    ("Performance", [
        ("opt_low_graphics", "Low graphics for all Roblox clients", bool,
         "Lowest render quality and textures, no anti-aliasing or grass, using only Roblox's officially "
         "allowed settings file. Takes effect when a client (re)starts. Applies to your main too."),
        ("opt_low_priority", "Lower CPU priority for tiled windows", bool,
         "Alts (windows with Tile on) run at 'Below normal' priority so your main and PC stay smooth."),
        ("opt_trim_min", "Trim tiled windows' memory every (min)", float,
         "Hands memory the alts aren't using back to Windows. 0 = off."),
    ]),
    ("Hallow's Eve", [
        ("event_check_s", "Check event every (s)", float,
         "Reads the event banner at the top. Needs Tesseract (the text reader). Works best on a "
         "full-size window; small tiles make the text tiny."),
        ("char_slots", "Character slots", str,
         "Hotbar slots with characters, like 2-4 or 3,4,6,9 (0 = slot 10). They don't have to be next to "
         "each other. Characters that already have a mutation and potions are skipped."),
        ("mutation_cycle", "Move to the next character when the mutation shows", bool,
         "When the held character gets the mutation below, hold the next unmutated one. A character that gets "
         "a different mutation is always swapped out."),
        ("mutation_word", "Mutation to wait for", str, "Dracula by default."),
        ("hallows_end_lead_s", "Put the character away this many seconds before the event ends", float,
         "Reads the event's countdown so a last-second catch can't mutate it. Needs a fairly big window "
         "(about 1500 px wide or more) to read the timer; otherwise it's put away when the banner goes. 0 = off."),
    ]),
    ("General", [
        ("anti_afk_min", "Anti-AFK after idle (min)", float,
         "Brings the window forward, wiggles the mouse over the game and clicks, so Roblox doesn't "
         "kick you after 20 min. Never clicks while a shop, menu or Robux pop-up is open."),
        ("anti_afk_clicks", "Anti-AFK clicks each time", int, ""),
        ("rejoin_check_s", "Check for 'Disconnected' every (s)", float,
         "With Rejoin on, a disconnected account (server shut down, error 256/277...) is closed and "
         "launched again, and the Welcome Back pop-up is closed so it keeps fishing. It reads the pop-up "
         "and Roblox's own log files, so it works on small windows too. 0 = off."),
        ("low_ram_restart", "Restart Roblox when the PC runs low on RAM", bool,
         "Off by default. When free RAM stays under the amount below, the Roblox using the most memory is "
         "closed and launched again (at most one every 3 minutes). Only turn it on if your PC runs out of RAM "
         "and Roblox crashes."),
        ("ram_restart_mb", "Low RAM means less than this much free (MB)", float,
         "Used by the switch above. Rejoins also wait (up to 2 minutes) until this much RAM is free."),
        ("rejoin_if_closed", "Also rejoin if Roblox closes or crashes", bool,
         "With Rejoin on, an account whose Roblox window closes by itself is launched again. Use the "
         "Close button in this app to close an account for good."),
        ("game_fps", "Roblox FPS limit", float,
         "If you cap Roblox's FPS low to save CPU (5-15 FPS), put that number here so key presses and "
         "clicks are held long enough for the game to notice them. Leave 60 if you don't cap it."),
        ("restore_user_focus", "Give focus back to my window after each action", bool, ""),
        ("wait_for_idle_s", "Wait until mouse/keyboard are idle for (s)", float,
         "Before taking control, waits for this long with no input from you or another script. 0 = off."),
        ("check_updates", "Check for updates on launch", bool,
         "Looks for a newer release on GitHub when the app opens; shows an Update button in the sidebar "
         "if there is one. It only updates when you click it."),
    ]),
]


class AutomationPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self.vars = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 10))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Settings", font=F(26, "bold"), text_color=TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text="Timers and behaviour shared by every account. Turn features on per "
                                "account on the Accounts page.", font=F(12), text_color=MUTED).grid(
            row=1, column=0, sticky="w")
        self.saved = ctk.CTkLabel(head, text="", font=F(12), text_color=GOOD)
        self.saved.grid(row=0, column=1, rowspan=2, padx=12)
        pill_button(head, "Save", self._save, width=100).grid(row=0, column=2, rowspan=2)

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.grid_columnconfigure((0, 1), weight=1, uniform="c")
        for i, (title, fields) in enumerate(SETTINGS_FORM):
            card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=8, pady=8)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=title, font=F(15, "bold"), text_color=TEXT).grid(
                row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 6))
            r = 1
            for key, label, typ, hint in fields:
                val = app.settings.get(key)
                if key == "char_slots" and not str(val or "").strip():
                    val = f"{app.settings.get('first_slot', 2)}-{app.settings.get('last_slot', 4)}"
                ctk.CTkLabel(card, text=label, font=F(12), text_color=TEXT, anchor="w").grid(
                    row=r, column=0, sticky="w", padx=16, pady=(6, 0))
                if typ in ("monitor", "monitor_keep"):
                    mons = win.monitors()
                    labels = [win.monitor_label(m) for m in mons]
                    if typ == "monitor_keep":
                        cur = next((l for m, l in zip(mons, labels) if m["n"] == int(val or 0)), KEEP_MONITOR)
                        labels = [KEEP_MONITOR] + labels
                    else:
                        cur = next((l for m, l in zip(mons, labels) if m["n"] == int(val or 1)), labels[0])
                    v = tk.StringVar(value=cur)
                    ctk.CTkOptionMenu(card, values=labels, variable=v, width=260, height=30, font=F(12),
                                      fg_color=CARD_HI, button_color=ACCENT, button_hover_color=ACCENT_HI).grid(
                        row=r, column=1, sticky="e", padx=16, pady=(6, 0))
                elif typ is bool:
                    v = tk.BooleanVar(value=bool(val))
                    ctk.CTkSwitch(card, text="", variable=v, progress_color=ACCENT, width=44).grid(
                        row=r, column=1, sticky="e", padx=16, pady=(6, 0))
                else:
                    v = tk.StringVar(value=str(val))
                    ctk.CTkEntry(card, textvariable=v, width=260 if typ is str else 90, height=30,
                                 fg_color=BG, border_color=BORDER, corner_radius=8, font=F(12)).grid(
                        row=r, column=1, sticky="e", padx=16, pady=(6, 0))
                self.vars[key] = (v, typ)
                r += 1
                if hint:
                    ctk.CTkLabel(card, text=hint, font=F(11), text_color=MUTED, anchor="w",
                                 wraplength=380, justify="left").grid(
                        row=r, column=0, columnspan=2, sticky="w", padx=16)
                    r += 1
            if title == "Auto ability":
                r = self._ability_controls(card, r)
            ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=r, column=0)

    def _ability_controls(self, card, r):
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=r, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 0))
        pill_button(row, "Mark ability button", self._mark_ability, width=170).pack(side="left", padx=(0, 8))
        ghost_button(row, "Test", self._test_ability, width=64).pack(side="left")
        self.ability_lbl = ctk.CTkLabel(card, text="", font=F(11), text_color=MUTED, anchor="w",
                                        wraplength=380, justify="left")
        self.ability_lbl.grid(row=r + 1, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 0))
        self._ability_label()
        return r + 2

    def _ability_label(self):
        pos = self.app.settings.get("ability_pos")
        if ability.valid_pos(pos):
            self.ability_lbl.configure(text=f"Button marked at {float(pos[0]) * 100:.1f}% across, "
                                            f"{float(pos[1]) * 100:.1f}% down (works at any window size).")
        else:
            self.ability_lbl.configure(text="Button not marked yet. Put the mouse over the ability button in a "
                                            "Roblox window, then click 'Mark ability button' and keep the mouse "
                                            "there for 5 seconds.")

    def _window_under_cursor(self):
        cx, cy = win.cursor_pos()
        for a in self.app.accounts:
            if not (a.hwnd and win.is_window(a.hwnd)):
                continue
            l, t, w, h = win.client_rect(a.hwnd)
            if w > 0 and h > 0 and l <= cx < l + w and t <= cy < t + h:
                return a, (cx - l) / w, (cy - t) / h
        return None, 0.0, 0.0

    def _mark_ability(self):
        if not win.IS_WIN:
            return

        def run():
            self.app.log("Auto ability: keep the mouse over the ability button in a Roblox window. "
                         "Reading its position in 5 seconds...")
            time.sleep(5.0)
            acc, fx, fy = self._window_under_cursor()
            if acc is None:
                self.app.log("Auto ability: the mouse wasn't over a Roblox window. Try again.", level="warn")
                return
            self.app.settings["ability_pos"] = [round(fx, 4), round(fy, 4)]
            save_settings(self.app.settings)
            self.app.ui(self._ability_label)
            self.app.log(f"Auto ability: button marked on {acc.username}'s window ({fx * 100:.1f}%, {fy * 100:.1f}%).")
            self._test_ability_on(acc)

        threading.Thread(target=run, daemon=True).start()

    def _test_ability(self):
        if not win.IS_WIN:
            return

        def run():
            pos = self.app.settings.get("ability_pos")
            if not ability.valid_pos(pos):
                self.app.log("Auto ability: mark the button first.", level="warn")
                return
            for a in self.app.accounts:
                if a.hwnd and win.is_window(a.hwnd):
                    self._test_ability_on(a)
                    return
            self.app.log("Auto ability: no Roblox window is open.", level="warn")

        threading.Thread(target=run, daemon=True).start()

    def _test_ability_on(self, acc):
        try:
            img = win.capture_window(acc.hwnd)
            pos = self.app.settings.get("ability_pos")
            if img is None or not ability.valid_pos(pos):
                self.app.log("Auto ability: couldn't read the window.", acc, "warn")
                return
            frac = ability.ready_fraction(img, pos)
            state = "READY (green)" if frac >= ability.READY_FRACTION else "not ready (grey / on cooldown)"
            self.app.log(f"Auto ability test: green share {frac:.2f} -> {state}. Needs {ability.READY_FRACTION:.2f} "
                         "to count as ready. (A window that's behind others may show an old picture; test with the "
                         "game in front.)", acc)
        except Exception as e:
            self.app.log(f"Auto ability test failed: {e}", acc, "warn")

    def _save(self):
        errors = []
        prev_mon = self.app.settings.get("untiled_monitor", 0)
        for key, (v, typ) in self.vars.items():
            try:
                if typ in ("monitor", "monitor_keep"):
                    self.app.settings[key] = 0 if v.get() == KEEP_MONITOR else int(v.get().split()[1])
                    continue
                self.app.settings[key] = typ(v.get()) if typ is not str else v.get().strip()
            except ValueError:
                errors.append(key)
        if self.app.settings.get("char_slots", "").strip() and not hallows.parse_slots(self.app.settings["char_slots"]):
            errors.append("char_slots")
        if errors:
            self.saved.configure(text=f"Check: {', '.join(errors)}", text_color=BAD)
            return
        save_settings(self.app.settings)
        self.app.apply_graphics()
        if self.app.settings.get("untiled_monitor", 0) != prev_mon and hasattr(self.app, "_maxed"):
            self.app._maxed.clear()
        self.saved.configure(text="✓ Saved", text_color=GOOD)
        self.after(2500, lambda: self.saved.configure(text=""))


def test_detection(app, acc):
    if not acc.hwnd or not win.is_window(acc.hwnd):
        messagebox.showinfo("No window", "Launch this account first.")
        return
    img = win.capture_window(acc.hwnd)
    if img is None:
        messagebox.showerror("Capture failed", "Couldn't read that window.")
        return
    s = app.settings
    boxes, found = [], []
    p = builtin.selene_prompt(img)
    if p:
        boxes.append((p[0] - 45, p[1] - 15, 90, 30, GOOD, "Selene prompt"))
        found.append("Selene's prompt")
    p = builtin.boost_prompt(img)
    if p:
        boxes.append((p[0] - 45, p[1] - 15, 90, 30, GOOD, "Boosts Store prompt"))
        found.append("Boosts Store prompt")
    x = builtin.close_x(img)
    if x:
        boxes.append((x[0] - 14, x[1] - 14, 28, 28, PINK, "X"))
        found.append("red X")
    rb = builtin.rebirth_button(img)
    if rb:
        bx, by, sc = rb
        boxes.append((bx - 170 * sc, by - 30 * sc, 340 * sc, 60 * sc, GOOD, "Rebirth!"))
        line = builtin.sacrifice_line_present(img, rb)
        found.append("rebirth menu (" + ("'Reach 250' line OK" if line else "'Reach 250' line NOT found") + ")")
    side = builtin.side_rebirth_button(img)
    if side:
        boxes.append((side[0] - 25, side[1] - 25, 50, 50, ACCENT, "REBIRTH"))
        found.append("REBIRTH button")
    btns = builtin.find_buy_buttons(img)
    shop_ids = {}
    for shop in ("selene", "boost"):
        ids = items.identify(img, btns, shop)
        shop_ids[shop] = ids
    shop = max(shop_ids, key=lambda k: sum(n not in ("unknown", "other") for n, r, f in shop_ids[k]))
    for (kind, bx, by, cx, sc), (item, rect, _f) in zip(btns, shop_ids[shop]):
        st, n = builtin.stock_status(img, bx, by, sc)
        label = {"out": "OUT", "left": f"{n} left", "ok": "buy"}[st]
        buy = items.wanted(s, shop, item)
        boxes.append((bx - 12 * sc - 2, by - 12 * sc - 2, 24 * sc + 4, 24 * sc + 4, BAD if st == "out" else GOOD,
                      f"{kind} {label}"))
        if rect is not None:
            l, t, r, b = rect
            boxes.append((l, t, r - l, b - t, GOOD if buy else MUTED,
                          f"{items.label(shop, item)} - {'will buy' if buy else 'skip'}"))
    if btns:
        found.append(f"{len(btns)} cash/gem button(s)")
    if builtin.sacrifice_popup(img):
        found.append("SACRIFICE pop-up")
    held_slots = []
    for slot in engine.char_slots(s):
        l, t, r, b = hallows.slot_box(img, slot)
        held, frac = hallows.slot_held(img, slot)
        if held:
            held_slots.append(slot)
        boxes.append((l, t, r - l, b - t, GOOD if held else MUTED, f"{slot}{' HELD' if held else ''}"))
    found.append("held slot: " + (", ".join(map(str, held_slots)) if held_slots else "none"))
    if builtin.ocr_ready():
        on, why = hallows.hallows_event(img)
        found.append("Hallow's Eve: " + ("ON" if on else "not showing"))
        if on:
            left = hallows.event_seconds_left(img)
            found.append("timer: " + (f"{left // 60}:{left % 60:02d} left" if left is not None else "can't read it"))
        muts = [f"{n}={m.title()}" for n in engine.char_slots(s) for m in [hallows.slot_mutation(img, n)] if m]
        found.append("mutations: " + (", ".join(muts) if muts else "none read"))
        ocr = "text reader ON"
    else:
        ocr = "text reader OFF (install Tesseract: needed for Hallow's Eve and OUT OF STOCK)"
    PreviewDialog(app, img, boxes, f"{acc.username} — found: {', '.join(found)}.   [{ocr}]")


class PreviewDialog(ctk.CTkToplevel):
    def __init__(self, app, img, boxes, text):
        super().__init__(app)
        self.title("Test result")
        self.configure(fg_color=PANEL)
        self.transient(app)
        H, W = img.shape[:2]
        scale = min(1100 / W, 640 / H, 2.0)
        dw, dh = int(W * scale), int(H * scale)
        self.photo = ImageTk.PhotoImage(bgr_to_pil(img).resize((dw, dh), Image.LANCZOS))
        ctk.CTkLabel(self, text=text, font=F(13), text_color=TEXT, wraplength=dw).pack(
            anchor="w", padx=16, pady=(12, 6))
        c = tk.Canvas(self, width=dw, height=dh, highlightthickness=0, bg=BG)
        c.pack(padx=16, pady=(0, 16))
        c.create_image(0, 0, image=self.photo, anchor="nw")
        for x, y, w, h, color, label in boxes:
            c.create_rectangle(x * scale, y * scale, (x + w) * scale, (y + h) * scale, outline=color, width=2)
            if label:
                c.create_text(x * scale + 2, y * scale - 2, text=label, anchor="sw", fill=color,
                              font=("Segoe UI", 9, "bold"))


class RemotePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app, self.r = app, app.remote
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.body = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        self.body.grid(row=0, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.body, text="Phone remote", font=F(26, "bold"), text_color=TEXT).grid(
            row=0, column=0, sticky="w", padx=28, pady=(26, 0))
        ctk.CTkLabel(self.body, text="Watch and control FAAR Manager from your phone, and get notifications. It runs "
                     "over Tailscale, so nothing is opened to the internet, and your Roblox logins never leave "
                     "this PC.", font=F(12), text_color=MUTED, wraplength=640, justify="left").grid(
            row=1, column=0, sticky="w", padx=28, pady=(2, 12))

        c1 = self._card(2, "1. Tailscale",
                        "Install Tailscale on this PC and on your phone (tailscale.com, free) and sign in to the "
                        "same account on both.")
        self.ts_lbl = ctk.CTkLabel(c1, text="", font=F(12), text_color=MUTED, wraplength=560, justify="left")
        self.ts_lbl.grid(row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(2, 12))

        c2 = self._card(3, "2. PIN", "Your phone asks for this PIN once. Use at least 6 digits.")
        self.pin = ctk.CTkEntry(c2, show="•", width=180, height=32, fg_color=BG, border_color=BORDER,
                                corner_radius=8, font=F(13))
        self.pin.grid(row=2, column=0, sticky="w", padx=16, pady=(4, 4))
        pill_button(c2, "Save PIN", self._save_pin).grid(row=2, column=1, sticky="e", padx=16)
        self.pin_lbl = ctk.CTkLabel(c2, text="", font=F(12), text_color=MUTED)
        self.pin_lbl.grid(row=3, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 12))

        c3 = self._card(4, "3. Turn it on", "Starts the remote and shares it on your Tailscale network as an "
                        "https:// link.")
        self.on_var = tk.BooleanVar(value=bool(app.settings.get("remote_enabled")))
        ctk.CTkSwitch(c3, text="Phone remote on", variable=self.on_var, command=self._toggle,
                      progress_color=ACCENT, font=F(13)).grid(row=2, column=0, sticky="w", padx=16, pady=4)
        pill_button(c3, "Set up Tailscale link", self._setup_link, width=180).grid(row=2, column=1, sticky="e", padx=16)
        self.url_lbl = ctk.CTkLabel(c3, text="", font=F(14, "bold"), text_color=ACCENT_HI, wraplength=560,
                                    justify="left")
        self.url_lbl.grid(row=3, column=0, sticky="w", padx=16, pady=(6, 0))
        self.copy_btn = ghost_button(c3, "Copy link", self._copy)
        self.copy_btn.grid(row=3, column=1, sticky="e", padx=16, pady=(6, 0))
        self.st_lbl = ctk.CTkLabel(c3, text="", font=F(12), text_color=MUTED, wraplength=560, justify="left")
        self.st_lbl.grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 12))

        self._card(5, "4. On your phone",
                   "Open the link (with Tailscale on), then add it to your home screen: on iPhone tap Share → "
                   "Add to Home Screen, on Android tap ⋮ → Add to Home screen / Install app. Open FAAR from the "
                   "home screen, type your PIN, then tap Turn on under Notifications.")

        c5 = self._card(6, "Notify me about", "")
        r = 2
        self.kind_vars = {}
        for k, label in remote.KINDS.items():
            v = tk.BooleanVar(value=bool(app.settings.get(f"notify_{k}", True)))
            ctk.CTkSwitch(c5, text=label, variable=v, progress_color=ACCENT, font=F(13),
                          command=lambda k=k, v=v: self._kind(k, v)).grid(row=r, column=0, columnspan=2,
                                                                           sticky="w", padx=16, pady=3)
            self.kind_vars[k] = v
            r += 1
        self.phones_lbl = ctk.CTkLabel(c5, text="", font=F(12), text_color=MUTED)
        self.phones_lbl.grid(row=r, column=0, sticky="w", padx=16, pady=(8, 12))
        bx = ctk.CTkFrame(c5, fg_color="transparent")
        bx.grid(row=r, column=1, sticky="e", padx=16, pady=(8, 12))
        ghost_button(bx, "Test", self._test, width=70).pack(side="left", padx=(0, 6))
        ghost_button(bx, "Remove all phones", self._clear_phones, width=140).pack(side="left")

        c6 = self._card(7, "Signed-in phones", "If you lose a phone or shared the PIN, sign everyone out and "
                        "change the PIN.")
        ghost_button(c6, "Sign out all phones", self._signout, width=160).grid(
            row=2, column=0, sticky="w", padx=16, pady=(4, 14))
        self.refresh()

    def _card(self, row, title, hint):
        card = ctk.CTkFrame(self.body, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        card.grid(row=row, column=0, sticky="ew", padx=28, pady=6)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=F(15, "bold"), text_color=TEXT).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 2))
        if hint:
            ctk.CTkLabel(card, text=hint, font=F(12), text_color=MUTED, wraplength=600, justify="left").grid(
                row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 6 if title[0].isdigit() else 14))
        return card

    def on_show(self):
        self.refresh()

    def refresh(self):
        has = self.r.has_pin()
        self.pin_lbl.configure(text="A PIN is set." if has else "No PIN yet.", text_color=GOOD if has else WARN)
        exe = remote.tailscale_exe()
        self.ts_lbl.configure(text=("Tailscale found on this PC." if exe else
                                    "Tailscale isn't installed on this PC yet."),
                              text_color=GOOD if exe else WARN)
        url = self.app.settings.get("remote_url", "")
        self.url_lbl.configure(text=url or "No link yet: click Set up Tailscale link.")
        run = self.r.running()
        self.st_lbl.configure(text="Running." if run else "Off.", text_color=GOOD if run else MUTED)
        n = len(self.r.cfg.get("subs", []))
        self.phones_lbl.configure(text=f"{n} phone{'s' if n != 1 else ''} get notifications.")

    def _save_pin(self):
        pin = self.pin.get().strip()
        if len(pin) < 6 or not pin.isdigit():
            messagebox.showerror("PIN", "Use at least 6 digits (numbers only).")
            return
        self.r.set_pin(pin)
        self.pin.delete(0, "end")
        self.app.log("Phone remote: PIN changed (every phone has to sign in again).")
        self.refresh()

    def _toggle(self):
        on = bool(self.on_var.get())
        if on and not self.r.has_pin():
            self.on_var.set(False)
            messagebox.showinfo("Set a PIN first", "Save a PIN in step 2 first.")
            return
        self.app.settings["remote_enabled"] = on
        save_settings(self.app.settings)
        if on:
            self.r.start()
        else:
            self.r.stop()
        self.after(300, self.refresh)

    def _setup_link(self):
        if not self.r.has_pin():
            messagebox.showinfo("Set a PIN first", "Save a PIN in step 2 first.")
            return
        if not self.r.running():
            self.on_var.set(True)
            self._toggle()
        self.st_lbl.configure(text="Asking Tailscale…", text_color=WARN)

        def go():
            ok, msg = self.r.setup_tailscale(
                status=lambda m: self.app.ui(lambda: self.st_lbl.configure(text=m, text_color=WARN)))

            def done():
                if ok:
                    self.app.settings["remote_url"] = msg
                    save_settings(self.app.settings)
                    self.app.log(f"Phone remote link: {msg}")
                    self.refresh()
                else:
                    self.refresh()
                    self.st_lbl.configure(text=msg, text_color=BAD)
            self.app.ui(done)
        threading.Thread(target=go, daemon=True).start()

    def _copy(self):
        url = self.app.settings.get("remote_url", "")
        if url:
            self.clipboard_clear()
            self.clipboard_append(url)
            self.copy_btn.configure(text="Copied")
            self.after(1500, lambda: self.copy_btn.configure(text="Copy link"))

    def _kind(self, k, v):
        self.app.settings[f"notify_{k}"] = bool(v.get())
        save_settings(self.app.settings)

    def _test(self):
        if not self.r.cfg.get("subs"):
            messagebox.showinfo("No phones yet", "Turn on notifications in the phone app first.")
            return
        threading.Thread(target=self.r._send_all, args=(list(self.r.cfg["subs"]), {
            "title": "FAAR Manager", "body": "Test notification. You're all set!", "tag": "test"}),
            daemon=True).start()

    def _clear_phones(self):
        if messagebox.askyesno("Remove all phones", "Stop sending notifications to every phone?"):
            self.r.clear_subs()
            self.refresh()

    def _signout(self):
        if messagebox.askyesno("Sign out all phones", "Every phone will need the PIN again. Continue?"):
            self.r.sign_out_all()
            self.app.log("Phone remote: signed out every phone.")


class LogPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 10))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Activity log", font=F(26, "bold"), text_color=TEXT).grid(row=0, column=0, sticky="w")
        ghost_button(head, "Clear", self._clear).grid(row=0, column=1)
        self.box = ctk.CTkTextbox(self, font=("Consolas", 12), fg_color=CARD, corner_radius=14,
                                  border_width=1, border_color=BORDER, wrap="word")
        self.box.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 24))
        for tag, color in (("info", TEXT), ("warn", WARN), ("error", BAD)):
            self.box.tag_config(tag, foreground=color)
        self.box.configure(state="disabled")

    def drain(self):
        lines = []
        try:
            while True:
                lines.append(self.app.log_lines.get_nowait())
        except queue.Empty:
            pass
        if not lines:
            return
        self.box.configure(state="normal")
        for line, level in lines:
            self.box.insert("end", line + "\n", level)
        if int(self.box.index("end-1c").split(".")[0]) > 3000:
            self.box.delete("1.0", "500.0")
        self.box.see("end")
        self.box.configure(state="disabled")

    def _clear(self):
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.configure(state="disabled")


def main():
    App().mainloop()
