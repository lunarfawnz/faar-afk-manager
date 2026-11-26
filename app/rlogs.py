import calendar
import glob
import os
import re
import threading
import time

JOIN_MARKS = ("! Joining game", "[FLog::Network] serverId:", "Report game_join_loadtime:")
DISC_MARKS = ("Time to disconnect replication data", "Disconnection Notification", "Lost connection with reason")
LEAVE_MARKS = ("leaveUGCGameInternal",)
TELE_MARKS = ("initiateTeleport",)
USER_RE = re.compile(r"userid:\s*(\d+)", re.I)
CODE_RE = re.compile(r"(?:reason|error code)\s*:?\s*(\d{3})", re.I)
TIME_RE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)")
MAX_AGE = 12 * 3600
READ_CAP = 4 * 1024 * 1024


def log_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox", "logs")


def _stamp(line):
    m = TIME_RE.match(line)
    if not m:
        return None
    try:
        return float(calendar.timegm(tuple(int(g) for g in m.groups()) + (0, 0, 0)))
    except Exception:
        return None


class _File:
    __slots__ = ("pos", "user", "state", "since", "code", "last")

    def __init__(self):
        self.pos, self.user, self.state, self.since, self.code, self.last = 0, None, "", 0.0, "", 0.0


class Watcher:
    def __init__(self, folder=None):
        self.folder = folder or log_dir()
        self.files = {}
        self.lock = threading.Lock()
        self.next_scan = 0.0

    def _feed(self, f, text, now):
        for line in text.splitlines():
            ts = _stamp(line) or now
            if f.user is None:
                m = USER_RE.search(line)
                if m:
                    f.user = int(m.group(1))
            if any(k in line for k in JOIN_MARKS):
                if f.state != "in":
                    f.state, f.since, f.code = "in", ts, ""
            elif any(k in line for k in LEAVE_MARKS):
                f.state, f.since = "left", ts
            elif any(k in line for k in TELE_MARKS):
                f.state, f.since = "teleport", ts
            elif any(k in line for k in DISC_MARKS):
                m = CODE_RE.search(line)
                if m:
                    f.code = m.group(1)
                if f.state in ("in", "teleport"):
                    f.state, f.since = "disc", ts
            f.last = max(f.last, ts)

    def poll(self):
        now = time.time()
        with self.lock:
            if now < self.next_scan:
                return
            self.next_scan = now + 3
            try:
                paths = glob.glob(os.path.join(self.folder, "*.log"))
            except Exception:
                return
            for p in paths:
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if now - st.st_mtime > MAX_AGE:
                    self.files.pop(p, None)
                    continue
                f = self.files.get(p)
                if f is None:
                    f = self.files[p] = _File()
                    f.last = st.st_mtime
                if st.st_size < f.pos:
                    f.pos = 0
                if st.st_size == f.pos:
                    continue
                try:
                    with open(p, "rb") as fh:
                        start = max(f.pos, st.st_size - READ_CAP) if f.pos == 0 else f.pos
                        fh.seek(start)
                        data = fh.read(st.st_size - start)
                except OSError:
                    continue
                cut = data.rfind(b"\n")
                if cut < 0:
                    continue
                f.pos = start + cut + 1
                self._feed(f, data[:cut + 1].decode("utf-8", "replace"), now)
            for p in list(self.files):
                if p not in paths:
                    self.files.pop(p, None)

    def latest(self, user_id):
        self.poll()
        with self.lock:
            mine = [f for f in self.files.values() if f.user == int(user_id)]
            if not mine:
                return None
            f = max(mine, key=lambda x: x.last)
            return f.state, f.since, f.code

    def disconnected(self, user_id, grace=30.0):
        got = self.latest(user_id)
        if not got:
            return ""
        state, since, code = got
        if state != "disc" or time.time() - since < grace:
            return ""
        return f"error {code}" if code else "disconnected"
