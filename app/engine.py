import math
import gc
import random
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import win, purchase, builtin, hallows, route, roblox, ability, items, rlogs, storage


CLICK_HOLD = 0.12
KEY_HOLD = 0.15


def free_ram_mb():
    try:
        import psutil
        return psutil.virtual_memory().available / 2 ** 20
    except Exception:
        return None


def _low_memory(e):
    if isinstance(e, MemoryError):
        return True
    text = str(e)
    return "Insufficient memory" in text or "OutOfMemory" in text or "Failed to allocate" in text


class Abort(Exception):
    pass


class PurchasePromptOpen(Abort):
    pass


@dataclass
class AccState:
    next_rebirth: float = 0
    next_boost: float = 0
    next_selene: float = 0
    selene_until: float = 0
    next_event: float = 0
    last_input: float = field(default_factory=time.time)
    event_on: bool = False
    ev_votes: int = 0
    cur_slot: int = 0
    done: bool = False
    drac_votes: int = 0
    hcache: dict = field(default_factory=dict)
    next_mut_check: float = 0
    intent: tuple = ()
    intent_count: int = 0
    backoff_until: float = 0
    warned: set = field(default_factory=set)
    disabled: set = field(default_factory=set)
    hold: str = ""
    next_popup_check: float = 0
    next_sacpop_check: float = 0
    next_hold_check: float = 0
    next_disc_check: float = 0
    born: float = field(default_factory=time.time)
    tried: set = field(default_factory=set)
    hold_fail: dict = field(default_factory=dict)
    stray: dict = field(default_factory=dict)
    ev_log: list = field(default_factory=list)
    offlist: int = 0
    ending: bool = False
    mut_name: str = ""
    mut_votes: int = 0
    clean_reads: int = 0
    next_timer: float = 0
    end_at: float = 0
    end_reads: list = field(default_factory=list)
    pending_return: bool = False
    next_ability: float = 0
    ability_presses: int = 0
    ability_warned: bool = False
    boost_miss: int = 0
    selene_miss: int = 0
    stuck_n: int = 0
    err_n: int = 0
    err_until: float = 0


