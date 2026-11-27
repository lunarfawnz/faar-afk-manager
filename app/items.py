import re

import cv2
import numpy as np

from . import builtin

CARD_H = 172
LEVELED = ("cash", "gems")

BOOST_ITEMS = [
    ("cash1", "Cash Potion Lvl 1"), ("cash2", "Cash Potion Lvl 2"), ("cash3", "Cash Potion Lvl 3"),
    ("gems1", "Gems Potion Lvl 1"), ("gems2", "Gems Potion Lvl 2"), ("gems3", "Gems Potion Lvl 3"),
    ("mutation", "Mutation Potion"), ("fastcatch", "Fast Catch Potion"), ("luck", "Luck Potion"),
]
SELENE_ITEMS = [
    ("luck3", "Luck Potion Lvl 3"), ("luck2", "Luck Potion Lvl 2"), ("heavens", "Heaven's Collide Potion"),
    ("meteorite", "Meteorite Potion"), ("food", "Food Potion"), ("honey", "Honey Potion"),
    ("sinister", "Sinister Potion"), ("lucrative", "Lucrative Realization Potion"),
    ("bigfert", "Big Fertilizer"), ("hugefert", "Huge Fertilizer"),
]
FERTILIZERS = ("bigfert", "hugefert")

FINGERPRINTS = {
    "boost": {
        "cash": (60, 251, 255, 57), "gems": (90, 249, 255, 88), "mutation": (150, 215, 116, 144),
        "fastcatch": (30, 251, 255, 30), "luck": (60, 251, 255, 139),
    },
    "selene": {
        "luck3": (60, 251, 255, 166), "luck2": (60, 251, 255, 64), "heavens": (30, 251, 255, 30),
        "meteorite": (12, 251, 255, 19), "food": (20, 199, 255, 19), "honey": (30, 193, 255, 24),
        "sinister": (64, 170, 72, 60), "lucrative": (0, 0, 255, 30),
    },
}
MATCH_MAX, MATCH_MARGIN = 14.0, 6.0


def setting_key(shop, item):
    return f"item_{shop}_{item}"


def default_settings():
    s = {setting_key("boost", k): True for k, _ in BOOST_ITEMS}
    s.update({setting_key("selene", k): True for k, _ in SELENE_ITEMS})
    s[setting_key("selene", "character")] = False
    s["buy_unknown_items"] = False
    return s


def label(shop, item):
    for k, name in (BOOST_ITEMS if shop == "boost" else SELENE_ITEMS):
        if k == item:
            return name
    return {"character": "the character", "ability": "an ability", "unknown": "an item it doesn't recognise"}.get(
        item, item)


def _is_panel(px):
    hsv = cv2.cvtColor(px.reshape(1, -1, 3), cv2.COLOR_BGR2HSV)[0]
    return (hsv[:, 1] < 40) & (hsv[:, 2] < 105)


def card_rect(img, x, y, sc):
    h, w = img.shape[:2]
    yr = int(y - 40 * sc)
    if yr < 2:
        return None
    row = img[max(0, yr - 2):yr + 3].astype(np.int32).mean(axis=0).astype(np.uint8)
    pan = _is_panel(row)
    run = max(3, int(4 * sc))
    l = r = int(min(w - 1, x + 50 * sc))
    while l > 0 and not pan[max(0, l - run):l].all():
        l -= 1
    while r < w - 1 and not pan[r + 1:r + 1 + run].all():
        r += 1
    if not (240 * sc <= r - l <= 380 * sc):
        return None
    bottom = int(y - 28 * sc)
    return l, bottom - int(CARD_H * sc), r, bottom


def _region(img, rect, sc, fx0, fx1, fy0, fy1):
    l, t, r, b = rect
    wd, hh = r - l, b - t
    y0, y1 = max(0, t + int(fy0 * hh)), max(0, t + int(fy1 * hh))
    return img[y0:y1, l + int(fx0 * wd):l + int(fx1 * wd)]


def _hsv(a):
    if a is None or a.size == 0:
        return np.zeros((0, 3), int)
    return cv2.cvtColor(np.ascontiguousarray(a), cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)


def features(img, rect, sc):
    liq = _hsv(_region(img, rect, sc, 0.13, 0.24, 0.58, 0.70))
    bg = _hsv(_region(img, rect, sc, 0.025, 0.07, 0.45, 0.85))
    ic = _hsv(_region(img, rect, sc, 0.05, 0.36, 0.28, 0.92))
    if len(liq) < 4 or len(ic) < 20:
        return None
    sat = bg[(bg[:, 1] > 80) & (bg[:, 2] > 50)]
    return {
        "lh": int(np.median(liq[:, 0])), "ls": int(np.median(liq[:, 1])), "lv": int(np.median(liq[:, 2])),
        "ch": int(np.median(sat[:, 0])) if len(sat) > 10 else -1,
        "dark": float((ic[:, 2] < 55).mean()),
        "white": float(((ic[:, 1] < 45) & (ic[:, 2] > 200)).mean()),
        "cork": float(((ic[:, 0] >= 3) & (ic[:, 0] <= 22) & (ic[:, 1] > 50) & (ic[:, 1] < 190)
                       & (ic[:, 2] > 170)).mean()),
    }


def icon_kind(f):
    if f is None:
        return "other"
    if f["cork"] >= 0.008 and f["dark"] >= 0.015:
        return "potion"
    if f["cork"] < 0.004 and f["dark"] < 0.006 and f["white"] >= 0.04:
        return "ability"
    return "other"


