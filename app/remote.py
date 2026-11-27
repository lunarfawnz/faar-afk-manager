import hashlib
import hmac
import http.cookies
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import storage

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    WEB_DIR = os.path.join(sys._MEIPASS, "app", "web")
CFG_FILE = os.path.join(storage.DATA_DIR, "remote.json")
COOKIE = "faar_s"
SESSION_DAYS = 30
KINDS = {
    "dracula": "Dracula got",
    "needs_you": "Needs you",
    "disconnects": "Disconnects and rejoins",
    "stopped": "Automation stopped or app crashed",
    "rare_god": "God catches",
    "rare_omniscient": "Omniscient catches",
    "rare_apex": "Apex catches",
}
CURRENT = None


def _pbkdf(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def _sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def tailscale_exe():
    found = shutil.which("tailscale")
    if found:
        return found
    for p in (r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
        if os.path.exists(p):
            return p
    return None


def _run(args, timeout=25):
    kw = {"capture_output": True, "text": True, "timeout": timeout}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000
    return subprocess.run(args, **kw)


class Remote:
    def __init__(self, app):
        global CURRENT
        CURRENT = self
        self.app = app
        self.lock = threading.RLock()
        self.cfg = self._load()
        self.server = None
        self.thread = None
        self.fails = []
        self.locked_until = 0.0
        self._icons = {}

    def _load(self):
        try:
            with open(CFG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except Exception:
            cfg = {}
        cfg.setdefault("subs", [])
        cfg.setdefault("sessions", {})
        if not cfg.get("vapid"):
            from . import webpush
            cfg["vapid"] = webpush.new_vapid_key()
        return cfg

    def _save(self):
        with self.lock:
            try:
                tmp = CFG_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.cfg, f, indent=1)
                os.replace(tmp, CFG_FILE)
            except Exception:
                pass

    @property
    def s(self):
        return self.app.settings

    def has_pin(self):
        return bool(self.cfg.get("pin_hash"))

    def set_pin(self, pin):
        salt = secrets.token_hex(16)
        with self.lock:
            self.cfg["pin_salt"], self.cfg["pin_hash"] = salt, _pbkdf(pin, salt)
            self.cfg["sessions"] = {}
        self._save()

    def sign_out_all(self):
        with self.lock:
            self.cfg["sessions"] = {}
        self._save()

    def check_pin(self, pin):
        now = time.time()
        if now < self.locked_until:
            return "locked"
        ok = self.has_pin() and hmac.compare_digest(_pbkdf(str(pin), self.cfg["pin_salt"]), self.cfg["pin_hash"])
        if ok:
            self.fails = []
            return "ok"
        self.fails = [t for t in self.fails if now - t < 600] + [now]
        if len(self.fails) >= 5:
            self.locked_until = now + 300
            self.fails = []
            self.app.log("Phone remote: 5 wrong PINs, logins are locked for 5 minutes.", level="warn")
            self.notify("needs_you", "Wrong PIN 5 times", "Someone typed a wrong PIN 5 times. Logins are locked for "
                        "5 minutes.")
        return "bad"

    def new_session(self):
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = time.time()
            self.cfg["sessions"] = {k: v for k, v in self.cfg["sessions"].items() if v > now}
            self.cfg["sessions"][_sha(token)] = now + SESSION_DAYS * 86400
        self._save()
        return token

    def valid(self, token):
        if not token:
            return False
        with self.lock:
            exp = self.cfg["sessions"].get(_sha(token))
            return bool(exp and exp > time.time())

    def end_session(self, token):
        with self.lock:
            self.cfg["sessions"].pop(_sha(token or ""), None)
        self._save()

    def running(self):
        return self.server is not None

    def start(self):
        if self.server:
            return True
        port = int(self.s.get("remote_port", 8787) or 8787)
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), _handler(self))
        except OSError as e:
            self.app.log(f"Phone remote couldn't start on port {port}: {e}", level="error")
            return False
        srv.daemon_threads = True
        self.server = srv
        self.thread = threading.Thread(target=srv.serve_forever, daemon=True)
        self.thread.start()
        self.app.log(f"Phone remote is on (local port {port}).")
        return True

    def stop(self):
        srv, self.server = self.server, None
        if srv:
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()
            self.app.log("Phone remote is off.")

    def tailscale_url(self):
        exe = tailscale_exe()
        if not exe:
            return None, "Tailscale isn't installed on this PC."
        try:
            out = _run([exe, "status", "--json"])
            data = json.loads(out.stdout or "{}")
        except Exception as e:
            return None, f"Couldn't ask Tailscale for this PC's name: {e}"
        if data.get("BackendState") != "Running":
            return None, "Tailscale is installed but not signed in / connected."
        name = ((data.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if not name:
            return None, "Tailscale didn't report a name for this PC (is MagicDNS on?)."
        return f"https://{name}", ""

    def setup_tailscale(self, status=lambda msg: None):
        exe = tailscale_exe()
        if not exe:
            return False, "Tailscale isn't installed on this PC. Install it from tailscale.com, sign in, then try again."
        url, why = self.tailscale_url()
        if not url:
            return False, why
        port = int(self.s.get("remote_port", 8787) or 8787)
        ok, text = self._serve(exe, [exe, "serve", "--bg", str(port)], status)
        if not ok and re.search(r"unknown flag|flag provided but not defined|invalid argument|usage:", text, re.I):
            ok, text = self._serve(exe, [exe, "serve", "https", "/", f"http://127.0.0.1:{port}"], status)
        if not ok:
            return False, "Tailscale said:\n" + (text.strip()[-600:] or "nothing (it stopped without saying why).")
        url, why = self.tailscale_url()
        return bool(url), (url or why)

    def _serve(self, exe, args, status):
        kw = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
              "text": True, "bufsize": 1}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000
        try:
            proc = subprocess.Popen(args, **kw)
        except Exception as e:
            return False, f"Couldn't run Tailscale: {e}"
        lines, opened = [], set()

        def reader():
            for line in proc.stdout:
                lines.append(line)
                for link in re.findall(r"https://login\.tailscale\.com/\S+", line):
                    link = link.rstrip(".,)")
                    if link not in opened:
                        opened.add(link)
                        try:
                            webbrowser.open(link)
                        except Exception:
                            pass
                        status("Tailscale needs you to allow HTTPS for your network. A page opened in your "
                               f"browser (if not, open this link): {link}  Allow it there; this finishes by itself.")
        th = threading.Thread(target=reader, daemon=True)
        th.start()
        end = time.time() + 300
        while proc.poll() is None and time.time() < end:
            time.sleep(0.3)
        if proc.poll() is None:
            proc.kill()
            th.join(2)
            return False, "".join(lines) + "\n(Timed out after 5 minutes waiting for Tailscale.)"
        th.join(2)
        return proc.returncode == 0, "".join(lines)

    def notify(self, kind, title, body, acc=None):
        if not self.s.get(f"notify_{kind}", True):
            return
        subs = list(self.cfg.get("subs", []))
        if not subs:
            return
        who = f"{acc.username}: " if acc is not None else ""
        data = {"title": title, "body": who + body, "tag": f"{kind}-{getattr(acc, 'user_id', '')}",
                "kind": kind, "t": int(time.time())}
        threading.Thread(target=self._send_all, args=(subs, data), daemon=True).start()

    def _send_all(self, subs, data):
        from . import webpush
        dead = []
        for sub in subs:
            try:
                code = webpush.send(sub, data, self.cfg["vapid"])
            except Exception as e:
                self.app.log(f"Phone remote: couldn't send a notification ({e}).", level="warn")
                continue
            if code in (404, 410):
                dead.append(sub["endpoint"])
            elif code >= 400:
                self.app.log(f"Phone remote: the push service refused a notification ({code}).", level="warn")
        if dead:
            with self.lock:
                self.cfg["subs"] = [x for x in self.cfg["subs"] if x["endpoint"] not in dead]
            self._save()

    def add_sub(self, sub, name):
        if not isinstance(sub, dict) or not str(sub.get("endpoint", "")).startswith("https://"):
            raise ValueError("bad subscription")
        keys = sub.get("keys") or {}
        if not keys.get("p256dh") or not keys.get("auth"):
            raise ValueError("bad subscription")
        clean = {"endpoint": sub["endpoint"], "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
                 "name": str(name or "Phone")[:40], "added": time.strftime("%Y-%m-%d %H:%M")}
        with self.lock:
            self.cfg["subs"] = [x for x in self.cfg["subs"] if x["endpoint"] != clean["endpoint"]] + [clean]
        self._save()

    def remove_sub(self, endpoint):
        with self.lock:
            self.cfg["subs"] = [x for x in self.cfg["subs"] if x["endpoint"] != endpoint]
        self._save()

    def clear_subs(self):
        with self.lock:
            self.cfg["subs"] = []
        self._save()

    def icon(self, size):
        if size not in self._icons:
            from PIL import Image
            base = os.path.join(os.path.dirname(WEB_DIR), "..", "assets", "icon_256.png")
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                base = os.path.join(sys._MEIPASS, "assets", "icon_256.png")
            im = Image.open(base).convert("RGBA")
            bg = Image.new("RGBA", im.size, (14, 16, 22, 255))
            bg.alpha_composite(im)
            buf = io.BytesIO()
            bg.convert("RGB").resize((size, size), Image.LANCZOS).save(buf, "PNG")
            self._icons[size] = buf.getvalue()
        return self._icons[size]

    def state(self):
        app = self.app
        accs = []
        for a in app.accounts:
            from . import win
            alive = bool(a.hwnd) and win.is_window(a.hwnd)
            h = app.engine.hstats.get(a.user_id)
            accs.append({
                "id": a.user_id, "name": a.username, "alive": alive,
                "launching": app.is_launching(a),
                "status": a.status if (alive or a.status != "In game") else "Offline",
                "features": {k: bool(a.features.get(k, True)) for k, _ in FEATURES},
                "hallows": h,
            })
        return {
            "engine": app.engine.status,
            "accounts": accs,
            "features": FEATURES,
            "notify": {k: bool(self.s.get(f"notify_{k}", True)) for k in KINDS},
            "kinds": KINDS,
            "push_key": self._pub(),
            "phones": [{"name": x.get("name", "Phone"), "added": x.get("added", "")} for x in self.cfg["subs"]],
            "log_id": app.log_seq,
        }

    def _pub(self):
        from . import webpush
        return webpush.vapid_public(self.cfg["vapid"])


FEATURES = [("boost_shop", "Boost shop"), ("selene", "Selene"), ("rebirth", "Auto rebirth"),
            ("hallows_eve", "Hallow's Eve"), ("anti_afk", "Anti-AFK"), ("ability", "Auto ability"),
            ("rejoin", "Rejoin")]
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
}


