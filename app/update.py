"""
Auto-update.

On launch the app asks GitHub for the latest release and, if it's newer than this build, offers it.
How it updates depends on how it's running:
  * as the packaged FAAR Manager.exe  -> downloads the new .exe and swaps it in (a running .exe can't
    overwrite itself on Windows, so a tiny .bat waits for the app to close, swaps the file, reopens it);
  * from a git clone                  -> git pull;
  * from a plain source download       -> downloads the repo zip and writes the new files over the folder.
The data/ folder (accounts, settings, logs) is never touched.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile

import requests

from .version import __version__, REPO
from . import storage

API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ZIPBALL = f"https://api.github.com/repos/{REPO}/zipball"
TIMEOUT = 12


def is_frozen():
    return getattr(sys, "frozen", False)


def _app_dir():
    # Where the app actually lives: next to the .exe when frozen, else the project root.
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def has_git():
    return os.path.isdir(os.path.join(_app_dir(), ".git")) and shutil.which("git") is not None


def _nums(tag):
    """'v1.2.3' / '1.2.3' -> (1, 2, 3) for comparing."""
    parts = re.findall(r"\d+", tag or "")
    return tuple(int(p) for p in parts[:4]) or (0,)


def is_newer(latest, current=__version__):
    return _nums(latest) > _nums(current)


def check():
    """Ask GitHub for the latest release. Returns a dict, or None if the check failed / nothing newer.
    {version, notes, exe_url, newer}"""
    try:
        r = requests.get(API_LATEST, timeout=TIMEOUT,
                         headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return None
        data = r.json()
        tag = data.get("tag_name") or data.get("name") or ""
        version = re.sub(r"^v", "", tag)
        exe_url = None
        for a in data.get("assets", []):
            if a.get("name", "").lower().endswith(".exe"):
                exe_url = a.get("browser_download_url")
                break
        return {"version": version, "notes": data.get("body", "") or "",
                "exe_url": exe_url, "newer": is_newer(version)}
    except Exception:
        return None


def _download(url, dest, progress=None):
    with requests.get(url, stream=True, timeout=TIMEOUT * 3) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=262144):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done / total)
    return os.path.getsize(dest)


# ----------------------------------------------------------------- applying
def update_exe(info, progress=None):
    """Download the new .exe next to this one, then launch a .bat that swaps it in and restarts.
    The app must exit right after this returns True (the caller does that)."""
    url = info.get("exe_url")
    if not url:
        raise RuntimeError("That release has no .exe attached.")
    exe = os.path.abspath(sys.executable)
    folder = os.path.dirname(exe)
    new_exe = os.path.join(folder, "FAAR Manager.new.exe")
    size = _download(url, new_exe, progress)
    if size < 1_000_000:                              # a real build is tens of MB; a tiny file = bad download
        os.remove(new_exe)
        raise RuntimeError("The download looks incomplete. Try again.")
    bat = os.path.join(folder, "_faar_update.bat")
    # wait for this .exe to close, back up the old one, swap in the new, relaunch, delete self
    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        ':wait\r\n'
        'tasklist /fi "imagename eq %s" | find /i "%s" >nul && (timeout /t 1 >nul & goto wait)\r\n'
        'move /y "%s" "%s" >nul\r\n'
        'move /y "%s" "%s" >nul\r\n'
        'start "" "%s"\r\n'
        'del "%%~f0"\r\n'
    ) % (os.path.basename(exe), os.path.basename(exe),
         exe, os.path.join(folder, "FAAR Manager.old.exe"),
         new_exe, exe,
         exe)
    with open(bat, "w") as f:
        f.write(script)
    subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)   # CREATE_NO_WINDOW
    return True


def update_source(progress=None):
    """Update a source checkout: git pull if it's a clone, else download+extract the repo zip.
    Returns a short message. The app should restart afterwards to load the new code."""
    folder = _app_dir()
    if has_git():
        out = subprocess.run(["git", "-C", folder, "pull", "--ff-only"],
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise RuntimeError("git pull failed: " + (out.stderr.strip() or out.stdout.strip())[:200])
        return "Pulled the latest code. Restart to apply."
    # plain download: fetch the repo zip and copy its files over the folder (keeping data/)
    tmp_zip = os.path.join(folder, "_faar_update.zip")
    _download(ZIPBALL, tmp_zip, progress)
    with zipfile.ZipFile(tmp_zip) as z:
        root = z.namelist()[0].split("/")[0]         # github wraps everything in one top folder
        extract_to = os.path.join(folder, "_faar_update_tmp")
        shutil.rmtree(extract_to, ignore_errors=True)
        z.extractall(extract_to)
    src = os.path.join(extract_to, root)
    for name in os.listdir(src):
        if name == "data":
            continue                                 # never overwrite accounts/settings/logs
        s, d = os.path.join(src, name), os.path.join(folder, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    shutil.rmtree(extract_to, ignore_errors=True)
    os.remove(tmp_zip)
    return "Downloaded the latest files. Restart to apply."


def restart():
    """Relaunch the app (used after a source update)."""
    if is_frozen():
        subprocess.Popen([sys.executable])
    else:
        subprocess.Popen([sys.executable, os.path.join(_app_dir(), "main.py")])
    os._exit(0)
