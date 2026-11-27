import re
from decimal import Decimal

import cv2
import numpy as np

from . import builtin

SUFFIXES = ["", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc",
            "Ud", "Dd", "Td", "Qad", "Qid", "Sxd", "Spd", "Ocd", "Nod", "Vg"]
_BY_LEN = sorted([s for s in SUFFIXES if s], key=len, reverse=True)
WHITELIST = "0123456789.,$KMBTQaiSxpOcNodDhCs:"
VARIANTS = [(3, 4), (2, 5), (0, 3), (5, 4), (2, 6), (3, 5)]


def parse(text):
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([A-Za-z0-9|]*)", text or "")
    if not m:
        return None
    number = m.group(1)
    rest = re.sub(r"^Q[1lI|]", "Qi", m.group(2))
    suffix = ""
    for cand in _BY_LEN:
        if rest.startswith(cand):
            suffix = cand
            break
    else:
        if rest and rest not in ("$",):
            return None
    if suffix and "," in number and "." not in number:
        number = number.replace(",", ".", 1)
    number = number.replace(",", "")
    if "." in number and len(number.split(".")[1]) > 3:
        return None
    try:
        mant = Decimal(number)
    except Exception:
        return None
    if suffix and mant <= 0:
        return None
    if suffix and not (0 < mant < 1000):
        return None
    return mant * (Decimal(1000) ** SUFFIXES.index(suffix)), suffix, mant


def text(money):
    if money is None:
        return "unknown"
    return f"{money[2].normalize():f}{money[1]}"


def _green(bgr):
    c = bgr.astype(int)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    return (g > 150) & (r < 150) & (b < 120) & (g - r > 60) & (g - b > 80)


def _lines(mask, min_h, min_px, row_px):
    rows = mask.sum(1)
    runs, start = [], None
    for i, v in enumerate(rows):
        if v > row_px and start is None:
            start = i
        if v <= row_px and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(rows) - 1))
    return [r for r in runs if r[1] - r[0] >= min_h and mask[r[0]:r[1] + 1].sum() >= min_px]


def _line_box(img, x0, y0, x1, y1, pick, min_h, min_px):
    s = max(0.3, min(img.shape[1] / 1920.0, img.shape[0] / 1080.0))
    mask = _green(img[y0:y1, x0:x1])
    runs = _lines(mask, max(4, int(min_h * s)), max(20, int(min_px * s * s)), max(2, int(6 * s)))
    if not runs:
        return None
    a, b = pick(runs, mask)
    cols = np.where(mask[a:b + 1].sum(0) > 0)[0]
    return x0 + int(cols.min()), y0 + a, x0 + int(cols.max()), y0 + b


def cash_box(img):
    h, w = img.shape[:2]
    return _line_box(img, 0, int(h * .83), int(w * .22), int(h * .985), lambda runs, m: runs[-1], 12, 150)


def cost_box(img):
    h, w = img.shape[:2]
    return _line_box(img, int(w * .30), int(h * .47), int(w * .70), int(h * .575),
                     lambda runs, m: max(runs, key=lambda r: m[r[0]:r[1] + 1].sum()), 20, 400)


def _read(img, box, margin, scale):
    x0, y0, x1, y1 = box
    h, w = img.shape[:2]
    x0, y0 = max(0, x0 - margin), max(0, y0 - margin)
    x1, y1 = min(w, x1 + margin + 1), min(h, y1 + margin + 1)
    s = max(0.3, min(w / 1920.0, h / 1080.0))
    f = scale / s
    mask = _green(img[y0:y1, x0:x1]).astype(np.uint8) * 255
    mask = cv2.resize(mask, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    out = cv2.copyMakeBorder(255 - mask, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return builtin._OCR["mod"].image_to_string(
        out, config=f"--psm 7 -c tessedit_char_whitelist={WHITELIST}").strip()


def read(shots, box_fn, tries=6, wait=None):
    if not builtin.ocr_ready():
        return None, []
    votes, seen = {}, []
    for i in range(tries):
        img = shots()
        if img is None:
            continue
        box = box_fn(img)
        if box is None:
            seen.append("")
        else:
            margin, scale = VARIANTS[i % len(VARIANTS)]
            try:
                t = _read(img, box, margin, scale)
            except Exception:
                t = ""
            seen.append(t)
            val = parse(t)
            if val is not None:
                e = votes.setdefault(val[0], [val, 0])
                e[1] += 1
        ranked = sorted(votes.values(), key=lambda v: -v[1])
        if ranked and ranked[0][1] >= 2 and (len(ranked) == 1 or ranked[1][1] <= ranked[0][1] - 2):
            return ranked[0][0], seen
        if wait:
            wait(0.15)
    ranked = sorted(votes.values(), key=lambda v: -v[1])
    if ranked and ranked[0][1] >= 2 and (len(ranked) == 1 or ranked[1][1] < ranked[0][1]):
        return ranked[0][0], seen
    return None, seen