def _handler(remote):
    class H(BaseHTTPRequestHandler):
        server_version = "FAAR"
        sys_version = ""

        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="application/json", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            if ctype.startswith("text/html"):
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
                                 "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _token(self):
            c = http.cookies.SimpleCookie()
            try:
                c.load(self.headers.get("Cookie", ""))
            except Exception:
                return ""
            return c[COOKIE].value if COOKIE in c else ""

        def _authed(self):
            return remote.valid(self._token())

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                raise ValueError("too big")
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw or b"{}")

        def do_GET(self):
            try:
                self._get()
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})

        def do_POST(self):
            try:
                self._post()
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})

        def _get(self):
            u = urllib.parse.urlsplit(self.path)
            path, q = u.path, urllib.parse.parse_qs(u.query)
            if path in STATIC:
                name, ctype = STATIC[path]
                with open(os.path.join(WEB_DIR, name), "rb") as f:
                    extra = {"Service-Worker-Allowed": "/"} if name == "sw.js" else None
                    return self._send(200, f.read(), ctype, extra)
            if path in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"):
                size = {"/icon-192.png": 192, "/icon-512.png": 512}.get(path, 180)
                return self._send(200, remote.icon(size), "image/png")
            if path == "/api/me":
                return self._send(200, {"authed": self._authed(), "has_pin": remote.has_pin()})
            if not self._authed():
                return self._send(401, {"error": "login"})
            if path == "/api/state":
                return self._send(200, remote.state())
            if path == "/api/log":
                since = int((q.get("since") or ["0"])[0] or 0)
                return self._send(200, {"lines": remote.app.log_since(since), "id": remote.app.log_seq})
            if path == "/api/shot":
                acc = remote.app.find_account(int((q.get("id") or ["0"])[0]))
                jpg = remote.app.screenshot_jpeg(acc) if acc else None
                if not jpg:
                    return self._send(404, {"error": "That account's window isn't open."})
                return self._send(200, jpg, "image/jpeg")
            return self._send(404, {"error": "not found"})

        def _post(self):
            path = urllib.parse.urlsplit(self.path).path
            if self.headers.get("X-FAAR") != "1":
                return self._send(403, {"error": "bad request"})
            data = self._body()
            if path == "/api/login":
                if not remote.has_pin():
                    return self._send(403, {"error": "Set a PIN in FAAR Manager first (Phone remote page)."})
                res = remote.check_pin(str(data.get("pin", ""))[:32])
                if res == "locked":
                    return self._send(429, {"error": "Too many wrong PINs. Try again in a few minutes."})
                if res != "ok":
                    return self._send(401, {"error": "Wrong PIN."})
                token = remote.new_session()
                cookie = (f"{COOKIE}={token}; Max-Age={SESSION_DAYS * 86400}; Path=/; HttpOnly; SameSite=Strict"
                          + ("; Secure" if self.headers.get("X-Forwarded-Proto", "") == "https"
                             or self.headers.get("Host", "").endswith(".ts.net") else ""))
                remote.app.log("Phone remote: a device signed in.")
                return self._send(200, {"ok": True}, headers={"Set-Cookie": cookie})
            if not self._authed():
                return self._send(401, {"error": "login"})
            app = remote.app
            if path == "/api/logout":
                remote.end_session(self._token())
                return self._send(200, {"ok": True}, headers={"Set-Cookie": f"{COOKIE}=; Max-Age=0; Path=/"})
            if path == "/api/engine":
                msg = app.remote_engine(str(data.get("action", "")))
                return self._send(200, {"ok": True, "msg": msg})
            if path == "/api/account":
                acc = app.find_account(int(data.get("id", 0)))
                if not acc:
                    return self._send(404, {"error": "No such account."})
                msg = app.remote_account(acc, str(data.get("action", "")))
                return self._send(200, {"ok": True, "msg": msg})
            if path == "/api/feature":
                acc = app.find_account(int(data.get("id", 0)))
                key = str(data.get("key", ""))
                if not acc or key not in dict(FEATURES):
                    return self._send(404, {"error": "No such account or switch."})
                app.remote_feature(acc, key, bool(data.get("on")))
                return self._send(200, {"ok": True})
            if path == "/api/notify":
                kind = str(data.get("kind", ""))
                if kind not in KINDS:
                    return self._send(404, {"error": "unknown"})
                app.settings[f"notify_{kind}"] = bool(data.get("on"))
                app.save_settings_now()
                return self._send(200, {"ok": True})
            if path == "/api/push/subscribe":
                remote.add_sub(data.get("subscription"), data.get("name"))
                app.log(f"Phone remote: notifications turned on for {str(data.get('name') or 'a phone')[:40]}.")
                return self._send(200, {"ok": True})
            if path == "/api/push/unsubscribe":
                remote.remove_sub(str(data.get("endpoint", "")))
                return self._send(200, {"ok": True})
            if path == "/api/push/test":
                if not remote.cfg["subs"]:
                    return self._send(400, {"error": "No phone has notifications turned on yet."})
                remote._send_all(list(remote.cfg["subs"]), {"title": "FAAR Manager",
                                                             "body": "Test notification. You're all set!",
                                                             "tag": "test", "kind": "test"})
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    return H
