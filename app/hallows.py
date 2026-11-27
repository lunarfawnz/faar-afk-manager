import difflib
import re
import time

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import builtin

REF_W, REF_H = 1920.0, 1017.0

SLOT1_LEFT, SLOT_PITCH, SLOT_SIZE = 532.4, 85.6, 81
SLOT_TOP = 934
TITLE_BOX = (780, 62, 1140, 105)
EVENT_BOX = (700, 62, 1220, 167)
MUTATION_BOX = (450, 192, 1350, 627)

TITLE_WORDS = ["hallows", "hallow's", "halloweve", "hallowseve"]
DESCRIPTION_WORDS = ["dracula"]
STRONG_CUTOFF, MEDIUM_CUTOFF = 0.90, 0.80
LABEL_DARK = 45


def hud_scale(img):
    h, w = img.shape[:2]
    return min(w / REF_W, h / REF_H)


def _top_centre(img, box):
    h, w = img.shape[:2]
    s = hud_scale(img)
    x0, y0, x1, y1 = box
    return (w / 2 + (x0 - 960) * s, y0 * s, w / 2 + (x1 - 960) * s, y1 * s)


def _centre(img, box):
    h, w = img.shape[:2]
    s = hud_scale(img)
    x0, y0, x1, y1 = box
    return (w / 2 + (x0 - 960) * s, h / 2 + (y0 - 508.5) * s, w / 2 + (x1 - 960) * s, h / 2 + (y1 - 508.5) * s)


BAR_PITCH, BAR_SLOT_W = 85.6, 77.0
BAR_TOP_FROM_BOTTOM, BAR_ROWS = 67.0, 50.0
_layout_memo = {"key": None, "val": None}


def _layout_key(img):
    h, w = img.shape[:2]
    band = img[max(0, h - 70):h:7, ::37]
    return (h, w, hash(band.tobytes()))


def hotbar_layout(img):
    key = _layout_key(img)
    if _layout_memo["key"] == key:
        return _layout_memo["val"]
    val = _find_layout(img)
    _layout_memo["key"], _layout_memo["val"] = key, val
    return val


def _find_layout(img):
    h, w = img.shape[:2]
    s = hud_scale(img)
    top = int(round(h - BAR_TOP_FROM_BOTTOM * s))
    bot = int(round(top + BAR_ROWS * s))
    band = img[max(0, top):min(h, bot)]
    if band.shape[0] < 4 or w < 200:
        return None
    pitch, sw = BAR_PITCH * s, BAR_SLOT_W * s
    f = band.astype(np.float32)
    gray = f.mean(axis=2)
    col = f.mean(axis=(0, 2))
    edge = np.zeros(w, np.float32)
    edge[1:-1] = np.abs(col[2:] - col[:-2])
    emax = edge.copy()
    for k in range(1, 3):
        emax[k:] = np.maximum(emax[k:], edge[:-k])
        emax[:-k] = np.maximum(emax[:-k], edge[k:])
    cg = np.concatenate([[0.0], np.cumsum(gray.mean(axis=0))])
    cd = np.concatenate([[0.0], np.cumsum((gray < 80).mean(axis=0))])
    offs = np.arange(0, max(1, int(w - sw)))
    alive = np.ones(len(offs), bool)
    count = np.zeros(len(offs), int)
    score = np.zeros(len(offs))
    thr = 20.0 * max(0.5, min(1.0, s * 1.3))
    for k in range(10):
        L = np.round(offs + k * pitch).astype(int)
        R = np.round(L + sw).astype(int)
        inside = R < w
        Lc, Rc = np.clip(L, 0, w - 1), np.clip(R, 0, w - 1)
        a = np.clip(L + int(8 * s), 0, w)
        b = np.clip(L + int(69 * s), 0, w)
        n = np.maximum(b - a, 1)
        ok = inside & (emax[Lc] > thr) & (emax[Rc] > thr) & ((cg[b] - cg[a]) / n < 120) & ((cd[b] - cd[a]) / n > 0.5)
        alive &= ok
        count += alive
        score += np.where(alive, emax[Lc] + emax[Rc], 0.0)
    best = int(count.max())
    if best < 1:
        return None
    cands = np.flatnonzero(count == best)
    centre = lambda left: abs(left + ((best - 1) * pitch + sw) / 2.0 - w / 2.0)
    near = [c for c in cands if centre(offs[c]) <= 14 * max(s, 0.4)]
    if not near:
        return None
    pick = max(near, key=lambda c: score[c])
    return float(offs[pick]), best


