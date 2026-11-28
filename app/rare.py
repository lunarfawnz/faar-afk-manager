import re

import cv2
import numpy as np

from . import builtin

# The three catch cutscenes, recognised by how the whole screen looks while the game's HUD is hidden:
#   omniscient: "IT KNOWS / NEVER SIN AGAIN", a red figure on dark red, then a white island under a red sky
#   apex:       a deep-blue starfield ("APEX", depth counter, kanji), then a pale-blue island
#   god:        "ARE YOU A GOD?", a pink figure on dark purple
TIERS = {"omniscient": "Omniscient", "apex": "Apex", "god": "God"}
VOTES = 2
VOTE_WINDOW = 12.0
NAME_WAIT = 100.0
COOLDOWN = 40.0


def _stats(img):
    h, w = img.shape[:2]
    f = 320.0 / max(1, w)
    small = cv2.resize(img, (320, max(1, int(h * f))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.int16)
    hh, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    return {
        "red": float((((hh <= 8) | (hh >= 172)) & (s > 150) & (v > 60)).mean()),
        "mag": float(((hh >= 140) & (hh <= 165) & (s > 120) & (v > 80)).mean()),
        "navy": float(((hh >= 95) & (hh <= 125) & (s > 150) & (v < 70)).mean()),
        "dark": float((v < 40).mean()),
        "dred": float((((hh <= 8) | (hh >= 170)) & (s > 120) & (v >= 12) & (v < 60)).mean()),
        "white": float(((s < 30) & (v > 200)).mean()),
        "green": float(((hh >= 45) & (hh <= 75) & (s > 150) & (v > 150)).mean()),
    }


def _hud(img):
    from . import hallows
    try:
        return bool(hallows.hotbar_layout(img))
    except Exception:
        return False


def cutscene(img):
    """Which catch cutscene this frame belongs to, or None."""
    if img is None:
        return None
    st = _stats(img)
    if st["green"] > 0.01:  # the game's green buttons are hidden during a cutscene
        return None
    if st["navy"] >= 0.5:
        kind = "apex"
    elif st["dred"] >= 0.3 and st["red"] >= 0.1 and st["mag"] < 0.03:
        kind = "omniscient"
    elif st["red"] >= 0.18 and st["white"] >= 0.2 and st["mag"] < 0.03:
        kind = "omniscient"
    elif st["mag"] >= 0.1 and st["dark"] >= 0.4 and st["red"] < 0.05:
        kind = "god"
    else:
        return None
    return None if _hud(img) else kind


CAUGHT_RE = re.compile(r"caught\W*\[?\s*([A-Za-z]{3,14})\s*[\]\)|}]?\s*([A-Za-z][A-Za-z' .-]{1,40})")


def clean_name(raw):
    """Keeps the part that looks like a character name: Capitalised words, with small joining words like 'of'."""
    raw = re.split(r"[!}\])|]", raw)[0]
    words = re.findall(r"[A-Za-z']+", raw)
    best, cur = [], []
    for wd in words:
        if wd[0].isupper() and len(wd) >= 3:
            cur.append(wd)
        elif cur and wd in ("of", "the", "and", "de", "no"):
            cur.append(wd)
        else:
            if len(cur) > len(best):
                best = cur
            cur = []
    if len(cur) > len(best):
        best = cur
    while best and best[-1] in ("of", "the", "and", "de", "no"):
        best.pop()
    return " ".join(best)


def caught_text(img):
    """Reads the "You have caught [Tier] Name!" notice. Returns (tier, name) or None."""
    if img is None or not builtin.ocr_ready():
        return None
    h, w = img.shape[:2]
    sub = img[int(h * .60):int(h * .80), int(w * .38):int(w * .68)]
    if sub.size == 0:
        return None
    f = max(1.5, 2.0 * 1080.0 / max(1, h))
    big = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    tess = builtin._OCR["mod"]
    for var in (np.where((hsv[..., 1] > 90) & (hsv[..., 2] > 150), 0, 255).astype(np.uint8),
                255 - cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)):
        try:
            txt = tess.image_to_string(var, config="--psm 6")
        except Exception:
            continue
        flat = " ".join(t.strip() for t in txt.splitlines() if t.strip())
        m = CAUGHT_RE.search(flat)
        if m:
            return m.group(1).strip().title(), clean_name(m.group(2))
    return None