class Engine:
    def __init__(self, get_accounts, get_settings, log):
        self.get_accounts = get_accounts
        self.get_settings = get_settings
        self.log = log
        self.states = {}
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread = None
        self._hotkeys = threading.Thread(target=self._hotkey_loop, daemon=True)
        self._hotkeys.start()
        self.on_status = lambda s: None
        self.notify = lambda kind, title, body, acc=None: None
        self.remote_stop = False
        self.user_closing = False
        self.next_ram_check = 0.0
        self.ram_low_n = 0
        self.ram_restart_at = 0.0
        self.input_lock = win.InputLock()
        self.relaunch = None
        self.logwatch = rlogs.Watcher()
        self.hstats = storage.HallowsStats()
        self.rejoin_times = {}
        self.selene_queue = []
        self.selene_busy = None
        self.selene_busy_since = 0.0

    @property
    def status(self):
        if not self._thread or not self._thread.is_alive():
            return "Stopped"
        return "Paused" if self._paused.is_set() else "Running"

    def start(self):
        if self._thread and self._thread.is_alive() and self._stop.is_set():
            self._thread.join(timeout=10)
        if self._thread and self._thread.is_alive() and not self._stop.is_set():
            self._paused.clear()
        else:
            self._stop.clear()
            self._paused.clear()
            self.states.clear()
            self.selene_queue, self.selene_busy = [], None
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            self.log("Automation started. F8 = pause/resume, F9 = stop.")
        self.on_status(self.status)

    def pause(self, toggle=True):
        if self.status == "Stopped":
            return
        if self._paused.is_set() and toggle:
            self._paused.clear()
            self.log("Resumed.")
        else:
            self._paused.set()
            self.log("Paused.")
        self.on_status(self.status)

    def stop(self):
        self._stop.set()
        self._paused.clear()
        if self._thread:
            self._thread.join(timeout=5)
        self.log("Automation stopped.")
        self.on_status("Stopped")
        if not self.user_closing:
            self.notify("stopped", "Automation stopped",
                        "Stopped from your phone." if self.remote_stop else "Stopped on the PC.")
        self.remote_stop = False

    def _hotkey_loop(self):
        was8 = was9 = False
        while True:
            try:
                k8, k9 = win.key_down_now(win.VK_F8), win.key_down_now(win.VK_F9)
                if k8 and not was8:
                    self.pause()
                if k9 and not was9 and self.status != "Stopped":
                    threading.Thread(target=self.stop, daemon=True).start()
                was8, was9 = k8, k9
            except Exception:
                pass
            time.sleep(0.05)

    def interrupted(self):
        return self._stop.is_set() or self._paused.is_set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._loop_once()
            except Exception as e:
                try:
                    self.log(f"Internal error (the automation keeps running): {e!r}", None, "error")
                except Exception:
                    pass
                time.sleep(2)

    def _loop_once(self):
        if self._paused.is_set():
            time.sleep(0.2)
            return
        s = self.get_settings()
        if time.time() >= self.next_ram_check:
            self.next_ram_check = time.time() + 20
            try:
                self._ram_guard(s)
            except Exception:
                pass
        if self.selene_queue:
            ok = {a.user_id for a in self.get_accounts() if a.hwnd and win.is_window(a.hwnd)
                  and not getattr(self.states.get(a.user_id), "hold", "")}
            self.selene_queue = [u for u in self.selene_queue if u in ok]
        for acc in list(self.get_accounts()):
            if self.interrupted():
                break
            if not acc.hwnd:
                continue
            if not win.is_window(acc.hwnd):
                self._window_gone(acc, s)
                continue
            st = self.states.setdefault(acc.user_id, self._new_state(s))
            if time.time() < st.err_until:
                continue
            try:
                jobs = self._due_jobs(acc, st, s)
                if jobs:
                    self._run_jobs(acc, st, s, jobs)
                st.err_n = 0
            except Abort:
                pass
            except Exception as e:
                if _low_memory(e):
                    self._memory_trouble()
                    time.sleep(5)
                    continue
                if not (acc.hwnd and win.is_window(acc.hwnd)):
                    continue
                st.err_n += 1
                self.log(f"Error: {e}", acc, "error")
                if st.err_n >= 5:
                    st.err_until = time.time() + 60
                    st.err_n = 0
                    self.log("Five errors in a row on this account. Resting it for 60 s; the other accounts carry on.",
                             acc, "warn")
                time.sleep(1)
        time.sleep(0.25)

    def _ram_guard(self, s):
        limit = float(s.get("ram_restart_mb", 1000) or 0)
        if limit <= 0 or not s.get("low_ram_restart", False):
            return
        import psutil
        free = psutil.virtual_memory().available / 2 ** 20
        if free >= limit:
            self.ram_low_n = 0
            return
        self.ram_low_n += 1
        if self.ram_low_n < 2 or time.time() < self.ram_restart_at:
            return
        best, used = None, 0.0
        for acc in self.get_accounts():
            st = self.states.get(acc.user_id)
            if not (acc.hwnd and acc.pid and win.is_window(acc.hwnd)) or st is None or st.hold:
                continue
            if self.selene_busy == acc.user_id:
                continue
            try:
                info = psutil.Process(acc.pid).memory_info()
                mb = getattr(info, "private", info.rss) / 2 ** 20
            except Exception:
                continue
            if mb > used:
                best, used = acc, mb
        if best is None:
            return
        self.ram_low_n = 0
        self.ram_restart_at = time.time() + 180
        st = self.states[best.user_id]
        self.log(f"Free RAM is low ({free:.0f} MB, limit {limit:.0f} MB). Restarting this Roblox to free memory "
                 f"(it's using {used:.0f} MB).", best, "warn")
        self.notify("needs_you", "Low RAM: restarting a Roblox",
                    f"Only {free:.0f} MB free, so this Roblox ({used:.0f} MB) is being restarted.", best)
        self._start_rejoin(best, st, s, "low RAM", quiet=True)

    def _memory_trouble(self):
        gc.collect()
        now = time.time()
        if now < getattr(self, "_mem_warned", 0):
            return
        self._mem_warned = now + 600
        mine = ""
        try:
            import psutil
            vm = psutil.virtual_memory()
            me = psutil.Process().memory_info().rss / 2 ** 20
            mine = (f" Free RAM: {vm.available / 2 ** 30:.1f} GB of {vm.total / 2 ** 30:.1f} GB; "
                    f"FAAR Manager itself is using {me:.0f} MB.")
        except Exception:
            pass
        auto = bool(self.get_settings().get("low_ram_restart", False))
        self.log("Your PC ran out of memory (RAM), so a screenshot couldn't be taken. Roblox windows may crash "
                 "when this happens" + ("; the biggest one will be restarted to free memory. " if auto else
                                         ". Turn on 'Restart Roblox when the PC runs low on RAM' in Settings to "
                                         "let FAAR restart the biggest one. ")
                 + "Close other programs or run fewer accounts if it keeps happening." + mine, None, "error")
        self.next_ram_check = 0
        self.ram_low_n = max(self.ram_low_n, 1)
        self.notify("needs_you", "PC out of memory", "Your PC ran out of RAM. Roblox windows may crash.")

    def _new_state(self, s):
        now = time.time()
        return AccState(next_rebirth=now + 20, next_boost=self._next_boost(now, s),
                        next_selene=now + 2, next_event=now + 1, next_ability=now + 5)

    @staticmethod
    def _next_boost(now, s):
        period = max(1, float(s["boost_every_min"])) * 60
        if s.get("boost_align_clock"):
            return math.floor(now / period) * period + period + float(s["boost_offset_s"])
        return now + period

    def _hold_for_sacrifice(self, acc, st):
        st.hold = "sacrifice-popup"
        st.next_hold_check = time.time() + 2
        acc.status = "Waiting for you: SACRIFICE pop-up"
        self.log("The SACRIFICE pop-up is showing (rebirth 250). Nothing will be clicked on this account "
                 "until you close it or take it there yourself.", acc, "warn")
        self.notify("needs_you", "SACRIFICE pop-up", "Rebirth 250 reached. The account is paused until you "
                    "close the pop-up or take it there yourself.", acc)

    def _window_gone(self, acc, s):
        st = self.states.get(acc.user_id)
        acc.hwnd, acc.pid = 0, 0
        if st and st.hold in ("rejoin", "rejoin-stopped"):
            return
        if (acc.features.get("rejoin", True) and s.get("rejoin_if_closed", True)
                and float(s.get("rejoin_check_s", 20)) > 0):
            st = st or self._new_state(s)
            self.states[acc.user_id] = st
            self._start_rejoin(acc, st, s, "the Roblox window closed")
            return
        acc.status = "Offline (closed)"
        self.log("Window closed.", acc)

    def _check_disconnect(self, acc, st, img):
        why = builtin.disconnected(img) if img is not None else ""
        if why:
            return why
        try:
            state = self.logwatch.latest(acc.user_id)
        except Exception:
            return ""
        if not state:
            return ""
        kind, since, code = state
        if kind == "disc" and since > st.born and time.time() - since >= 30:
            return f"error {code}" if code else "disconnected"
        return ""

    def _rejoin_allowed(self, acc):
        now = time.time()
        times = [x for x in self.rejoin_times.get(acc.user_id, []) if now - x < 1800]
        if len(times) >= 5:
            self.rejoin_times[acc.user_id] = times
            return False
        times.append(now)
        self.rejoin_times[acc.user_id] = times
        return True

    def _start_rejoin(self, acc, st, s, why, quiet=False):
        if not self._rejoin_allowed(acc):
            st.hold = "rejoin-stopped"
            st.next_hold_check = time.time() + 1e9
            acc.status = "Offline (too many rejoins)"
            self.log(f"Disconnected again ({why}). That's 5 rejoins in 30 min, so this account is left alone "
                     "now. Launch it yourself when you're back.", acc, "error")
            self.notify("needs_you", "Stopped rejoining", "5 rejoins in 30 minutes. This account is left "
                        "alone until you launch it.", acc)
            return
        st.hold = "rejoin"
        acc.status = f"Rejoining ({why})"
        if quiet:
            pass
        elif why.startswith("the Roblox window"):
            self.log("Roblox closed by itself. Rejoining.", acc, "warn")
            self.notify("disconnects", "Roblox closed", "Roblox closed by itself. Rejoining.", acc)
        else:
            extra = ", the server was shut down" if why == "error 256" else ""
            self.log(f"Disconnected ({why}{extra}). Rejoining.", acc, "warn")
            self.notify("disconnects", "Disconnected", f"{why}{extra}. Rejoining.", acc)
        threading.Thread(target=self._rejoin, args=(acc, st, s), daemon=True).start()

    def _sleep(self, secs):
        end = time.time() + secs
        while time.time() < end:
            if self._stop.is_set():
                return False
            time.sleep(0.25)
        return True

    def _rejoin(self, acc, st, s):
        waits = (20, 45, 90, 120)
        try:
            for attempt in range(1, len(waits) + 2):
                roblox.close(acc)
                acc.hwnd, acc.pid = 0, 0
                if not self._sleep(5):
                    return
                need = float(s.get("ram_restart_mb", 1000) or 0)
                waited = 0
                while need > 0 and waited < 120 and (free_ram_mb() or need) < need:
                    if waited == 0:
                        acc.status = "Waiting for free RAM"
                        self.log(f"Waiting for at least {need:.0f} MB of free RAM before reopening Roblox.", acc)
                    if not self._sleep(5):
                        return
                    waited += 5
                if not self.relaunch:
                    self.log("Can't rejoin from here (no launcher).", acc, "error")
                    return
                ok = False
                if self.relaunch(acc):
                    acc.status = "Loading game..."
                    loaded = route.wait_loaded(acc.hwnd, 150, self._stop.is_set)
                    img = win.capture_window(acc.hwnd) if acc.hwnd and win.is_window(acc.hwnd) else None
                    if img is None:
                        why = "the window closed while loading"
                    else:
                        why = builtin.disconnected(img)
                    if loaded and not why:
                        ok = True
                    elif not why and img is not None:
                        self.log("Rejoined, but the game didn't finish loading in time. Will check again later.",
                                 acc, "warn")
                        ok = True
                    else:
                        self.log(f"The rejoin didn't stick ({why}).", acc, "warn")
                if ok:
                    new = self._new_state(s)
                    new.pending_return = True
                    self.states[acc.user_id] = new
                    acc.status = "In game"
                    return
                if self._stop.is_set():
                    return
                if attempt > len(waits):
                    break
                wait = waits[attempt - 1]
                acc.status = f"Rejoin failed, retrying in {wait}s"
                self.log(f"Rejoin attempt {attempt} failed. Trying again in {wait}s "
                         "(servers can take a minute to come back after a shutdown).", acc, "warn")
                if not self._sleep(wait):
                    return
            roblox.close(acc)
            acc.hwnd, acc.pid = 0, 0
            acc.status = "Offline (rejoin failed)"
            self.log(f"Couldn't rejoin after {len(waits) + 1} tries. Launch it yourself when you're back.",
                     acc, "error")
            self.notify("needs_you", "Rejoin failed", f"Couldn't rejoin after {len(waits) + 1} tries. "
                        "Launch it yourself when you're back.", acc)
        except Exception as e:
            acc.status = "Offline (rejoin error)"
            self.log(f"Rejoin error: {e}", acc, "error")
        finally:
            st.hold = ""

    def _selene_round_wanted(self, acc):
        return any(a.features.get("selene") and a.user_id != acc.user_id and a.hwnd
                   for a in self.get_accounts())

    def _start_selene_round(self, acc, mine, s):
        now = time.time()
        order = []
        for a in self.get_accounts():
            if a.user_id == acc.user_id or not a.features.get("selene") or not a.hwnd:
                continue
            ost = self.states.get(a.user_id)
            if ost and (ost.hold or now < ost.selene_until or "selene" in ost.disabled):
                continue
            order.append(a.user_id)
        self.selene_queue = order
        self.selene_busy = acc.user_id if mine else None
        self.selene_busy_since = now
        names = {a.user_id: a.username for a in self.get_accounts()}
        if order:
            self.log("Selene is here. Visiting her on " + ("this account first, then " if mine else "") +
                     ", ".join(names.get(u, "?") for u in order) + ", one at a time.", acc)
        elif mine:
            self.log("Selene is here.", acc)

    def _selene_wait(self, acc, st, s, ok):
        if ok:
            st.selene_miss = 0
            return float(s["selene_cooldown_min"]) * 60
        st.selene_miss += 1
        if st.selene_miss >= 3:
            if st.selene_miss == 3:
                self.log("Selene wasn't reachable on this account 3 times in a row (is it standing at her spot?). "
                         "Only trying again every 30 min.", acc, "warn")
            return 1800.0
        return 60.0

    def _selene_next(self, acc):
        if self.selene_queue and self.selene_queue[0] == acc.user_id:
            self.selene_queue.pop(0)
        if self.selene_busy == acc.user_id:
            self.selene_busy = None
        live = {a.user_id for a in self.get_accounts() if a.hwnd}
        self.selene_queue = [u for u in self.selene_queue if u in live]
        if not self.selene_queue:
            self.log("Selene round finished.")

    def _warn_once(self, acc, st, key, msg):
        if key not in st.warned:
            st.warned.add(key)
            self.log(msg, acc, "warn")

    def _due_jobs(self, acc, st, s):
        now = time.time()
        f = acc.features
        jobs = []
        bg = None

        def shot():
            nonlocal bg
            if bg is None:
                bg = win.capture_window(acc.hwnd)
            return bg

        if st.hold in ("rejoin", "rejoin-stopped"):
            return []
        if st.pending_return:
            st.pending_return = False
            return [("return",)]
        if (f.get("rejoin", True) and float(s.get("rejoin_check_s", 20)) > 0
                and now >= st.next_disc_check):
            st.next_disc_check = now + max(5.0, float(s.get("rejoin_check_s", 20)))
            why = self._check_disconnect(acc, st, shot())
            if why:
                self._start_rejoin(acc, st, s, why)
                return []

        if st.hold:
            if now < st.next_hold_check:
                return []
            st.next_hold_check = now + 2
            img = shot()
            if img is None:
                return []
            if st.hold == "purchase" and purchase.is_open(img):
                return []
            if st.hold == "sacrifice-popup" and builtin.sacrifice_popup(img):
                return []
            what = "SACRIFICE pop-up" if st.hold == "sacrifice-popup" else "Robux pop-up"
            st.hold = ""
            st.next_rebirth = now + max(1, float(s["rebirth_every_min"])) * 60
            acc.status = "In game"
            self.log(f"{what} is gone. Resuming automation on this account.", acc)
            return []

        if now >= st.next_sacpop_check:
            st.next_sacpop_check = now + 3
            img = shot()
            if img is not None and builtin.sacrifice_popup(img):
                self._hold_for_sacrifice(acc, st)
                return []

        if now >= st.next_popup_check:
            st.next_popup_check = now + 2
            img = shot()
            if img is not None and purchase.is_open(img):
                return [("close_purchase",)]

        if f.get("rebirth") and "rebirth" not in st.disabled and now >= st.next_rebirth:
            st.next_rebirth = now + max(1, float(s["rebirth_every_min"])) * 60
            jobs.append(("rebirth",))

        if f.get("boost_shop") and "boost_shop" not in st.disabled and now >= st.next_boost:
            st.next_boost = self._next_boost(now, s)
            jobs.append(("boost",))

        if now >= st.next_selene and now >= st.selene_until and not self.selene_queue:
            st.next_selene = now + max(1, float(s["selene_check_s"]))
            if f.get("selene") or self._selene_round_wanted(acc):
                img = shot()
                if img is not None and builtin.selene_prompt(img):
                    mine = f.get("selene") and "selene" not in st.disabled
                    self._start_selene_round(acc, mine, s)
                    if mine:
                        jobs.append(("selene",))
                    else:
                        st.selene_until = now + float(s["selene_cooldown_min"]) * 60
        if self.selene_busy is not None and now - self.selene_busy_since > 360:
            self.selene_busy = None
        if (self.selene_queue and self.selene_queue[0] == acc.user_id and self.selene_busy is None
                and not jobs):
            self.selene_busy_since = now
            self.selene_busy = acc.user_id
            jobs.append(("selene_turn",))

        if f.get("hallows_eve") and now >= st.next_event and now >= st.backoff_until:
            st.next_event = now + max(1, float(s["event_check_s"]))
            if not builtin.ocr_ready():
                self._warn_once(acc, st, "hallows-ocr", "Hallow's Eve needs Tesseract (the text reader) to read "
                                "the event banner. Install it (install_requirements.bat of the script does it).")
            else:
                img = shot()
                if img is not None:
                    jobs += self._hallows_decide(acc, st, s, img)

        if (f.get("ability") and "ability" not in st.disabled and not jobs and now >= st.next_ability
                and self.selene_busy != acc.user_id):
            st.next_ability = now + 3
            jobs.append(("ability",))

        if f.get("anti_afk") and not jobs and now - st.last_input >= float(s["anti_afk_min"]) * 60:
            jobs.append(("anti_afk",))
        return jobs

    def _hallows_decide(self, acc, st, s, img):
        slots = char_slots(s)
        word = str(s.get("mutation_word", "dracula") or "dracula").strip().lower()
        reading, why = hallows.hallows_event_cached(img, st.hcache)
        if reading != st.event_on:
            st.ev_votes += 1
            if st.ev_votes >= 2:
                st.event_on, st.ev_votes = reading, 0
                if reading:
                    self._event_started(acc, st, why)
                else:
                    self._event_ended(acc, st, word)
        else:
            st.ev_votes = 0

        if st.event_on and not st.done and not st.ending:
            cur = st.cur_slot if st.cur_slot in slots else 0
            if cur and hallows.slot_held(img, cur)[0]:
                lead = self._timer_check(acc, st, s, img)
                if lead:
                    return lead
            if not cur:
                cur = self._pick_slot(acc, st, slots, img)
                if not cur:
                    return []
            held, _ = hallows.slot_held(img, cur)
            if not held:
                if st.hold_fail.get(cur, 0) >= 1:
                    self.log(f"Slot {cur} won't stay held (empty, or the hotbar can't be read in this window). "
                             "Skipping it.", acc, "warn")
                    st.ev_log.append((cur, "couldn't hold"))
                    st.cur_slot = 0
                    return []
                return self._press_for(acc, st, cur, True)
            st.intent_count = 0
            st.stuck_n = 0
            if time.time() >= st.next_mut_check:
                st.next_mut_check = time.time() + 4
                name = hallows.slot_mutation_cached(img, cur, st.hcache)
                if not name and word in hallows.MUTATIONS:
                    seen = hallows.mutation_seen_cached(img, cur, word, st.hcache)
                    name = word if seen else ""
                if not name:
                    st.clean_reads += 1
                if name and name == st.mut_name:
                    st.mut_votes += 1
                else:
                    st.mut_name, st.mut_votes = name, 1 if name else 0
                if name and st.mut_votes >= 2:
                    return self._mutated(acc, st, s, cur, name, word)
            return []

        out = []
        for slot in slots:
            if hallows.slot_held(img, slot)[0]:
                st.stray[slot] = st.stray.get(slot, 0) + 1
                if st.stray[slot] >= 2 and not out:
                    st.stray[slot] = 0
                    out = self._press_for(acc, st, slot, False)
            else:
                st.stray.pop(slot, None)
        if not out:
            st.intent_count = 0
            st.stuck_n = 0
        return out

    def _event_started(self, acc, st, why):
        st.done = st.ending = False
        st.tried, st.hold_fail, st.stray, st.ev_log = set(), {}, {}, []
        st.cur_slot, st.offlist, st.mut_name, st.mut_votes = 0, 0, "", 0
        st.end_at, st.end_reads, st.next_timer = 0.0, [], 0.0
        d = self.hstats.event(acc.user_id)
        self.log(f"Hallow's Eve started ({why}). That's event #{d['since']} since the last Dracula "
                 f"({d['events']} counted, {d['hits']} Dracula so far).", acc)

    def _event_ended(self, acc, st, word):
        held = ", ".join(f"slot {n}: {what}" for n, what in st.ev_log) or "nothing changed"
        d = self.hstats.get(acc.user_id)
        self.log(f"Hallow's Eve ended. This event: {held}. Events since the last {word.title()}: {d['since']}.", acc)
        st.cur_slot = 0

    def _pick_slot(self, acc, st, slots, img):
        for slot in slots:
            if slot in st.tried:
                continue
            st.tried.add(slot)
            if hallows.slot_is_potion(img, slot):
                self.log(f"Slot {slot} is a potion, skipping it.", acc)
                continue
            name = hallows.slot_mutation(img, slot)
            if name:
                self.log(f"Slot {slot} already has {name.title()}, skipping it.", acc)
                continue
            st.cur_slot, st.mut_name, st.mut_votes, st.clean_reads = slot, "", 0, 0
            st.hcache = {k: v for k, v in st.hcache.items() if k == "banner"}
            return slot
        st.done = True
        st.cur_slot = 0
        self.log("No unmutated characters left in your character slots, so nothing is held for the rest of "
                 "this event.", acc, "warn")
        return 0

    def _mutated(self, acc, st, s, cur, name, word):
        st.mut_name, st.mut_votes = "", 0
        if st.clean_reads == 0:
            self.log(f"Slot {cur} already had {name.title()} (it couldn't be read before it was picked). "
                     "Skipping it.", acc)
            st.cur_slot = 0
            return []
        st.ev_log.append((cur, name.title()))
        if name == word:
            d = self.hstats.hit(acc.user_id, time.strftime("%Y-%m-%d %H:%M"))
            self.log(f"Slot {cur} got {word.title()}! ({d['hits']} so far.) The counter is back to 0.", acc)
            self.notify("dracula", f"{word.title()}!", f"Slot {cur} got {word.title()} "
                        f"({d['hits']} so far).", acc)
            if not s.get("mutation_cycle", True):
                st.done = True
                return []
        else:
            self.log(f"Slot {cur} became {name.title()} instead of {word.title()}. Moving on.", acc)
            if name not in hallows.HALLOWS_GIVES:
                st.offlist += 1
                if st.offlist >= 2:
                    st.ending = True
                    self.hstats.undo_event(acc.user_id)
                    self.log(f"Failsafe: {st.offlist} characters got mutations Hallow's Eve never gives "
                             f"(last one: {name.title()}), so this is probably a different event. Stopping and "
                             "putting the character away. It wasn't added to the counter.", acc, "warn")
                    return self._press_for(acc, st, cur, False)
        st.cur_slot = 0
        return []

    def _timer_check(self, acc, st, s, img):
        now = time.time()
        lead = max(0.0, float(s.get("hallows_end_lead_s", 4) or 0))
        if lead <= 0:
            return []
        if st.end_at and now >= st.end_at - lead:
            st.ending = True
            left = max(0, int(round(st.end_at - now)))
            self.log(f"About {left}s left on the Hallow's Eve timer: putting slot {st.cur_slot} away now so a "
                     "last-second catch can't mutate it.", acc)
            return self._press_for(acc, st, st.cur_slot, False)
        if now < st.next_timer:
            return []
        left = hallows.event_seconds_left(img)
        if left is None:
            st.next_timer = now + 10
            return []
        end = now + left
        st.end_reads = [e for e in st.end_reads if abs(e - end) <= 3][-3:] + [end]
        if len(st.end_reads) >= 2:
            st.end_at = sum(st.end_reads) / len(st.end_reads)
        st.next_timer = now + (1.0 if left <= 25 else min(20.0, left / 4))
        if left <= 25:
            st.next_event = min(st.next_event, now + 1)
        return []

    def _press_for(self, acc, st, slot, want_held):
        intent = (slot, want_held)
        st.intent_count = st.intent_count + 1 if st.intent == intent else 1
        st.intent = intent
        if st.intent_count > 3:
            st.stuck_n += 1
            wait = min(900, 60 * 2 ** min(st.stuck_n - 1, 4))
            self.log(f"Slot {slot} isn't reacting after 3 presses (is the hotbar full, is something in that "
                     f"slot, or is this window too small to read the hotbar?). Waiting {wait // 60} min.",
                     acc, "warn")
            st.backoff_until = time.time() + wait
            st.intent_count = 0
            return []
        return [("key", win.slot_key(slot), f"{'Holding' if want_held else 'Putting away'} slot {slot}",
                 slot, want_held)]

    def _run_jobs(self, acc, st, s, jobs):
        need_idle = float(s.get("wait_for_idle_s", 1.5))
        if need_idle > 0:
            end = time.time() + 30
            while win.idle_seconds() < need_idle and time.time() < end:
                if self.interrupted():
                    return
                time.sleep(0.2)
        if not self.input_lock.acquire(timeout_s=180):
            self.log("Your other script has been using the mouse/keyboard for 3 min. Will try again.", acc, "warn")
            return
        try:
            self._run_jobs_locked(acc, st, s, jobs)
        finally:
            self.input_lock.release()

    def _run_jobs_locked(self, acc, st, s, jobs):
        prev_fg = win.foreground()
        prev_cursor = win.cursor_pos()
        if not win.focus(acc.hwnd):
            self.log("Couldn't bring the window to the front. Will retry.", acc, "warn")
            return
        time.sleep(0.25)
        ctx = Ctx(self, acc, st, s)
        try:
            if jobs[0][0] != "close_purchase":
                wait_drawn(ctx)
            if builtin.sacrifice_popup(ctx.shot()):
                self._hold_for_sacrifice(acc, st)
                return
            if jobs[0][0] != "close_purchase" and ctx.purchase_open():
                self.log("A Robux pop-up was already open. Closing it first.", acc, "warn")
                if not ctx.dismiss_purchase():
                    return
            for job in jobs:
                kind = job[0]
                if kind == "close_purchase":
                    if ctx.dismiss_purchase():
                        self.log("Closed a Robux pop-up (never bought anything). If it came from a rebirth, "
                                 "there wasn't enough cash.", acc)
                    continue
                if kind == "key":
                    self.log(job[2] + ".", acc)
                    ctx.key(job[1])
                    if len(job) >= 5 and not verify_slot_key(ctx, job[1], job[3], job[4]) and job[4]:
                        st.hold_fail[job[3]] = st.hold_fail.get(job[3], 0) + 1
                elif kind == "return":
                    do_return(ctx)
                elif kind == "anti_afk":
                    do_anti_afk(ctx)
                elif kind == "ability":
                    do_ability(ctx)
                elif kind == "rebirth":
                    do_rebirth_builtin(ctx)
                elif kind == "boost":
                    do_boost_builtin(ctx)
                elif kind == "selene_turn":
                    try:
                        ok = do_selene_turn(ctx)
                        st.selene_until = time.time() + self._selene_wait(acc, st, s, ok)
                    finally:
                        self._selene_next(acc)
                elif kind == "selene":
                    try:
                        ok = do_selene_builtin(ctx)
                    finally:
                        if self.selene_busy == acc.user_id:
                            self.selene_busy = None
                    st.selene_until = time.time() + self._selene_wait(acc, st, s, ok)
        except PurchasePromptOpen:
            self.log("A Robux pop-up appeared. Closed it without buying.", acc, "warn")
            ctx.dismiss_purchase()
        except Abort as e:
            if str(e):
                self.log(str(e), acc, "warn")
        finally:
            st.last_input = time.time()
            if s.get("restore_user_focus"):
                try:
                    win.user32.SetCursorPos(*prev_cursor)
                except Exception:
                    pass
                if prev_fg and prev_fg != acc.hwnd:
                    win.restore_focus(prev_fg)


