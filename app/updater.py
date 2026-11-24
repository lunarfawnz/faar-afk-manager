"""
Checks GitHub for a newer version and updates in place.

Two ways it runs, told apart automatically:
  * as the packaged .exe  -> downloads the new FAAR Manager.exe from the latest release and swaps it in
  * from the .py source   -> `git pull` if it's a git clone, otherwise downloads the repo zip over itself

Your accounts and settings (the data folder) are never touched.
Set GITHUB_REPO below to your "owner/repo" or updates stay off.
"""
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from .version import __version__

# ------------------------------------------------------------------ set this
GITHUB_REPO = "OWNER/REPO"      # e.g. "Leelynnd/FAAR-Manager"
# ---------------------------------------------------------------------------


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def app_dir():
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_git_clone():
    return os.path.isdir(os.path.join(app_dir(), ".git"))


def configured():
    return bool(GITHUB_REPO) and "/" in GITHUB_REPO and not GITHUB_REPO.startswith("OWNER")


def _ver(s):
    nums = re.findall(r"\d+", s or "")
    nums = [int(n) for n in nums[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def _get(url, timeout=10, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "FAAR-Manager",
                                               "Accept": "application/vnd.github+json"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read() if binary else r.read().decode("utf-8", "replace")


def check(timeout=10):
    """Ask GitHub for the latest release. Returns a dict the GUI can read:
    {available, current, latest, notes, exe_url, exe_size, html_url} or {available:False, reason/error}."""
    if not configured():
        return {"available": False, "reason": "not configured"}
    try:
        data = json.loads(_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout))
    except Exception as e:
        return {"available": False, "error": str(e)}
    tag = data.get("tag_name") or ""
    exe_url, exe_size = None, 0
    for a in data.get("assets", []):
        if (a.get("name") or "").lower().endswith(".exe"):
            exe_url, exe_size = a.get("browser_download_url"), int(a.get("size") or 0)
            break
    return {
        "available": _ver(tag) > _ver(__version__),
        "current": __version__,
        "latest": tag.lstrip("vV") or tag,
        "notes": (data.get("body") or "").strip(),
        "exe_url": exe_url,
        "exe_size": exe_size,
        "zip_url": data.get("zipball_url"),
        "html_url": data.get("html_url"),
    }


def apply(info, log=lambda m: None):
    """Download and install the update described by check(). On the .exe path this relaunches the app
    and the current process should exit right after. Returns (ok, message)."""
    try:
        if is_frozen():
            return _apply_exe(info, log)
        if is_git_clone():
            return _apply_git(log)
        return _apply_zip(info, log)
    except Exception as e:
        return False, f"Update failed: {e}"


def _apply_git(log):
    log("Updating from git...")
    r = subprocess.run(["git", "pull", "--ff-only"], cwd=app_dir(),
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, "git pull failed: " + (r.stderr or r.stdout).strip()[:200]
    return True, "Updated. Restart the app to use the new version."


def _apply_zip(info, log):
    url = info.get("zip_url")
    if not url:
        return False, "No source archive in the release."
    log("Downloading the new version...")
    raw = _get(url, timeout=60, binary=True)
    tmp = tempfile.mkdtemp()
    zpath = os.path.join(tmp, "src.zip")
    with open(zpath, "wb") as f:
        f.write(raw)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    roots = [os.path.join(tmp, d) for d in os.listdir(tmp)
             if os.path.isdir(os.path.join(tmp, d)) and d != "__MACOSX"]
    if not roots:
        return False, "Downloaded archive looked empty."
    src = roots[0]
    dst = app_dir()
    for base, _dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        if rel.split(os.sep)[0] == "data":              # never overwrite accounts/settings
            continue
        target = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(target, exist_ok=True)
        for fn in files:
            shutil.copy2(os.path.join(base, fn), os.path.join(target, fn))
    shutil.rmtree(tmp, ignore_errors=True)
    return True, "Updated. Restart the app to use the new version."


def _apply_exe(info, log):
    url = info.get("exe_url")
    if not url:
        return False, "This release has no .exe to download."
    target = os.path.abspath(sys.executable)
    new = target + ".new"
    log("Downloading the new version...")
    raw = _get(url, timeout=120, binary=True)
    want = info.get("exe_size") or 0
    if len(raw) < 1_000_000 or (want and abs(len(raw) - want) > 4096):
        return False, "Download looked incomplete, not applying."
    with open(new, "wb") as f:
        f.write(raw)
    # A running .exe can't overwrite itself, so a tiny script waits for us to exit, swaps the file,
    # and relaunches the app.
    bat = os.path.join(os.path.dirname(target), "_faar_update.bat")
    pid = os.getpid()
    name = os.path.basename(target)
    with open(bat, "w") as f:
        f.write(
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /fi "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
            f'move /y "{new}" "{target}" >nul\r\n'
            f'start "" "{target}"\r\n'
            'del "%~f0"\r\n')
    subprocess.Popen(["cmd", "/c", bat], creationflags=0x00000008)  # DETACHED_PROCESS
    return True, "RESTART"       # the GUI closes the app; the script swaps and reopens it
