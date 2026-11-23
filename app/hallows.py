import difflib
import re

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
        return builtin._OCR["mod"].image_to_string(img, config=config).lower()
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
            d = tess.image_to_data(v, config="--psm 11", output_type=tess.Output.DICT)
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
