import math
import random
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import win, purchase, builtin, hallows, route, roblox


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
    pending_return: bool = False


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
        self.input_lock = win.InputLock()
        self.relaunch = None
        self.selene_queue = []
        self.selene_busy = None
        self.selene_busy_since = 0.0

    @property
    def status(self):
        if not self._thread or not self._thread.is_alive():
            return "Stopped"
        return "Paused" if self._paused.is_set() else "Running"

    def start(self):
        if self._thread and self._thread.is_alive():
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

    def _hotkey_loop(self):
        was8 = was9 = False
        while True:
            k8, k9 = win.key_down_now(win.VK_F8), win.key_down_now(win.VK_F9)
            if k8 and not was8:
                self.pause()
            if k9 and not was9 and self.status != "Stopped":
                threading.Thread(target=self.stop, daemon=True).start()
            was8, was9 = k8, k9
            time.sleep(0.05)

    def interrupted(self):
        return self._stop.is_set() or self._paused.is_set()

    def _loop(self):
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.2)
                continue
            s = self.get_settings()
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
                    acc.hwnd, acc.pid, acc.status = 0, 0, "Offline (closed)"
                    self.log("Window closed.", acc)
                    continue
                st = self.states.setdefault(acc.user_id, self._new_state(s))
                try:
                    jobs = self._due_jobs(acc, st, s)
                    if jobs:
                        self._run_jobs(acc, st, s, jobs)
                except Abort:
                    pass
                except Exception as e:
                    self.log(f"Error: {e}", acc, "error")
                    time.sleep(1)
            time.sleep(0.25)

    def _new_state(self, s):
        now = time.time()
        return AccState(next_rebirth=now + 20, next_boost=self._next_boost(now, s),
                        next_selene=now + 2, next_event=now + 1, cur_slot=int(s["first_slot"]))

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

    def _start_rejoin(self, acc, st, s, why):
        st.hold = "rejoin"
        acc.status = f"Rejoining ({why})"
        self.log(f"Disconnected ({why}{', the server was shut down' if why == 'error 256' else ''}). "
                 "Rejoining.", acc, "warn")
        threading.Thread(target=self._rejoin, args=(acc, st, s), daemon=True).start()

    def _rejoin(self, acc, st, s):
        try:
            roblox.close(acc)
            acc.hwnd, acc.pid = 0, 0
            for _ in range(50):
                if self._stop.is_set():
                    return
                time.sleep(0.1)
            if not self.relaunch:
                self.log("Can't rejoin from here (no launcher).", acc, "error")
                return
            for attempt in range(1, 4):
                if self._stop.is_set():
                    return
                if self.relaunch(acc):
                    break
                self.log(f"Rejoin attempt {attempt} failed." + (" Trying again in 60s." if attempt < 3 else ""),
                         acc, "warn")
                end = time.time() + 60
                while attempt < 3 and time.time() < end and not self._stop.is_set():
                    time.sleep(0.5)
            else:
                acc.status = "Offline (rejoin failed)"
                self.log("Couldn't rejoin after 3 tries. Launch it yourself when you're back.", acc, "error")
                return
            acc.status = "Loading game..."
            if not route.wait_loaded(acc.hwnd, 150, self._stop.is_set):
                self.log("Rejoined, but the game didn't finish loading in time. Will check again later.",
                         acc, "warn")
            new = self._new_state(s)
            new.pending_return = True
            self.states[acc.user_id] = new
            acc.status = "In game"
        except Exception as e:
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

        if st.hold == "rejoin":
            return []
        if st.pending_return:
            st.pending_return = False
            return [("return",)]
        if (f.get("rejoin", True) and float(s.get("rejoin_check_s", 20)) > 0
                and now >= st.next_disc_check):
            st.next_disc_check = now + max(5.0, float(s.get("rejoin_check_s", 20)))
            img = shot()
            why = builtin.disconnected(img) if img is not None else ""
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

        if f.get("anti_afk") and not jobs and now - st.last_input >= float(s["anti_afk_min"]) * 60:
            jobs.append(("anti_afk",))
        return jobs

    def _hallows_decide(self, acc, st, s, img):
        first, last = int(s["first_slot"]), min(10, int(s["last_slot"]))
        reading, why = hallows.hallows_event(img)
        if reading != st.event_on:
            st.ev_votes += 1
            if st.ev_votes >= 2:
                st.event_on, st.ev_votes = reading, 0
                if reading:
                    self.log(f"Hallow's Eve started ({why}).", acc)
                    if not st.done and not first <= st.cur_slot <= last:
                        st.cur_slot = first
                else:
                    self.log("Hallow's Eve ended.", acc)
        else:
            st.ev_votes = 0

        if st.event_on and not st.done:
            held, _ = hallows.slot_held(img, st.cur_slot)
            if not held:
                return self._press_for(acc, st, st.cur_slot, True)
            st.intent_count = 0
            if s.get("mutation_cycle", True) and time.time() >= st.next_mut_check:
                st.next_mut_check = time.time() + 5
                word = str(s.get("mutation_word", "dracula") or "dracula")
                st.drac_votes = st.drac_votes + 1 if hallows.mutation_seen(img, st.cur_slot, word) else 0
                if st.drac_votes >= 2:
                    st.drac_votes = 0
                    return [("advance",)]
            return []

        for slot in range(first, last + 1):
            if hallows.slot_held(img, slot)[0]:
                return self._press_for(acc, st, slot, False)
        st.intent_count = 0
        return []

    def _press_for(self, acc, st, slot, want_held):
        intent = (slot, want_held)
        st.intent_count = st.intent_count + 1 if st.intent == intent else 1
        st.intent = intent
        if st.intent_count > 3:
            self.log(f"Slot {slot} isn't reacting after 3 presses (is the hotbar full, and is something in "
                     f"that slot?). Waiting 60s.", acc, "warn")
            st.backoff_until = time.time() + 60
            st.intent_count = 0
            return []
        return [("key", win.slot_key(slot), f"{'Holding' if want_held else 'Putting away'} slot {slot}")]

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
                elif kind == "advance":
                    do_hallows_advance(ctx)
                elif kind == "return":
                    do_return(ctx)
                elif kind == "anti_afk":
                    do_anti_afk(ctx)
                elif kind == "rebirth":
                    do_rebirth_builtin(ctx)
                elif kind == "boost":
                    do_boost_builtin(ctx)
                elif kind == "selene_turn":
                    try:
                        ok = do_selene_turn(ctx)
                        st.selene_until = time.time() + (float(s["selene_cooldown_min"]) * 60 if ok else 60)
                    finally:
                        self._selene_next(acc)
                elif kind == "selene":
                    try:
                        ok = do_selene_builtin(ctx)
                    finally:
                        if self.selene_busy == acc.user_id:
                            self.selene_busy = None
                    st.selene_until = time.time() + (float(s["selene_cooldown_min"]) * 60 if ok else 60)
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
            win.mouse_click()
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
        return False

    def _click_raw(self, xy):
        self.ensure_front()
        win.move_to(*self.screen_xy(*xy))
        win.mouse_click()

    def key(self, k, hold=0.06):
        self.ensure_front()
        win.press_key(k, hold)

    def guard(self):
        if self.purchase_open():
            raise PurchasePromptOpen("")