def hotbar_count(img):
    lay = hotbar_layout(img)
    return lay[1] if lay else None


def slot_box(img, n):
    h, w = img.shape[:2]
    s = hud_scale(img)
    top = h - (REF_H - SLOT_TOP) * s
    lay = hotbar_layout(img)
    if lay:
        left = lay[0] - 2 * s + (n - 1) * BAR_PITCH * s
    else:
        left = w / 2 + (SLOT1_LEFT + (n - 1) * SLOT_PITCH - 960) * s
    return (left, top, left + SLOT_SIZE * s, top + SLOT_SIZE * s)


def _crop(img, box):
    h, w = img.shape[:2]
    l, t, r, b = (int(round(v)) for v in box)
    l, t, r, b = max(0, l), max(0, t), min(w, r), min(h, b)
    if r - l < 3 or b - t < 3:
        return None
    return img[t:b, l:r]


def _pil(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def _ocr(img, config):
    if not builtin.ocr_ready():
        return ""
    try:
        return builtin._OCR["mod"].image_to_string(img, config=config, lang=builtin.ocr_lang()).lower()
    except Exception:
        return ""


def _blue(px):
    hsv = cv2.cvtColor(np.ascontiguousarray(px), cv2.COLOR_BGR2HSV)
    return (hsv[..., 0] >= 92) & (hsv[..., 0] <= 112) & (hsv[..., 1] >= 150) & (hsv[..., 2] >= 170)


def _pure(px):
    b, g, r = px[..., 0].astype(int), px[..., 1].astype(int), px[..., 2].astype(int)
    return (b >= 248) & (r <= 25) & (g >= 120) & (g <= 205)


def slot_frame(img, n):
    s = hud_scale(img)
    pad = max(3, int(round(6 * s)))
    l, tp, r, b = (int(round(v)) for v in slot_box(img, n))
    H_, W_ = img.shape[:2]
    x0, y0, x1, y1 = l - 2 * pad, tp - 2 * pad, r + 2 * pad, b + 2 * pad
    if x1 <= 0 or y1 <= 0 or x0 >= W_ or y0 >= H_:
        return 0.0, 1.0
    sub = img[max(0, y0):min(H_, y1), max(0, x0):min(W_, x1)]
    sub = np.pad(sub, ((max(0, -y0), max(0, y1 - H_)), (max(0, -x0), max(0, x1 - W_)), (0, 0)))
    h, w = sub.shape[:2]
    bar = max(2, int(round(3 * s)))
    if h < 6 * pad or w < 6 * pad:
        return 0.0, 1.0
    blue = _blue(sub)
    ys = slice(3 * pad, h - 3 * pad)
    xs = slice(3 * pad, w - 3 * pad)

    def col(m, x):
        return float(m[ys, x:x + bar].mean()) if 0 <= x and x + bar <= w else 1.0

    def row(m, y):
        return float(m[y:y + bar, xs].mean()) if 0 <= y and y + bar <= h else 1.0

    def side(get, lo, hi, outward):
        best = 0.0
        for p in range(lo, hi + 1):
            loose = get(blue, p)
            if loose < 0.3:
                continue
            outer = get(blue, p + outward * bar)
            if outer < 0.5:
                best = max(best, loose)
        return best

    left = side(col, pad, 3 * pad, -1)
    right = side(col, w - 3 * pad - bar, w - pad - bar, 1)
    top = side(row, pad, 3 * pad, -1)
    bottom = side(row, h - 3 * pad - bar, h - pad - bar, 1)
    m = 4 * pad
    inner = float(blue[m:h - m, m:w - m].mean()) if h > 2 * m + 2 and w > 2 * m + 2 else 1.0
    return min(left, right, top, bottom), inner


LVL_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAABcAAAANCAIAAADNBWIKAAADlklEQVQoFQXBfUwbZRwA4N9LC20PuhtQYKxs61FAClzAlEQKVzMG"
    "wpINGW4ozjVdoybiRtQYpy7idDCHLiYbabLsj4myJswtsclczAzLDGFWJrZsjA9TKNwBBUoLLcV+9+71eZDv+StDv66wK+FwJLEV"
    "iC+7QxmSRJUG78nFcQG82+DZwPOLEInjrGyQyQAB0Hn1ncda5IQ0IQizs8tPJ13o4VDNgxEPtxpZYEOb/lhFsXCyBR84gJMYtkOQ"
    "4CESxU4XPBzBKx4QiUCRA/Vlh7pOtBBSaTIh/Ot0P5tcQP0Xym0TW7/8gXOr3vBN37v0HlddhaZc+O+nsOmHrN1QReNcBdwYxBNL"
    "VfICbXDqZmd7wwftR4k0aTwpOJ2rTqcb9XxU/GQyOObR0Sarw6y/2mkTEWjgNnDLEI0BKYdMUigqhBknDpdbSIqxf6eiaTA2tr+m"
    "ZzBGLOvzbPjRl2fU49PBcV8dbbI6zPqe07alNXTDIiQlVGq6gojZ/QFeXtwamH9Ucvw6STH/fKsq1YC+tM7Y2JQhkwQCO5FYEnV3"
    "Fo7aA1Phl2mT1WHWf9Zh8/lQ/wCvPTcfD65PXmfEJKU772KHL8oURSTFjPepqEJACDWW17bV1IghBYlE6PN3qN8ee93iRtpkdZj1"
    "/UabMgd9bxFm5d1U89dj3xTlaU9RTRfGLhdRhy+SFGPvU+XlQ2oaCDw6qKmuKy2Nx4LoY8P+BzafR9ZEm6wOs/7Hd23VL8D0IrT2"
    "KnVfsNxwT57WEAssuX6qLzhmISnm2RVVtgKBCCOAFwvUBzVqTW0b+tS4//6o10M00yarw6zfi//keezfASyAsuN3UlUrkmTMDhlz"
    "tgZ5nYWkGHufSgDgeShUZr5/hJGIYC6ZhyxfaS4Psh6imTZZAwujgIXUdAUAPL9aIS9/vdzwMx/bedKT31AZYtUWkmL+ukS9dG4m"
    "7J3bvGe49uHJEubVawN30JWz1A/317wZhyuMdxPhrUTIlwj54sG1xdsdAkrTnufW7Rb1+ieEFJz7bhG5pZM3W3TdnPuxGRx9vW+3"
    "VTaf8m9wqOt4vm16e8oVTSSFzHTIJlHWLtglBSYLZli4s4jK9gn9XWjEAb13JXJxNJxISfIgk4rPnGh409C5W1nCTQyjs2175tyh"
    "QmnkdCUuUOHU9BRBwNEI3uHgv2Ug9kKmGrAIYwH4OFrlsHkMP2LRkbqaVl1l2aG3/OucNLL8P1pgstNBU4Q8AAAAAElFTkSuQmCC"
)
_LVL = {}


