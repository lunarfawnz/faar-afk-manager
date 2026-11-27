import re

import cv2
import numpy as np

from . import builtin


def _scale(img):
    h, w = img.shape[:2]
    return max(0.2, min(w / 1920.0, h / 1080.0))


def _components(mask):
    n, _, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return [tuple(int(v) for v in st[i]) for i in range(1, n)]


def join_event_x(img):
    if img is None:
        return None
    h_img, w_img = img.shape[:2]
    s = _scale(img)
    rgb = img[..., ::-1].astype(np.int16)
    grey = np.abs(rgb - np.array((39, 41, 48), np.int16)).max(axis=2) <= 3
    for x, y, w, h, area in _components(grey):
        if not (250 * s <= w <= 800 * s) or h <= 0:
            continue
        if not (0.80 <= w / h <= 1.15) or area < 0.35 * w * h:
            continue
        if abs((x + w / 2.0) - w_img / 2.0) > 0.06 * w_img:
            continue
        box = rgb[y:y + h, x:x + w]
        blue = (box[..., 0] <= 100) & (box[..., 1] >= 60) & (box[..., 1] <= 150) & (box[..., 2] >= 235)
        button = False
        for bx, by, bw, bh, barea in _components(blue):
            if 0.75 <= bw / w <= 0.97 and 0.04 <= bh / h <= 0.12 and barea >= 0.6 * bw * bh \
                    and (by + bh / 2.0) / h >= 0.70:
                button = True
                break
        if not button:
            continue
        wx0, wx1 = int(0.03 * w), int(0.20 * w)
        wy0, wy1 = int(0.02 * h), int(0.13 * h)
        white = (box[wy0:wy1, wx0:wx1] >= 190).all(axis=2)
        ys, xs = np.nonzero(white)
        if len(xs) < max(4, int(8 * s * s)):
            continue
        return x + wx0 + int(xs.mean()), y + wy0 + int(ys.mean())
    return None


def _says_claim(img, x, y, w, h):
    if not builtin.ocr_ready():
        return False
    sub = img[max(0, y):y + h, max(0, x):x + w]
    if sub.size == 0:
        return False
    f = max(1.5, 90.0 / max(1, h))
    big = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    a = big.astype(np.int16)
    variants = (np.where(a.min(axis=2) > 200, 0, 255).astype(np.uint8),
                np.where(a.max(axis=2) < 60, 0, 255).astype(np.uint8),
                cv2.cvtColor(big, cv2.COLOR_BGR2GRAY))
    tess = builtin._OCR["mod"]
    for v in variants:
        try:
            txt = tess.image_to_string(v, config="--psm 7", lang=builtin.ocr_lang()).lower()
        except Exception:
            continue
        clean = re.sub(r"[^a-z]", "", txt)
        if "claim" in clean or "clam" in clean or "ciaim" in clean:
            return True
        if re.search(r"rebirth|buy|yes|robux", clean):
            return False
    return False


def daily_claim(img):
    if img is None:
        return None
    s = _scale(img)
    rgb = img[..., ::-1].astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    green = (r <= 30) & (g >= 200) & (b <= 70)
    for x, y, w, h, area in _components(green):
        if not (180 * s <= w <= 800 * s) or not (35 * s <= h <= 160 * s):
            continue
        if not (3.6 <= w / h <= 5.2) or area < 0.7 * w * h:
            continue
        cx, cy = x + w / 2.0, y + h / 2.0
        half = 0.11 * w
        ex, ey = cx + 1.77 * w, cy - 1.70 * w
        x0, x1, y0, y1 = int(ex - 2 * half), int(ex + 2 * half), int(ey - 2 * half), int(ey + 2 * half)
        if x0 < 0 or y0 < 0 or x1 > rgb.shape[1] or y1 > rgb.shape[0]:
            continue
        win = rgb[y0:y1, x0:x1]
        red = (win[..., 0] >= 180) & (win[..., 1] <= 125) & (win[..., 2] <= 125)
        white = (win >= 225).all(axis=2)
        for bx, by, bw, bh, barea in _components(red | white):
            if not (0.10 * w <= bw <= 0.30 * w and 0.10 * w <= bh <= 0.30 * w):
                continue
            if not (0.8 <= bw / bh <= 1.25) or barea < 0.6 * bw * bh:
                continue
            rs = red[by:by + bh, bx:bx + bw].mean()
            ws = white[by:by + bh, bx:bx + bw].mean()
            if rs < 0.40 or not (0.06 <= ws <= 0.50):
                continue
            if not _says_claim(img, x, y, w, h):
                break
            return int(cx), int(cy)
    return None


def income_slots(img):
    from . import hallows
    lay = hallows.hotbar_layout(img)
    if not lay:
        return 0
    n = 0
    s = hallows.hud_scale(img)
    for slot in range(1, lay[1] + 1):
        l, t, r_, b_ = (int(round(v)) for v in hallows.slot_box(img, slot))
        crop = img[max(0, t):b_, max(0, l):r_]
        if crop.size == 0:
            continue
        low = crop[int(crop.shape[0] * 0.6):].astype(np.int16)
        bb, gg, rr = low[..., 0], low[..., 1], low[..., 2]
        if int(((rr <= 90) & (gg >= 190) & (bb <= 90)).sum()) >= max(6, int(40 * s * s)):
            n += 1
    return n