class Ctx:

    def __init__(self, engine, acc, st, s, interrupted=None):
        self.e, self.acc, self.st, self.s = engine, acc, st, s
        self._intr = interrupted or engine.interrupted

    def log(self, msg, level="info"):
        self.e.log(msg, self.acc, level)

    def wait(self, sec):
        end = time.time() + sec
        while time.time() < end:
            if self._intr():
                raise Abort("")
            time.sleep(min(0.05, max(0, end - time.time())))

    def ensure_front(self):
        if win.foreground() != self.acc.hwnd:
            if not win.focus(self.acc.hwnd):
                raise Abort("Lost focus of the window. Stopped this action.")
            time.sleep(0.2)

    def size(self):
        _, _, w, h = win.client_rect(self.acc.hwnd)
        return w, h

    def shot(self):
        img = win.capture_window(self.acc.hwnd)
        if img is None:
            raise Abort("Couldn't read the window.")
        return img

    def screen_xy(self, x, y):
        l, t, _, _ = win.client_rect(self.acc.hwnd)
        return l + int(x), t + int(y)

    def purchase_open(self, img=None):
        return purchase.is_open(self.shot() if img is None else img)

    def click(self, x, y, times=1, gap=0.2):
        self.ensure_front()
        win.move_to(*self.screen_xy(x, y))
        for i in range(times):
            if self._intr():
                raise Abort("")
            if self.purchase_open():
                raise PurchasePromptOpen("")
            win.move_to(*self.screen_xy(x, y))
            win.mouse_click(hold=max(CLICK_HOLD, 1.5 * game_frame(self.s)))
            if i < times - 1:
                time.sleep(gap)

    def dismiss_purchase(self):
        end = time.time() + 8
        clicks, gone, last_xy, scale = 0, 0, None, 1.0
        while time.time() < end:
            if self._intr():
                raise Abort("")
            img = self.shot()
            btn = purchase.find_buy_button(img)
            if btn is None:
                if purchase.x_still_there(img, last_xy, scale):
                    gone = 0
                    if clicks < 3:
                        self._click_raw(last_xy)
                        clicks += 1
                        time.sleep(0.9)
                        continue
                else:
                    gone += 1
                    if gone >= 3:
                        return True
                time.sleep(0.4)
                continue
            gone = 0
            scale = btn[2] / 416.0
            xy = purchase.find_close(img)
            if xy:
                last_xy = xy
            if not last_xy or clicks >= 3:
                time.sleep(0.4)
                continue
            self._click_raw(last_xy)
            clicks += 1
            time.sleep(0.9)
        img = self.shot()
        if purchase.find_buy_button(img) is None and not purchase.x_still_there(img, last_xy, scale):
            return True
        self.st.hold = "purchase"
        self.st.next_hold_check = time.time() + 2
        self.acc.status = "Waiting for you: Robux pop-up"
        why = "its X was clicked but it stayed open" if clicks else "its X couldn't be found"
        self.log(f"A Robux pop-up is still open ({why}). Close it yourself (never press Buy); "
                 "this account is paused until it's gone.", "error")
        self.e.notify("needs_you", "Robux pop-up stuck", "A Robux pop-up won't close. Close it yourself "
                      "(never press Buy); the account is paused until it's gone.", self.acc)
        return False

    def _click_raw(self, xy):
        self.ensure_front()
        win.move_to(*self.screen_xy(*xy))
        win.mouse_click(hold=max(CLICK_HOLD, 1.5 * game_frame(self.s)))

    def key(self, k, hold=None):
        self.ensure_front()
        win.press_key(k, key_hold(self.s) if hold is None else max(hold, key_hold(self.s)))

    def guard(self):
        if self.purchase_open():
            raise PurchasePromptOpen("")