def _lvl_feats(bgr):
    f = bgr.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    blue = np.clip((b - r - 60.0) / 130.0, 0, 1) * (b > 110)
    near = cv2.dilate((blue > 0.25).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
    dark = np.clip(1.0 - f.max(axis=2) / 90.0, 0, 1) * (1.0 - blue) * near
    return np.dstack([blue, dark, np.zeros_like(blue)]).astype(np.float32)


def _lvl_templates(s):
    key = round(s, 2)
    if key not in _LVL:
        import base64
        raw = np.frombuffer(base64.b64decode("".join(LVL_PNG)), np.uint8)
        tpl = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        out = []
        for k in (0.85, 0.95, 1.05, 1.15):
            f = s * k
            if tpl.shape[1] * f < 8:
                continue
            small = cv2.resize(tpl, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            out.append(cv2.GaussianBlur(_lvl_feats(small), (0, 0), 0.7))
        _LVL[key] = out
    return _LVL[key]


def lvl_score(img, n):
    s = hud_scale(img)
    l, t, r, b = (int(round(v)) for v in slot_box(img, n))
    w = r - l
    sub = _crop(img, (l - 2 * s, t - 2 * s, l + w * 0.72, t + w * 0.42))
    if sub is None:
        return 0.0
    feats = cv2.GaussianBlur(_lvl_feats(sub), (0, 0), 0.7)
    integ = cv2.integral(feats[..., 0])
    best = 0.0
    for tpl in _lvl_templates(s):
        th, tw = tpl.shape[:2]
        if feats.shape[0] < th or feats.shape[1] < tw:
            continue
        res = np.nan_to_num(cv2.matchTemplate(feats, tpl, cv2.TM_CCOEFF_NORMED))
        ih, iw = res.shape
        mass = integ[th:th + ih, tw:tw + iw] - integ[0:ih, tw:tw + iw] - integ[th:th + ih, 0:iw] + integ[0:ih, 0:iw]
        res = np.where(mass >= 0.5 * float(tpl[..., 0].sum()), res, 0.0)
        best = max(best, float(res.max()))
    return best


LVL_ON, LVL_OFF, LVL_MIN_SCALE, LVL_VETO_SCALE = 0.62, 0.45, 0.9, 0.7


def held_slot(img, slots=None):
    if img is None:
        return None, {}
    s = hud_scale(img)
    need = 0.45 if s >= 0.6 else 0.3
    lay = hotbar_layout(img)
    if not lay:
        return None, {}
    count = lay[1]
    scores = {n: 0.0 for n in range(1, 11)}
    for n in range(1, count + 1):
        frame, inner = slot_frame(img, n)
        scores[n] = frame if inner < 0.35 else 0.0
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_n, best = ranked[0]
    second = ranked[1][1]
    unique = best >= need and second < need and best >= 1.6 * max(second, 0.02)
    mine = [n for n in (slots or []) if 1 <= n <= count]
    if unique and best_n in mine and best < 0.8 and s >= LVL_VETO_SCALE and lvl_score(img, best_n) <= 0.3:
        return None, scores
    if s >= LVL_MIN_SCALE and len(mine) >= 2:
        lv = {n: lvl_score(img, n) for n in mine}
        if not unique:
            on = [n for n, v in lv.items() if v >= LVL_ON]
            if len(on) == 1 and all(v <= LVL_OFF for n, v in lv.items() if n != on[0]):
                return on[0], scores
    if not unique:
        return None, scores
    return best_n, scores


def slot_held(img, n, slots=None):
    got, scores = held_slot(img, slots)
    return got == n, scores.get(n, 0.0)


def _clean(text):
    t = text.lower()
    for a, b in (("1", "l"), ("|", "l"), ("0", "o"), ("5", "s"), ("’", "'"), ("`", "'")):
        t = t.replace(a, b)
    return t


def _title_word_score(text):
    best = 0.0
    for tok in re.findall(r"[a-z']+", _clean(text)):
        tok2 = tok.replace("'", "")
        if len(tok2) < 6 or tok2[0] not in "hn":
            continue
        for w in TITLE_WORDS:
            best = max(best, difflib.SequenceMatcher(None, tok2, w.replace("'", "")).ratio())
    return best


def hallows_reason(title_text, body_text):
    both = title_text + " " + body_text
    score = _title_word_score(both)
    if score >= STRONG_CUTOFF:
        return f"title word ~ 'hallows' ({score:.2f})"
    clean = _clean(body_text)
    for w in DESCRIPTION_WORDS:
        if w in clean:
            return f"'{w}' in the description"
    if score >= MEDIUM_CUTOFF and re.search(r"\beve\b", _clean(both)):
        return f"title word ~ 'hallows' ({score:.2f}) + 'eve'"
    return ""


def _variants(pil, factor):
    big = pil.resize((max(1, int(pil.width * factor)), max(1, int(pil.height * factor))))
    gray = big.convert("L")
    yield gray
    yield gray.point(lambda p: 255 if p > 170 else 0)
    hsv = cv2.cvtColor(np.array(big.convert("RGB")), cv2.COLOR_RGB2HSV)
    warm = (hsv[..., 1] >= 120) & (hsv[..., 2] >= 170) & ((hsv[..., 0] <= 35) | (hsv[..., 0] >= 170))
    if warm.mean() > 0.02:
        yield Image.fromarray(np.where(warm, 0, 255).astype("uint8"))


EVENTS = {
    "hallows": "Hallow's Eve",
    "heavens": "Heaven's Collide",
    "solar": "Solar",
    "hells": "Hell's Gates",
    "slime": "Slime Rain",
}
OTHER_TITLE = {"heavens": ["heavens", "heaven", "collide"], "solar": ["solar"], "hells": ["hells", "gates"],
               "slime": ["slime"]}
OTHER_BODY = {"heavens": ["angelic", "falling"], "solar": ["solar"], "hells": ["hells"], "slime": ["slime"]}


def _other_event(text, table, cutoff=0.82):
    toks = [tok.replace("'", "") for tok in re.findall(r"[a-z']+", _clean(text))]
    for key, words in table.items():
        for tok in toks:
            if len(tok) < 4:
                continue
            for w in words:
                if difflib.SequenceMatcher(None, tok, w).ratio() >= cutoff:
                    return key
    return ""


def classify_event(img):
    if not builtin.ocr_ready():
        return "", "text reader not available"
    s = hud_scale(img)
    title = _crop(img, _top_centre(img, TITLE_BOX))
    title_text = ""
    if title is not None:
        for v in _variants(_pil(title), 3.0 / s):
            title_text += " " + _ocr(v, "--psm 7")
            other = _other_event(title_text, OTHER_TITLE, 0.78)
            if other:
                return other, f"title read: {title_text.strip()!r}"
            why = hallows_reason(title_text, "")
            if why:
                return "hallows", f"{why} | read: {title_text.strip()!r}"
    body = _crop(img, _top_centre(img, EVENT_BOX))
    body_text = ""
    if body is not None:
        for v in _variants(_pil(body), 2.0 / s):
            body_text += " " + _ocr(v, "--psm 6")
            other = _other_event(title_text, OTHER_TITLE) or _other_event(body_text, OTHER_BODY)
            if other:
                return other, f"read: {(title_text + ' / ' + body_text).strip()[:160]!r}"
            why = hallows_reason(title_text, body_text)
            if why:
                return "hallows", f"{why} | read: {(title_text + ' / ' + body_text).strip()[:160]!r}"
    return "", ""


def hallows_event(img):
    name, why = classify_event(img)
    return name == "hallows", why


def _has_word(text, words, cutoff=0.84, minlen=4):
    for t in re.findall(r"[a-z']+", text):
        if len(t) < minlen:
            continue
        for w in words:
            if difflib.SequenceMatcher(None, t, w).ratio() >= cutoff:
                return True
    return False


def fuzzy_in(text, word, cutoff=0.78):
    L = len(word)
    for tok in re.findall(r"[a-z]+", text.lower()):
        if len(tok) < 4:
            continue
        for ln in (L - 1, L, L + 1):
            for i in range(0, max(1, len(tok) - ln + 1)):
                if difflib.SequenceMatcher(None, tok[i:i + ln], word).ratio() >= cutoff:
                    return True
    return False


def slot_is_potion(img, n):
    l, t, _, _ = slot_box(img, n)
    s = hud_scale(img)
    sub = _crop(img, (l - 8 * s, t - 39 * s, l + 89 * s, t + 3 * s))
    if sub is None:
        return False
    f = 4.0 / max(s, 0.25)
    big = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_LANCZOS4)
    mask = big.min(axis=2) > 190
    text = _ocr(Image.fromarray(np.where(mask, 0, 255).astype("uint8")), "--psm 6")
    return _has_word(text, ["potion"], cutoff=0.8, minlen=5)


def _label_texts(img, n):
    l, t, _, _ = slot_box(img, n)
    s = hud_scale(img)
    sub = _crop(img, (l - 8 * s, t - 22 * s, l + 89 * s, t))
    if sub is None:
        return
    sc = 6.0 / max(s, 0.25)
    rgb = cv2.cvtColor(sub, cv2.COLOR_BGR2RGB).astype(int)
    m = (rgb.max(axis=2) < LABEL_DARK).astype(np.uint8)
    big = cv2.resize(m, None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST)
    k = np.ones((3, 3), np.uint8)
    for v in (255 - big * 255, 255 - cv2.dilate(big, k, iterations=1) * 255,
              255 - cv2.morphologyEx(big, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) * 255):
        yield _ocr(Image.fromarray(v.astype("uint8")), "--psm 7").strip()
    pil = _pil(sub)
    pil = pil.resize((max(1, int(pil.width * sc)), max(1, int(pil.height * sc))), Image.LANCZOS)
    a2 = np.array(pil).astype(int)
    mx, mn = a2.max(axis=2), a2.min(axis=2)
    gray = pil.convert("L")
    for v in (Image.fromarray(np.where(mx > 150, 0, 255).astype("uint8")),
              Image.fromarray(np.where((mx - mn) > 90, 0, 255).astype("uint8")),
              gray, ImageOps.invert(gray)):
        yield _ocr(v, "--psm 7").strip()


def slot_label_has(img, n, word):
    return any(fuzzy_in(t, word) for t in _label_texts(img, n))


def world_label_has(img, word):
    if not builtin.ocr_ready():
        return False
    box = _centre(img, MUTATION_BOX)
    sub = _crop(img, box)
    if sub is None:
        return False
    s = hud_scale(img)
    f = 2.0 / max(s, 0.25)
    pil = _pil(sub)
    big = pil.resize((max(1, int(pil.width * f)), max(1, int(pil.height * f))), Image.LANCZOS)
    gray = big.convert("L")
    arr = np.array(big).astype(int)
    mx, mn = arr.max(axis=2), arr.min(axis=2)
    variants = [gray, ImageOps.invert(gray),
                Image.fromarray(np.where(mx > 150, 0, 255).astype("uint8")),
                Image.fromarray(np.where((mx - mn) > 90, 0, 255).astype("uint8"))]
    tess = builtin._OCR["mod"]
    toks = []
    for v in variants:
        try:
            d = tess.image_to_data(v, config="--psm 11", lang=builtin.ocr_lang(),
                                   output_type=tess.Output.DICT)
        except Exception:
            continue
        for i, txt in enumerate(d["text"]):
            if txt.strip() and float(d["conf"][i]) >= 0:
                toks.append((txt.strip(), d["left"][i] / f, d["top"][i] / f, d["width"][i] / f, d["height"][i] / f))
    clean = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    feed = [t for t in toks if difflib.SequenceMatcher(None, clean(t[0]), "caught").ratio() >= 0.8
            or clean(t[0]) == "got"]
    for t in toks:
        c = clean(t[0])
        if len(c) >= 4 and difflib.SequenceMatcher(None, c, word).ratio() >= 0.78:
            in_feed = any(abs((fd[2] + fd[4] / 2) - (t[2] + t[4] / 2)) < 14 * s and 0 < t[1] - fd[1] < 450 * s
                          for fd in feed)
            if not in_feed:
                return True
    return False


def mutation_seen(img, n, word="dracula"):
    word = word.lower()
    return slot_label_has(img, n, word) or world_label_has(img, word)


def _thumb(img, box):
    sub = _crop(img, box)
    if sub is None:
        return None
    return cv2.resize(cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY), (64, 20), interpolation=cv2.INTER_AREA).astype(np.int16)