def do_return(ctx):
    if route.close_welcome_back(ctx):
        ctx.log("Back in game after the rejoin.")
    else:
        ctx.log("Rejoined, but couldn't confirm the game's screen is clear. Check this account when "
                "you're back.", "warn")


def do_hallows_advance(ctx):
    st, s = ctx.st, ctx.s
    word = str(s.get("mutation_word", "dracula") or "dracula")
    cur, nxt = st.cur_slot, st.cur_slot + 1
    last = min(10, int(s["last_slot"]))
    img = ctx.shot()
    if nxt > last or hallows.slot_is_potion(img, nxt):
        why = "that was the last character slot" if nxt > last else f"slot {nxt} is a potion"
        st.done = True
        ctx.log(f"Slot {cur} has {word.title()}, and {why}: all characters done, putting slot {cur} away. "
                "(Restart automation to run through them again.)")
        if hallows.slot_held(img, cur)[0]:
            ctx.key(win.slot_key(cur))
        return
    ctx.log(f"Slot {cur} has {word.title()}. Moving on to slot {nxt}.")
    ctx.key(win.slot_key(nxt))
    ctx.wait(1.0)
    img = ctx.shot()
    if hallows.slot_held(img, nxt)[0]:
        st.cur_slot = nxt
        return
    ctx.log(f"Couldn't hold slot {nxt} (empty?). Stopping here.", "warn")
    st.done = True
    if hallows.slot_held(img, cur)[0]:
        ctx.key(win.slot_key(cur))


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