def do_return(ctx):
    if route.close_welcome_back(ctx):
        ctx.log("Back in game after the rejoin.")
    else:
        ctx.log("Rejoined, but couldn't confirm the game's screen is clear. Check this account when "
                "you're back.", "warn")


def _builtin_close_x(ctx, still_open):
    for _ in range(3):
        img = ctx.shot()
        if not still_open(img):
            return True
        xy = builtin.close_x(img)
        if not xy:
            return False
        ctx.click(*xy)
        ctx.wait(0.8)
    return not still_open(ctx.shot())


def _open_shop(ctx, name, still_here):
    img = ctx.shot()
    if builtin.rebirth_button(img):
        ctx.log("The rebirth menu was left open, closing it first.")
        _builtin_close_x(ctx, lambda im: builtin.rebirth_button(im) is not None)
    opened = builtin.shop_open(ctx.shot())
    for attempt in range(2):
        if opened:
            break
        ctx.key("e", hold=0.3)
        end = time.time() + 10
        while time.time() < end:
            ctx.wait(0.7)
            if builtin.shop_open(ctx.shot()):
                opened = True
                break
        if not opened and still_here is not None and not still_here(ctx.shot()):
            break
    if opened:
        ctx.wait(0.8)
    return opened


SCROLL_NOTCH = 100
SCROLL_MIN_NOTCHES = 2
SCROLL_MAX_NOTCHES = 8
SCROLL_TARGET = 0.55
LAST_ROW = {"selene": ("sinister", "lucrative")}