def _same(a, b, tol=3.0):
    return a is not None and b is not None and a.shape == b.shape and float(np.abs(a - b).mean()) < tol


def event_cached(img, cache, max_age=30.0):
    th = _thumb(img, _top_centre(img, EVENT_BOX))
    old = cache.get("banner")
    if old and _same(old[0], th) and time.time() - old[2] < max_age:
        return old[1]
    res = classify_event(img)
    cache["banner"] = (th, res, time.time())
    return res


def hallows_event_cached(img, cache, max_age=30.0):
    name, why = event_cached(img, cache, max_age)
    return name == "hallows", why


def mutation_seen_cached(img, n, word, cache, world_every=3, max_age=30.0):
    word = word.lower()
    now = time.time()
    l, t, _, _ = slot_box(img, n)
    sc = hud_scale(img)
    lab_th = _thumb(img, (l - 8 * sc, t - 22 * sc, l + 89 * sc, t))
    old = cache.get(("label", n))
    if old and _same(old[0], lab_th) and now - old[2] < max_age:
        on_label = old[1]
    else:
        on_label = slot_label_has(img, n, word)
        cache[("label", n)] = (lab_th, on_label, now)
    if on_label:
        return True
    cache["mut_n"] = cache.get("mut_n", 0) + 1
    if cache["mut_n"] % world_every and not cache.get("world_hit"):
        return None
    w_th = _thumb(img, _centre(img, MUTATION_BOX))
    old = cache.get("world")
    if old and _same(old[0], w_th) and now - old[2] < max_age:
        hit = old[1]
    else:
        hit = world_label_has(img, word)
        cache["world"] = (w_th, hit, now)
    cache["world_hit"] = hit
    return hit