def is_fertilizer(f):
    # A beige sack with a green sprout: far more sack colour than any potion's cork
    return f is not None and f["cork"] >= 0.05 and f["dark"] >= 0.05 and 45 <= f["lh"] <= 85 and f["ls"] >= 100


def _hue_d(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


def _distance(f, fp):
    lh, ls, lv, ch = fp
    d = abs(f["ls"] - ls) / 4 + abs(f["lv"] - lv) / 4
    if ls >= 60 and f["ls"] >= 60:
        d += 2 * _hue_d(f["lh"], lh)
    if f["ch"] >= 0:
        d += 1.5 * _hue_d(f["ch"], ch)
    else:
        d += 20
    return d


def match_potion(f, shop):
    ranked = sorted((_distance(f, fp), name) for name, fp in FINGERPRINTS[shop].items())
    best_d, best = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 999
    if best_d <= MATCH_MAX and second - best_d >= MATCH_MARGIN:
        return best, best_d
    return None, best_d


def title_level(img, rect, sc):
    if not builtin.ocr_ready():
        return None
    sub = _region(img, rect, sc, 0.55, 0.98, 0.0, 0.24)
    if sub is None or sub.size == 0 or rect[1] < 0:
        return None
    f = max(2.0, 4.0 / max(sc, 0.3))
    big = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    dark = hsv[..., 2] < 70
    variants = [np.where((hsv[..., 2] > 150) & ~dark, 0, 255).astype(np.uint8),
                255 - cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)]
    tess = builtin._OCR["mod"]
    for v in variants:
        try:
            txt = tess.image_to_string(v, config="--psm 7", lang=builtin.ocr_lang())
        except Exception:
            continue
        m = re.search(r"([123])\D*$", txt.strip())
        if m:
            return int(m.group(1))
    return None


def card_to_left(img, rect, sc):
    l, t, r, b = rect
    x0, x1 = int(l - 80 * sc), int(l - 50 * sc)
    if x0 < 0:
        return False
    strip = _hsv(img[max(0, b - int(110 * sc)):b - int(40 * sc), x0:x1])
    if len(strip) == 0:
        return False
    return float(((strip[:, 1] > 70) & (strip[:, 2] > 50)).mean()) > 0.5


def identify(img, buttons, shop):
    out = []
    for btn in buttons:
        kind, x, y, cx, sc = btn
        rect = card_rect(img, x, y, sc)
        if rect is None:
            out.append(("unknown", None, None))
            continue
        f = features(img, rect, sc)
        ik = icon_kind(f)
        if ik == "ability":
            out.append(("ability", rect, f))
            continue
        if ik != "potion":
            out.append(("other", rect, f))
            continue
        if shop == "selene" and is_fertilizer(f):
            out.append(("fert", rect, f))
            continue
        name, _ = match_potion(f, shop)
        out.append((name or "unknown", rect, f))
    if shop == "boost":
        _levels(img, buttons, out)
    else:
        _fertilizers(img, buttons, out)
    return out


def fertilizer_title(img, rect, sc):
    if not builtin.ocr_ready():
        return None
    sub = _region(img, rect, sc, 0.05, 0.95, 0.0, 0.24)
    if sub is None or sub.size == 0 or rect[1] < 0:
        return None
    f = max(2.0, 2.0 / max(sc, 0.3))
    big = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    a = big.astype(np.int16)
    tess = builtin._OCR["mod"]
    for v in (np.where(a.min(axis=2) > 200, 0, 255).astype(np.uint8), cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)):
        try:
            txt = re.sub(r"[^a-z]", "", tess.image_to_string(v, config="--psm 7").lower())
        except Exception:
            continue
        if re.search(r"h[uv][aeqg]{1,2}e?f", txt) or txt.startswith("hu"):
            return "hugefert"
        if re.search(r"b[il1][agq]f", txt) or txt.startswith("bi"):
            return "bigfert"
    return None


def _fertilizers(img, buttons, out):
    idxs = [i for i, (name, rect, f) in enumerate(out) if name == "fert"]
    rows = {}
    for i in idxs:
        rows.setdefault(round(out[i][1][3] / max(8, 40 * buttons[i][4])), []).append(i)
    for row in rows.values():
        row.sort(key=lambda i: out[i][1][0])
        for rank, i in enumerate(row):
            _, rect, f = out[i]
            name = fertilizer_title(img, rect, buttons[i][4])
            if name is None and len(row) == 2:
                name = FERTILIZERS[rank]
            out[i] = (name or "unknown", rect, f)


def _levels(img, buttons, out):
    rows = {}
    for i, (name, rect, f) in enumerate(out):
        if name in LEVELED and rect is not None:
            sc = buttons[i][4]
            rows.setdefault((name, round(rect[3] / max(8, 40 * sc))), []).append(i)
    for (name, _), idxs in rows.items():
        idxs.sort(key=lambda i: out[i][1][0])
        for rank, i in enumerate(idxs):
            _, rect, f = out[i]
            lvl = title_level(img, rect, buttons[i][4])
            if lvl is None and len(idxs) == 3:
                lvl = rank + 1
            out[i] = (f"{name}{lvl}" if lvl in (1, 2, 3) else "unknown", rect, f)


def selene_character_slot(img, buttons, ids):
    for (name, rect, f), btn in zip(ids, buttons):
        if name == "luck3" and rect is not None:
            return "character" if card_to_left(img, rect, btn[4]) else "none"
    return "unknown"


def wanted(s, shop, item):
    if item == "ability":
        return False
    if item in ("unknown", "other"):
        return bool(s.get("buy_unknown_items", False))
    if shop == "selene" and item == "character":
        return bool(s.get(setting_key("selene", "character"), False))
    return bool(s.get(setting_key(shop, item), True))
