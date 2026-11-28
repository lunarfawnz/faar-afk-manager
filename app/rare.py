import re

import cv2
import numpy as np

from . import builtin

# The three catch cutscenes, recognised by how the whole screen looks while the game's HUD is hidden:
#   omniscient: "IT KNOWS / NEVER SIN AGAIN", a red figure on dark red, then a white island under a red sky
#   apex:       a deep-blue starfield ("APEX", depth counter, kanji), then a pale-blue island
#   god:        "ARE YOU A GOD?", a pink figure on dark purple
#   transcendent: about a minute of near-black screens with a faint dark-red glow (hell names, kanji,
#                 white shapes, a red seal, "TRANSCENDENT"), then a pale island under a dark red sky
TIERS = {"omniscient": "Omniscient", "apex": "Apex", "god": "God", "transcendent": "Transcendent"}
VOTES = {"transcendent": 4}  # it has short red flashes that look like Omniscient, so it needs a longer look
VOTES_DEFAULT = 2
VOTE_WINDOW = 15.0
NAME_WAIT = 100.0
READ_FOR = 5.0  # keep reading this long after the name first shows up
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
    elif st["dark"] >= 0.6 and st["dred"] >= 0.15 and st["red"] < 0.12:
        kind = "transcendent"
    elif st["dred"] >= 0.3 and st["red"] >= 0.1 and st["mag"] < 0.03:
        kind = "omniscient"
    elif st["red"] >= 0.18 and st["white"] >= 0.2 and st["mag"] < 0.03:
        kind = "omniscient"
    elif st["mag"] >= 0.1 and st["dark"] >= 0.4 and st["red"] < 0.05:
        kind = "god"
    else:
        return None
    return None if _hud(img) else kind


CAUGHT_RE = re.compile(r"caught\W*\[?\s*([A-Za-z]{2,14})\s*[\]\)|}]?\s*(.{1,80})")
JOINERS = ("of", "the", "and", "de", "no")
BANG = "lI1i|!"  # how the "!" after the name tends to come out


def clean_name(raw):
    """Keeps the character name: the last run of Capitalised words (small joining words like 'of' allowed).
    The name is the last thing before the "!", and stray marks from the background come before it."""
    raw = re.split(r"[!}\])|]", raw)[0]
    words = re.findall(r"[A-Za-z']+", raw)
    runs, cur = [], []
    for wd in words:
        if wd[0].isupper() and len(wd) >= 3:
            cur.append(wd)
        elif cur and wd in JOINERS:
            cur.append(wd)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return ""
    best = runs[-1]
    while best and best[-1] in JOINERS:
        best.pop()
    return " ".join(best)


def caught_texts(img):
    """Every reading of the "You have caught [Tier] Name!" notice in this frame, as (tier, name) pairs."""
    if img is None or not builtin.ocr_ready():
        return []
    h, w = img.shape[:2]
    sub = img[int(h * .60):int(h * .80), int(w * .36):int(w * .70)]
    if sub.size == 0:
        return []
    f = max(1.5, 2.0 * 1080.0 / max(1, h))
    big = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    tess = builtin._OCR["mod"]
    out = []
    for var in (np.where((hsv[..., 1] > 90) & (hsv[..., 2] > 150), 0, 255).astype(np.uint8),
                255 - cv2.cvtColor(big, cv2.COLOR_BGR2GRAY),
                np.where(big.max(axis=2) > 200, 0, 255).astype(np.uint8)):
        try:
            txt = tess.image_to_string(var, config="--psm 6")
        except Exception:
            continue
        flat = " ".join(t.strip() for t in txt.splitlines() if t.strip())
        m = CAUGHT_RE.search(flat)
        if m:
            name = clean_name(m.group(2))
            if name.lower() in {t.lower() for t in TIERS.values()}:
                name = ""
            out.append((m.group(1).strip().title(), name))
    return out


def caught_text(img):
    got = caught_texts(img)
    named = [g for g in got if g[1]]
    return (named or got or [None])[0]


def tier_of(read):
    """Which rare tier the notice's [Tier] text names, or None."""
    for kind in TIERS:
        if tier_matches(read, kind):
            return kind
    return None


def tier_matches(read, kind):
    want = TIERS[kind].lower()
    got = re.sub(r"[^a-z]", "", read.lower())
    if not got:
        return False
    if want in got or got.startswith(want[:2]):
        return True
    import difflib
    return difflib.SequenceMatcher(None, got[:len(want) + 1], want).ratio() >= 0.6


def best_name(reads):
    """reads: names in the order they were read. The notice types itself out letter by letter, so early reads
    are cut short; the final text is the reading that agrees best with the later ones. A trailing letter that
    other reads don't have is the "!" being misread, so it's dropped."""
    import difflib
    tiers = {t.lower() for t in TIERS.values()}
    names = [n for n in reads if n and len(n) >= 3 and n.lower() not in tiers]
    if not names:
        return ""
    late = names[len(names) // 2:]
    final = max(set(late), key=lambda n: (sum(difflib.SequenceMatcher(None, n, o).ratio() for o in late),
                                         late.count(n)))
    if len(final) > 3 and final[-1] in BANG and final[:-1] in names:
        final = final[:-1]
    return final