MUTATIONS = ("dracula", "demonic", "sinister", "blood", "nightmare", "electric", "zombie", "ghost",
             "angelic", "complexity", "diamond", "frozen", "gold", "honey", "lava", "lunar", "mars",
             "party", "slime", "solar", "toxic", "void")
HALLOWS_GIVES = ("dracula", "demonic", "sinister", "blood", "nightmare", "electric", "zombie", "ghost")
TIMER_BOX = (760, 128, 1160, 172)


def parse_slots(text):
    out = []
    for part in re.split(r"[,\s;]+", str(text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", part)
        if m:
            a, b = int(m.group(1)) or 10, int(m.group(2)) or 10
            rng = range(a, b + 1) if a <= b else range(a, b - 1, -1)
        elif part.isdigit():
            rng = [int(part) or 10]
        else:
            return []
        for n in rng:
            if 1 <= n <= 10 and n not in out:
                out.append(n)
    return out


def _mutation_in(text):
    best, name = 0.0, ""
    for tok in re.findall(r"[a-z]+", _clean(text)):
        if len(tok) < 3:
            continue
        for m in MUTATIONS:
            r = difflib.SequenceMatcher(None, tok, m).ratio()
            if r > best:
                best, name = r, m
    return name if best >= 0.8 else ""


def slot_mutation(img, n):
    if not builtin.ocr_ready():
        return ""
    for t in _label_texts(img, n):
        name = _mutation_in(t)
        if name:
            return name
    return ""


def slot_mutation_cached(img, n, cache, max_age=30.0):
    l, t, _, _ = slot_box(img, n)
    sc = hud_scale(img)
    th = _thumb(img, (l - 8 * sc, t - 22 * sc, l + 89 * sc, t))
    old = cache.get(("mut", n))
    if old and _same(old[0], th) and time.time() - old[2] < max_age:
        return old[1]
    name = slot_mutation(img, n)
    cache[("mut", n)] = (th, name, time.time())
    return name


def event_seconds_left(img):
    if not builtin.ocr_ready():
        return None
    sub = _crop(img, _top_centre(img, TIMER_BOX))
    if sub is None:
        return None
    s = hud_scale(img)
    f = max(1.5, 3.0 / max(s, 0.25))
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    green = (hsv[..., 0] >= 35) & (hsv[..., 0] <= 85) & (hsv[..., 1] >= 110) & (hsv[..., 2] >= 120)
    if green.mean() < 0.01:
        return None
    mask = cv2.resize(np.where(green, 0, 255).astype(np.uint8), None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((mask == 0).astype(np.uint8))
    rows = mask.shape[0]
    tall = [i for i in range(1, n) if rows * 0.15 <= stats[i][3] <= rows * 0.6 and stats[i][2] <= stats[i][3] * 3]
    if not tall:
        return None
    top = float(np.median([stats[i][1] for i in tall]))
    bot = float(np.median([stats[i][1] + stats[i][3] for i in tall]))
    lh = max(1.0, bot - top)
    keep = np.zeros_like(mask, bool)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if y >= top - lh * 0.4 and y + h <= bot + lh * 0.4 and h <= lh * 1.5 and w <= lh * 3 and area >= 4:
            keep |= lab == i
    dots = [i for i in range(1, n) if stats[i][3] <= lh * 0.4 and stats[i][2] <= lh * 0.4
            and stats[i][1] >= top - lh * 0.2 and stats[i][1] + stats[i][3] <= bot + lh * 0.2]
    colon = None
    for a in dots:
        for b in dots:
            ax, ay, aw = stats[a][0], stats[a][1], stats[a][2]
            bx, by = stats[b][0], stats[b][1]
            if a != b and abs(ax - bx) <= max(2, aw) and by - ay > lh * 0.3:
                cx = (ax + bx) // 2
                if colon is None or cx > colon[0]:
                    colon = (min(ax, bx), max(ax + aw, bx + stats[b][2]))
    img = np.where(keep, 0, 255).astype(np.uint8)
    if colon is not None:
        gap = np.full((img.shape[0], int(lh * 0.35)), 255, np.uint8)
        img = np.hstack([img[:, :colon[0]], gap, img[:, colon[0]:colon[1]], gap, img[:, colon[1]:]])
        keep = img == 0
    ys = np.nonzero(keep.any(axis=1))[0]
    xs = np.nonzero(keep.any(axis=0))[0]
    clean = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    k = 60.0 / max(1, clean.shape[0])
    clean = cv2.resize(clean, None, fx=k, fy=k, interpolation=cv2.INTER_LINEAR)
    clean = np.where(cv2.GaussianBlur(clean, (5, 5), 0) > 127, 255, 0).astype(np.uint8)
    clean = cv2.copyMakeBorder(clean, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    tess = builtin._OCR["mod"]
    try:
        d = tess.image_to_data(clean, config="--psm 7", lang=builtin.ocr_lang(), output_type=tess.Output.DICT)
    except Exception:
        return None
    words = [(d["text"][i], d["left"][i], d["width"][i]) for i in range(len(d["text"])) if d["text"][i].strip()]
    if not words:
        return None
    _, wl, ww = words[-1]
    tail = clean[:, max(0, wl - 8):wl + ww + 8]
    tail = cv2.copyMakeBorder(tail, 0, 0, 20, 20, cv2.BORDER_CONSTANT, value=255)
    for img2, cfg in ((tail, "--psm 7 -c tessedit_char_whitelist=0123456789:"),
                      (tail, "--psm 8 -c tessedit_char_whitelist=0123456789:"),
                      (clean, "--psm 7")):
        txt = _ocr(Image.fromarray(img2), cfg)
        got = _parse_clock(txt)
        if got is not None:
            return got
    return None


def _parse_clock(txt):
    t = txt.lower().strip()
    m = re.findall(r"(\d{1,2})\s*[:.;]\s*(\d{2})", t)
    if m and int(m[-1][1]) < 60:
        return int(m[-1][0]) * 60 + int(m[-1][1])
    m = re.search(r"(?:duration|ation)\W*([0-9tli|!])\W{0,2}(\d{2})\b", t)
    if m:
        mm = m.group(1)
        mm = int(mm) if mm.isdigit() else 1
        if int(m.group(2)) < 60:
            return mm * 60 + int(m.group(2))
    m = re.fullmatch(r"(\d)(\d{2})", re.sub(r"\D", "", t)) if re.fullmatch(r"[\d\s:.;]+", t or "x") else None
    if m and int(m.group(2)) < 60:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None
