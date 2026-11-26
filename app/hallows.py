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


def slot_box(img, n):
    h, w = img.shape[:2]
    s = hud_scale(img)
    left = w / 2 + (SLOT1_LEFT + (n - 1) * SLOT_PITCH - 960) * s
    top = h - (REF_H - SLOT_TOP) * s
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


def slot_held(img, n):
    sub = _crop(img, slot_box(img, n))
    if sub is None:
        return False, 0.0
    s = hud_scale(img)
    t = max(2, int(round(5 * s)))
    h, w = sub.shape[:2]
    mask = np.zeros((h, w), bool)
    mask[:t, :] = mask[-t:, :] = True
    mask[:, :t] = mask[:, -t:] = True
    px = sub[mask].astype(int)
    b, g, r = px[:, 0], px[:, 1], px[:, 2]
    blue = (r < 60) & (g >= 125) & (g <= 215) & (b >= 215)
    frac = float(blue.mean()) if len(px) else 0.0
    return frac >= (0.25 if s >= 0.75 else 0.17), frac


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


def hallows_event(img):
    if not builtin.ocr_ready():
        return False, "text reader not available"
    s = hud_scale(img)
    title = _crop(img, _top_centre(img, TITLE_BOX))
    title_text = ""
    if title is not None:
        for v in _variants(_pil(title), 3.0 / s):
            title_text += " " + _ocr(v, "--psm 7")
            why = hallows_reason(title_text, "")
            if why:
                return True, f"{why} | read: {title_text.strip()!r}"
    body = _crop(img, _top_centre(img, EVENT_BOX))
    body_text = ""
    if body is not None:
        for v in _variants(_pil(body), 2.0 / s):
            body_text += " " + _ocr(v, "--psm 6")
            why = hallows_reason(title_text, body_text)
            if why:
                return True, f"{why} | read: {(title_text + ' / ' + body_text).strip()[:160]!r}"
    return False, ""


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


def hallows_event_cached(img, cache, max_age=30.0):
    th = _thumb(img, _top_centre(img, EVENT_BOX))
    old = cache.get("banner")
    if old and _same(old[0], th) and time.time() - old[2] < max_age:
        return old[1]
    res = hallows_event(img)
    cache["banner"] = (th, res, time.time())
    return res


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