def _ends_list(shop, item, buttons, ids, x, y, sc):
    row = LAST_ROW.get(shop)
    if not row or item not in row:
        return False
    if item == row[-1]:
        return True
    return any(b[1] > x + 40 * sc and abs(b[2] - y) < 20 * sc for b, other in zip(buttons, ids) if other != item)


def _buy_everything(ctx, shop="selene"):
    s = ctx.s
    w, h = ctx.size()
    sx0, sy0, sx1, sy1 = builtin.SHOP_AREA
    cx, cy = int((sx0 + sx1) / 2 * w), int((sy0 + sy1) / 2 * h)
    target = builtin.LIST_HEIGHT * builtin.ui_scale(ctx.shot()) * SCROLL_TARGET
    notches = SCROLL_MIN_NOTCHES
    handled, total, skipped = [], 0, 0
    robux_hits = 0
    by_choice, told = [], set()
    _sx0, sy_top = int(sx0 * w), int(sy0 * h)
    for _pass in range(2):
        missed = False
        ctx.ensure_front()
        win.move_to(*ctx.screen_xy(cx, cy))
        win.wheel_raw(1000)
        ctx.wait(1.2)
        offset, tracking = 0, True
        bottom_done = False
        for _step in range(25):
            img = ctx.shot()
            top = builtin.list_top(img)
            buttons = builtin.find_buy_buttons(img)
            ids = _shop_items(ctx, img, buttons, shop, first_view=(_step == 0))
            for (kind, x, y, clickx, sc), item in zip(buttons, ids):
                if total >= 150:
                    break
                list_y = y + offset
                tol = max(8, 25 * sc)
                if tracking and any(k == kind and abs(hx - x) < tol and abs(hy - list_y) < tol
                                    for k, hx, hy in handled):
                    continue
                if not builtin.stock_text_visible(img, y, sc, top):
                    continue
                if _ends_list(shop, item, buttons, ids, x, y, sc):
                    bottom_done = True
                if not items.wanted(s, shop, item):
                    handled.append((kind, x, list_y))
                    by_choice.append(item)
                    if item not in told:
                        told.add(item)
                        why = ("abilities are never bought" if item == "ability" else
                               "turn on 'Buy items it doesn't recognise' to buy these" if item in ("unknown", "other")
                               else "it's switched off in Settings > Shop items")
                        ctx.log(f"Skipped {items.label(shop, item)} ({why}).")
                    continue
                now_img = ctx.shot()
                if not builtin.still_there(now_img, kind, x, y, sc):
                    missed = True
                    continue
                status, left = builtin.stock_status(now_img, x, y, sc)
                if status == "out":
                    skipped += 1
                    handled.append((kind, x, list_y))
                    continue
                try:
                    total += _buy_item(ctx, kind, x, y, clickx, sc, left)
                except PurchasePromptOpen:
                    robux_hits += 1
                    if not ctx.dismiss_purchase():
                        return total, skipped, True
                    handled.append((kind, x, list_y))
                    if robux_hits >= 3:
                        ctx.log("Three Robux pop-ups in this shop visit (closed without buying). Stopping this visit.",
                                "warn")
                        _builtin_close_x(ctx, builtin.shop_open)
                        return total, skipped, True
                    ctx.log("A shop click opened a Robux pop-up. Closed it without buying; carrying on with the "
                            "next item.", "warn")
                    continue
                handled.append((kind, x, list_y))
            if bottom_done:
                break
            before_img = ctx.shot()
            before = builtin.shop_view(before_img)
            before_list = builtin.list_view(before_img)
            ctx.ensure_front()
            win.move_to(*ctx.screen_xy(cx, cy))
            win.wheel_raw(-SCROLL_NOTCH * notches, chunk=SCROLL_NOTCH)
            ctx.wait(0.8)
            after_img = ctx.shot()
            after = builtin.shop_view(after_img)
            if before.shape == after.shape and float(np.abs(after - before).mean()) < 3:
                break
            shift, sure = builtin.list_shift(before_list, builtin.list_view(after_img))
            if sure:
                offset += shift
                if shift > 0:
                    per = shift / notches
                    notches = int(max(SCROLL_MIN_NOTCHES, min(SCROLL_MAX_NOTCHES, notches * 2, target // per)))
            else:
                tracking = False
                notches = SCROLL_MIN_NOTCHES
        if not missed:
            break
    return total, skipped, False


def _shop_items(ctx, img, buttons, shop, first_view):
    ids = items.identify(img, buttons, shop)
    names = [n for n, r, f in ids]
    if shop != "selene":
        return names
    slot = items.selene_character_slot(img, buttons, ids) if first_view else None
    luck = next((r for n, r, f in ids if n == "luck3" and r is not None), None)
    for i, (n, rect, f) in enumerate(ids):
        if n != "other" or rect is None:
            continue
        if slot == "character" and luck and rect[2] < luck[0] and abs(rect[3] - luck[3]) < 40 * buttons[i][4]:
            names[i] = "character"
        elif slot == "unknown" and first_view and i == 0:
            names[i] = "character"
            ctx.log("Selene: couldn't find Luck Lvl 3 at the top of her list, so the first slot is treated "
                    "as the character.", "warn")
    return names


CLICK_CAP = 10


def _buy_item(ctx, kind, x, y, clickx, sc, left):
    if left is not None:
        bought = 0
        for _round in range(2):
            todo = min(CLICK_CAP - bought, left)
            for i in range(todo):
                ctx.click(clickx, y)
                bought += 1
                if i < todo - 1:
                    ctx.wait(0.15)
                    if not builtin.still_there(ctx.shot(), kind, x, y, sc):
                        return bought
            if bought >= CLICK_CAP:
                return bought
            ctx.wait(0.5)
            img = ctx.shot()
            if not builtin.still_there(img, kind, x, y, sc):
                return bought
            status, left = builtin.stock_status(img, x, y, sc)
            if status == "out" or not left:
                return bought
        return bought
    bought = 0
    for _ in range(CLICK_CAP):
        ctx.click(clickx, y)
        bought += 1
        ctx.wait(0.25)
        chk = ctx.shot()
        if not builtin.still_there(chk, kind, x, y, sc):
            break
        if builtin.stock_status(chk, x, y, sc)[0] == "out":
            break
    return bought


def wait_drawn(ctx, timeout=None):
    timeout = float(ctx.s.get("focus_settle_s", 10)) if timeout is None else timeout
    end = time.time() + timeout
    while True:
        img = ctx.shot()
        if builtin.shops_button(img) or builtin.shop_open(img) or purchase.is_open(img):
            return True
        if time.time() >= end:
            return False
        ctx.wait(0.5)


def do_selene_turn(ctx):
    end = time.time() + float(ctx.s.get("selene_turn_wait_s", 8))
    while not builtin.selene_prompt(ctx.shot()):
        if builtin.shop_open(ctx.shot()):
            break
        if time.time() >= end:
            ctx.log("Selene round: her prompt isn't showing on this account (not standing at her spot?). "
                    "Skipped.", "warn")
            return False
        ctx.wait(0.7)
    return do_selene_builtin(ctx)


def do_selene_builtin(ctx):
    ctx.log("Selene is here. Opening her shop.")
    if not _open_shop(ctx, "Selene", builtin.selene_prompt):
        ctx.log("Selene's shop didn't open. Will look again in a minute.", "warn")
        return False
    total, skipped, early = _buy_everything(ctx, "selene")
    if not early and not _builtin_close_x(ctx, builtin.shop_open):
        ctx.log("Couldn't confirm Selene's shop closed.", "warn")
    ctx.log(f"Selene: {total} click(s) on cash/gem buttons, {skipped} item(s) skipped as out of stock/owned.")
    return True


def do_boost_builtin(ctx):
    img = ctx.shot()
    if builtin.selene_prompt(img):
        ctx.log("Selene is standing here, so E would open her shop instead. Skipped this boost restock.", "warn")
        return
    if not builtin.shop_open(img):
        seen = builtin.boost_prompt(img)
        end = time.time() + 3
        while not seen and time.time() < end:
            ctx.wait(0.5)
            seen = builtin.boost_prompt(ctx.shot())
        if not seen:
            st = ctx.st
            st.boost_miss += 1
            if st.boost_miss >= 3:
                st.next_boost = time.time() + 1800
                if st.boost_miss == 3:
                    ctx.log("The boosts stand wasn't reachable 3 restocks in a row. Move this account right next "
                            "to it. Only trying again every 30 min (or turn Boost shop off for this account).",
                            "warn")
            else:
                ctx.log("The 'Boosts Store / Talk' prompt isn't showing, so E wouldn't open the shop. Move this "
                        "account right next to the boosts stand. Skipped this restock.", "warn")
            return
    ctx.st.boost_miss = 0
    ctx.log("Boost restock: 'Boosts Store' prompt found, opening the shop.")
    if not _open_shop(ctx, "Boost", builtin.boost_prompt):
        ctx.log("The boost shop didn't open after pressing E. Is this account standing right at the boosts "
                "stand (close enough for its E prompt)? Skipped this restock.", "warn")
        return
    total, skipped, early = _buy_everything(ctx, "boost")
    if not early and not _builtin_close_x(ctx, builtin.shop_open):
        ctx.log("Couldn't confirm the boost shop closed.", "warn")
    ctx.log(f"Boost shop: {total} click(s) on cash/gem buttons, {skipped} item(s) skipped as out of stock/owned.")


def do_rebirth_builtin(ctx):
    img = ctx.shot()
    if ctx.purchase_open(img):
        if not ctx.dismiss_purchase():
            raise Abort("")
        img = ctx.shot()
    btn = builtin.rebirth_button(img)
    if not btn:
        if builtin.shop_open(img):
            ctx.log("Selene's shop was left open, closing it first.")
            if not _builtin_close_x(ctx, builtin.shop_open):
                ctx.log("Couldn't close the shop. Skipping this rebirth.", "warn")
                return
            img = ctx.shot()
        side = builtin.side_rebirth_button(img)
        for _ in range(3):
            if side:
                break
            ctx.wait(1.0)
            img = ctx.shot()
            side = builtin.side_rebirth_button(img)
        if not side:
            ctx.log("Couldn't find the REBIRTH button on the left (looked 4 times). Skipped this time.", "warn")
            return
        ctx.click(*side)
        end = time.time() + 5
        while time.time() < end:
            ctx.wait(0.4)
            btn = builtin.rebirth_button(ctx.shot())
            if btn:
                break
    if not btn:
        ctx.log("The rebirth menu didn't open. Skipped this time.", "warn")
        return
    line_seen = False
    end = time.time() + float(ctx.s.get("sacrifice_line_wait_s", 6))
    while True:
        img = ctx.shot()
        btn = builtin.rebirth_button(img) or btn
        if builtin.sacrifice_line_present(img, btn):
            line_seen = True
            break
        if time.time() >= end:
            break
        ctx.wait(0.5)
    if not line_seen:
        ctx.log("The 'Reach 250 Rebirths to unlock SACRIFICE!' line didn't show: sacrifice may be unlocked. "
                "Skipped this rebirth - if you're at 250, do it yourself. Will check again next time.", "warn")
        _builtin_close_x(ctx, lambda im: builtin.rebirth_button(im) is not None)
        return
    ctx.click(btn[0], btn[1])
    end = time.time() + float(ctx.s.get("rebirth_popup_wait_s", 6))
    while time.time() < end and not ctx.purchase_open():
        ctx.wait(0.3)
    if ctx.purchase_open():
        if not ctx.dismiss_purchase():
            raise Abort("")
        ctx.log(f"Not enough cash to rebirth yet (closed the 'Skip Rebirth' Robux pop-up). "
                f"Trying again in {ctx.s['rebirth_every_min']} min.")
    else:
        ctx.log("Rebirth clicked and no 'not enough cash' pop-up appeared, so it should have gone through.")
    ctx.wait(1.5)
    if builtin.sacrifice_popup(ctx.shot()):
        ctx.e._hold_for_sacrifice(ctx.acc, ctx.st)
        raise Abort("")
    _builtin_close_x(ctx, lambda im: builtin.rebirth_button(im) is not None)


def _something_open(ctx, img):
    if ctx.purchase_open(img):
        return "a Robux pop-up"
    if builtin.sacrifice_popup(img):
        return "the SACRIFICE pop-up"
    if builtin.rebirth_button(img):
        return "the rebirth menu"
    if builtin.close_x(img) or builtin.find_buy_buttons(img):
        return "a shop"
    return None


def do_anti_afk(ctx):
    w, h = ctx.size()
    img = ctx.shot()
    busy = _something_open(ctx, img)
    if busy:
        ctx.log(f"Anti-AFK: {busy} is open, so no clicking - nudged the camera keys instead.")
        ctx.key("right", hold=0.12)
        ctx.wait(0.1)
        ctx.key("left", hold=0.12)
        return
    x = int(w * 0.5 + random.randint(-int(w * 0.04), int(w * 0.04)))
    y = int(h * 0.45 + random.randint(-int(h * 0.04), int(h * 0.04)))
    ctx.ensure_front()
    sx, sy = ctx.screen_xy(x, y)
    win.move_to(sx, sy)
    for _ in range(random.randint(6, 10)):
        win.move_to(sx + random.randint(-12, 12), sy + random.randint(-8, 8))
        time.sleep(random.uniform(0.04, 0.09))
    n = max(1, int(ctx.s.get("anti_afk_clicks", 10)))
    for _ in range(n):
        ctx.click(x + random.randint(-6, 6), y + random.randint(-6, 6))
        ctx.wait(random.uniform(0.12, 0.3))
    ctx.log(f"Anti-AFK: wiggled the mouse and clicked {n} times.")


def game_frame(s):
    try:
        fps = float(s.get("game_fps", 60) or 60)
    except (TypeError, ValueError):
        fps = 60.0
    return 1.0 / min(240.0, max(1.0, fps))


def key_hold(s):
    return max(KEY_HOLD, 1.5 * game_frame(s))


def char_slots(s):
    got = hallows.parse_slots(s.get("char_slots") or "")
    if got:
        return got
    first, last = int(s.get("first_slot", 2)), min(10, int(s.get("last_slot", 4)))
    return list(range(first, last + 1))


def verify_slot_key(ctx, key, slot, want_held):
    fr = game_frame(ctx.s)
    want = bool(want_held)
    plan = [(None, max(2.6, 13 * fr)), (None, max(3.0, 15 * fr)),
            (max(0.8, 5 * fr), max(3.5, 17 * fr)), (max(1.2, 5 * fr), max(4.0, 20 * fr))]
    if want:
        plan = plan[:3]
    for attempt, (hold, wait) in enumerate(plan):
        if attempt:
            if hallows.slot_held(ctx.shot(), slot)[0] == want:
                return True
            what = "held" if want else "put away"
            if hold:
                ctx.log(f"Slot {slot} still isn't {what}. Pressing it again and holding the key for {hold:.1f}s.",
                        "warn")
            else:
                ctx.log(f"Slot {slot} still isn't {what} after {plan[attempt - 1][1]:.1f}s. Pressing it once more.",
                        "warn")
            ctx.key(key, hold=hold)
        end = time.time() + wait
        good = 0
        while time.time() < end:
            ctx.wait(max(0.12, fr))
            if hallows.slot_held(ctx.shot(), slot)[0] == want:
                good += 1
                if good >= 2:
                    return True
            else:
                good = 0
    ctx.log(f"Slot {slot} still isn't {'held' if want else 'put away'} after {len(plan)} presses. "
            "Check that window.", "warn")
    return False


def do_ability(ctx):
    s, st = ctx.s, ctx.st
    every = max(3.0, float(s.get("ability_every_s", 10) or 10))
    key = str(s.get("ability_key", "v") or "v").strip().lower()
    pos = s.get("ability_pos")
    only_ready = bool(s.get("ability_only_ready", True))
    img = ctx.shot()
    busy = _something_open(ctx, img)
    if busy:
        st.next_ability = time.time() + 3
        return
    if only_ready and ability.valid_pos(pos):
        if not ability.is_ready(img, pos):
            st.next_ability = time.time() + every
            return
        ctx.wait(0.35)
        if not ability.is_ready(ctx.shot(), pos):
            st.next_ability = time.time() + every
            return
    elif only_ready and not st.ability_warned:
        st.ability_warned = True
        ctx.log("Auto ability: the ability button isn't marked yet (Settings > Auto ability > Mark ability button), "
                "so the key is pressed on the timer instead.", "warn")
    try:
        ctx.key(key)
    except ValueError:
        ctx.log(f"Auto ability: '{key}' isn't a key this app can press. Change it in Settings > Auto ability.", "error")
        st.disabled.add("ability")
        return
    st.ability_presses += 1
    st.next_ability = time.time() + every
    if st.ability_presses == 1 or st.ability_presses % 25 == 0:
        ctx.log(f"Auto ability: pressed {key.upper()} ({st.ability_presses} time(s) so far).")