def _buy_everything(ctx):
    s = ctx.s
    w, h = ctx.size()
    sx0, sy0, sx1, sy1 = builtin.SHOP_AREA
    cx, cy = int((sx0 + sx1) / 2 * w), int((sy0 + sy1) / 2 * h)
    step_units = max(20, int(60 * h / builtin.REF_H))
    max_clicks = max(1, int(s["buy_clicks"]))
    handled, total, skipped = [], 0, 0
    _sx0, sy_top = int(sx0 * w), int(sy0 * h)
    for _pass in range(2):
        missed = False
        ctx.ensure_front()
        win.move_to(*ctx.screen_xy(cx, cy))
        win.wheel_raw(1000)
        ctx.wait(1.2)
        offset, tracking = 0, True
        for _step in range(15):
            img = ctx.shot()
            top = builtin.list_top(img)
            for kind, x, y, clickx, sc in builtin.find_buy_buttons(img):
                if total >= 150:
                    break
                list_y = y + offset
                tol = max(8, 25 * sc)
                if tracking and any(k == kind and abs(hx - x) < tol and abs(hy - list_y) < tol
                                    for k, hx, hy in handled):
                    continue
                if not builtin.stock_text_visible(img, y, sc, top):
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
                todo = max_clicks if left is None else min(max_clicks, left)
                done = 0
                try:
                    for _ in range(todo):
                        ctx.click(clickx, y)
                        done += 1
                        total += 1
                        ctx.wait(0.25)
                        if done >= todo:
                            break
                        chk = ctx.shot()
                        if not builtin.still_there(chk, kind, x, y, sc):
                            break
                        if builtin.stock_status(chk, x, y, sc)[0] == "out":
                            break
                except PurchasePromptOpen:
                    ctx.dismiss_purchase()
                    ctx.log("A shop click opened a Robux pop-up. Closed it without buying; stopping this visit.",
                            "warn")
                    _builtin_close_x(ctx, builtin.shop_open)
                    return total, skipped, True
                handled.append((kind, x, list_y))
            before_img = ctx.shot()
            before = builtin.shop_view(before_img)
            before_list = builtin.list_view(before_img)
            ctx.ensure_front()
            win.move_to(*ctx.screen_xy(cx, cy))
            win.wheel_raw(-step_units)
            ctx.wait(1.0)
            after_img = ctx.shot()
            after = builtin.shop_view(after_img)
            if before.shape == after.shape and float(np.abs(after - before).mean()) < 3:
                break
            shift, sure = builtin.list_shift(before_list, builtin.list_view(after_img))
            if sure:
                offset += shift
            else:
                tracking = False
        if not missed:
            break
    return total, skipped, False


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
    total, skipped, early = _buy_everything(ctx)
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
            ctx.log("The 'Boosts Store / Talk' prompt isn't showing, so E wouldn't open the shop. Move this "
                    "account right next to the boosts stand. Skipped this restock.", "warn")
            return
    ctx.log("Boost restock: 'Boosts Store' prompt found, opening the shop.")
    if not _open_shop(ctx, "Boost", builtin.boost_prompt):
        ctx.log("The boost shop didn't open after pressing E. Is this account standing right at the boosts "
                "stand (close enough for its E prompt)? Skipped this restock.", "warn")
        return
    total, skipped, early = _buy_everything(ctx)
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
        if not side:
            ctx.log("Couldn't find the REBIRTH button on the left. Skipped this time.", "warn")
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
