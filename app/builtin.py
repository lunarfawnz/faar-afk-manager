import base64
import difflib
import os
import re
import shutil
import sys

import cv2
import numpy as np

from .builtin_templates import TEMPLATES

REF_H = 1017.0
REL_SCALES = (0.8, 0.9, 1.0, 1.1, 1.25)

_cache = {}


def _tpl(name):
    if name not in _cache:
        _cache[name] = cv2.imdecode(np.frombuffer(base64.b64decode(TEMPLATES[name]), np.uint8),
                                    cv2.IMREAD_COLOR)
    return _cache[name]


def ui_scale(img):
    return img.shape[0] / REF_H


def white_mask(img):
    return np.where(img.min(axis=2) >= 185, 255, 0).astype(np.uint8)


def orange_mask(img):
    b, g, r = (img[:, :, i].astype(np.int16) for i in range(3))
    return np.where((r >= 190) & (g >= 110) & (b <= 120) & (r - b >= 100), 255, 0).astype(np.uint8)


_MASKS = {"white": white_mask, "orange": orange_mask}


def _region(img, frac):
    H, W = img.shape[:2]
    if frac is None:
        return img, 0, 0
    x0, y0, x1, y1 = frac
    l, t, r, b = int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)
    return img[t:b, l:r], l, t


def _box(img, box):
    H, W = img.shape[:2]
    l, t, r, b = (int(round(v)) for v in box)
    l, t, r, b = max(0, l), max(0, t), min(W, r), min(H, b)
    if r - l < 4 or b - t < 4:
        return None, l, t
    return img[t:b, l:r], l, t


def _match(sub, ox, oy, tpl, scales, thr, mask=None, max_hits=40):
    if sub is None or sub.size == 0:
        return []
    hay = _MASKS[mask](sub) if mask else sub
    if mask:
        hay = cv2.GaussianBlur(hay, (3, 3), 0)
    hits = []
    for sc in scales:
        t = cv2.resize(tpl, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR)
        if mask:
            t = cv2.GaussianBlur(_MASKS[mask](t), (3, 3), 0)
            if t.std() < 5:
                continue
        th, tw = t.shape[:2]
        if th < 6 or tw < 6 or th > hay.shape[0] or tw > hay.shape[1]:
            continue
        res = np.nan_to_num(cv2.matchTemplate(hay, t, cv2.TM_CCOEFF_NORMED))
        flat = res.ravel()
        idx = np.flatnonzero(flat >= thr)
        if len(idx) > 400:
            idx = idx[np.argpartition(flat[idx], -400)[-400:]]
        ys, xs = np.unravel_index(idx, res.shape)
        for y, x in zip(ys, xs):
            hits.append((float(res[y, x]), ox + int(x) + tw // 2, oy + int(y) + th // 2, sc))
    hits.sort(key=lambda h: -h[0])
    out = []
    for h in hits:
        md = max(6, int(14 * h[3]))
        if all(abs(h[1] - o[1]) > md or abs(h[2] - o[2]) > md for o in out):
            out.append(h)
            if len(out) >= max_hits:
                break
    return out


def _scales(img, rel=REL_SCALES):
    s0 = ui_scale(img)
    return [s0 * f for f in rel]


PROMPT_AREA = (0.25, 0.25, 0.9, 0.9)


TITLE_BOX = (60, 4, 166, 26)


def _prompts(img):
    sub, ox, oy = _region(img, PROMPT_AREA)
    s0 = ui_scale(img)
    scales = sorted({round(s, 3) for s in [s0 * f for f in (0.85, 1.0, 1.15)] + [0.85, 1.0, 1.15]})
    return _match(sub, ox, oy, _tpl("selene_prompt"), scales, 0.6, mask="white", max_hits=3)


def _title_score(img, cx, cy, sc, name):
    t = _tpl(name)
    x0, y0, x1, y1 = TITLE_BOX
    tt = t[y0:y1, x0:x1]
    tt = cv2.resize(tt, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR)
    th, tw = t.shape[:2]
    left, top = cx - tw * sc / 2, cy - th * sc / 2
    pad = max(4, 6 * sc)
    sub, _, _ = _box(img, (left + x0 * sc - pad, top + y0 * sc - pad, left + x1 * sc + pad, top + y1 * sc + pad))
    if sub is None or sub.shape[0] < tt.shape[0] or sub.shape[1] < tt.shape[1]:
        return 0.0
    g = lambda a: cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    return float(np.nan_to_num(cv2.matchTemplate(g(sub), g(tt), cv2.TM_CCOEFF_NORMED)).max())


def prompt_kind(img, hit):
    _, cx, cy, sc = hit
    a = _title_score(img, cx, cy, sc, "selene_prompt")
    b = _title_score(img, cx, cy, sc, "boost_prompt")
    if max(a, b) < 0.5 or abs(a - b) < 0.08:
        return None
    return "selene" if a > b else "boost"


def _prompt_of(img, kind):
    for h in _prompts(img):
        if prompt_kind(img, h) == kind:
            return (h[1], h[2])
    return None


def selene_prompt(img):
    return _prompt_of(img, "selene")


def boost_prompt(img):
    return _prompt_of(img, "boost")


X_AREA = (0.5, 0.03, 0.97, 0.6)


def close_x(img):
    sub, ox, oy = _region(img, X_AREA)
    full = _tpl("close")
    hits = (_match(sub, ox, oy, full, _scales(img, (0.75, 0.9, 1.0, 1.1, 1.25, 1.4)), 0.75, max_hits=3) +
            _match(sub, ox, oy, full[7:-7, 7:-7], _scales(img, (0.75, 0.9, 1.0, 1.1, 1.25, 1.4)), 0.75, max_hits=3))
    hits.sort(key=lambda h: -h[0])
    return (hits[0][1], hits[0][2]) if hits else None


REBIRTH_BTN_AREA = (0.12, 0.45, 0.62, 0.92)
SIDE_AREA = (0.0, 0.15, 0.17, 0.75)


def rebirth_button(img):
    sub, ox, oy = _region(img, REBIRTH_BTN_AREA)
    hits = _match(sub, ox, oy, _tpl("rebirth_btn"), _scales(img, (0.85, 0.92, 1.0, 1.08, 1.15)), 0.72, max_hits=1)
    return (hits[0][1], hits[0][2], hits[0][3]) if hits else None


def side_rebirth_button(img):
    sub, ox, oy = _region(img, SIDE_AREA)
    hits = _match(sub, ox, oy, _tpl("rebirth_side"), _scales(img, (0.85, 0.95, 1.05, 1.15)), 0.4, max_hits=1)
    return (hits[0][1], hits[0][2]) if hits else None


def sacrifice_line_present(img, btn):
    bx, by, sc = btn
    box = (bx - 170 * sc, by + 60 * sc, bx + 660 * sc, by + 165 * sc)
    sub, ox, oy = _box(img, box)
    if _match(sub, ox, oy, _tpl("sacrifice_text"), [sc * f for f in (0.9, 1.0, 1.1)], 0.45,
              mask="orange", max_hits=1):
        return True
    if ocr_ready():
        for t in ocr_texts(img, box, sc):
            letters = re.sub(r"[^a-z]", "", _clean_ocr(t))
            if any(_fuzzy_in(letters, w) for w in ("rebirths", "unlock", "reach", "sacrifice")):
                return True
    return False


SHOP_AREA = (0.15, 0.2, 0.85, 0.82)
CLICK_OFFSET_X = 55


def find_buy_buttons(img, thr=None):
    small = ui_scale(img) < 0.75
    thr = thr if thr is not None else (0.8 if small else 0.85)
    robux_thr = 0.55 if small else 0.78
    sub, ox, oy = _region(img, SHOP_AREA)
    sc_list = _scales(img, (0.75, 0.9, 1.0, 1.1, 1.25, 1.4))
    robux = _match(sub, ox, oy, _tpl("robux"), sc_list, robux_thr)
    found = []
    for kind in ("cash", "gem"):
        for score, x, y, sc in _match(sub, ox, oy, _tpl(kind), sc_list, thr):
            cx = x + int(round(CLICK_OFFSET_X * sc))
            if any(abs(x - r[1]) < 30 * sc and abs(y - r[2]) < 30 * sc for r in robux):
                continue
            if any(abs(cx - r[1]) < 70 * sc and abs(y - r[2]) < 30 * sc for r in robux):
                continue
            found.append((kind, x, y, cx, sc))
    found.sort(key=lambda h: (round(h[2] / max(8, 40 * h[4])), h[1]))
    return found


def still_there(img, kind, x, y, sc):
    pad_x, pad_y = int(40 * sc) + 4, int(30 * sc) + 4
    sub, ox, oy = _box(img, (x - pad_x, y - pad_y, x + pad_x, y + pad_y))
    hits = _match(sub, ox, oy, _tpl(kind), [sc * f for f in (0.9, 1.0, 1.1)], 0.75 if sc < 0.75 else 0.8, max_hits=1)
    return bool(hits) and abs(hits[0][1] - x) <= max(4, 12 * sc) and abs(hits[0][2] - y) <= max(4, 12 * sc)


def card_signature(img, x, y, sc):
    sub, _, _ = _box(img, (x - 45 * sc, y - 150 * sc, x + 150 * sc, y + 24 * sc))
    if sub is None:
        return None
    g = cv2.resize(cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY), (24, 24), interpolation=cv2.INTER_AREA)
    return (g > g.mean()).flatten()


def shop_open(img):
    if rebirth_button(img):
        return False
    return close_x(img) is not None or len(find_buy_buttons(img)) >= 2


def shop_view(img):
    sub, _, _ = _region(img, SHOP_AREA)
    return cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.int16)


STOCK_BOX = (-25, -110, 295, -32)


def stock_status(img, x, y, sc):
    if not ocr_ready():
        return "ok", None
    l, t, r, b = STOCK_BOX
    texts = ocr_texts(img, (x + l * sc, y + t * sc, x + r * sc, y + b * sc), sc)
    counts = [n for n in (_stock_left(t) for t in texts) if n is not None]
    if counts:
        n = min(counts)
        return ("out", None) if n == 0 else ("left", n)
    if any(_says_out_of_stock(t) for t in texts):
        return "out", None
    if any("owned" in re.sub(r"[^a-z]", "", _clean_ocr(t)) for t in texts):
        return "out", None
    return "ok", None


_OCR = {"ready": None}


def _find_tesseract():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cands = [os.path.join(base, "tesseract", "tesseract.exe"),
             r"C:\Program Files\Tesseract-OCR\tesseract.exe",
             r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
             os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
             os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
             shutil.which("tesseract")]
    return next((c for c in cands if c and os.path.exists(c)), None)


def _langs(data_dir):
    if not data_dir:
        return "eng"
    import glob
    stems = []
    for f in sorted(glob.glob(os.path.join(data_dir, "*.traineddata"))):
        name = os.path.splitext(os.path.basename(f))[0]
        if name and name != "osd":
            stems.append(name)
    stems = (["eng"] if "eng" in stems else []) + [n for n in stems if n != "eng"]
    return "+".join(stems) if stems else "eng"


def ocr_lang():
    ocr_ready()
    return _OCR.get("lang", "eng")


def ocr_ready():
    if _OCR["ready"] is None:
        try:
            import pytesseract
            exe = _find_tesseract()
            if not exe:
                raise RuntimeError("Tesseract not installed")
            pytesseract.pytesseract.tesseract_cmd = exe
            root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            data_dir = None
            for d in (os.path.join(os.path.dirname(exe), "tessdata"), os.path.join(root, "tessdata")):
                if os.path.exists(os.path.join(d, "eng.traineddata")):
                    os.environ["TESSDATA_PREFIX"] = d
                    data_dir = d
                    break
            _OCR["lang"] = _langs(data_dir)
            _OCR["mod"] = pytesseract
            _OCR["ready"] = True
        except Exception as e:
            _OCR["ready"] = False
            _OCR["why"] = str(e)
    return _OCR["ready"]


def ocr_texts(img, box, sc):
    sub, _, _ = _box(img, box)
    if sub is None:
        return []
    f = max(2.0, min(6.0, 2.0 / max(sc, 0.2)))
    big = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    a = big.astype(np.int16)
    mx, mn = a.max(axis=2), a.min(axis=2)
    variants = (np.where((mx > 200) & (mx - mn > 110), 0, 255).astype(np.uint8),
                np.where(mx < 40, 0, 255).astype(np.uint8),
                cv2.cvtColor(big, cv2.COLOR_BGR2GRAY))
    tess = _OCR["mod"]
    out = []
    for v in variants:
        try:
            out.append(tess.image_to_string(v, config="--psm 6", lang=_OCR.get("lang", "eng")).lower())
        except Exception:
            pass
    return out


def _clean_ocr(text):
    t = text.lower()
    for a, b in (("1", "l"), ("|", "l"), ("0", "o"), ("5", "s"), ("\u2019", "'"), ("`", "'")):
        t = t.replace(a, b)
    return t


def _fuzzy_in(letters, word, cutoff=0.78):
    L = len(word)
    for ln in (L - 1, L, L + 1):
        for i in range(0, max(1, len(letters) - ln + 1)):
            if difflib.SequenceMatcher(None, letters[i:i + ln], word).ratio() >= cutoff:
                return True
    return False


_SOLD_OUT_WORDS = ("outofstock", "soldout", "nostock", "agotado", "esgotado",
                   "epuise", "epuise", "ausverkauft", "esaurito", "nonstock")


def _says_out_of_stock(text):
    letters = re.sub(r"[^a-z]", "", _clean_ocr(text))
    for i in range(len(letters) - 1):
        if letters[i:i + 2] == "no":
            for j in (i + 2, i + 3):
                if difflib.SequenceMatcher(None, letters[j:j + 5], "stock").ratio() >= 0.8:
                    return True
    for w in _SOLD_OUT_WORDS:
        if w in letters:
            return True
        L = len(w)
        for i in range(0, len(letters) - L + 1):
            if difflib.SequenceMatcher(None, letters[i:i + L], w).ratio() >= 0.88:
                return True
    return False


def _stock_left(text):
    t = text.lower().replace(" ", "")
    m = re.search(r"(?<![0-9])x([0-9]{1,3})(?![0-9])", t)
    if m:
        return int(m.group(1))
    for pat in (r"st[o0]ck[:x]?([0-9]{1,3})", r"([0-9]{1,3})(?:left|inst[o0]ck)"):
        m = re.search(pat, t)
        if m:
            return int(m.group(1))
    return None


LIST_TOP_BELOW_X = 102
LIST_TOP_FRACTION = 313 / REF_H


LIST_HEIGHT = 444


def list_view(img):
    H, W = img.shape[:2]
    top = int(list_top(img)) + 2
    bottom = int(top + LIST_HEIGHT * ui_scale(img)) - 6
    x0, _, x1, _ = SHOP_AREA
    sub = img[max(0, top):min(H, bottom), int(x0 * W):int(x1 * W)]
    return cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.int16)


def list_top(img):
    x = close_x(img)
    if x:
        return x[1] + LIST_TOP_BELOW_X * ui_scale(img)
    return LIST_TOP_FRACTION * img.shape[0]


def stock_text_visible(img, y, sc, top=None):
    top = list_top(img) if top is None else top
    return y + STOCK_BOX[1] * sc >= top


def list_shift(before, after):
    b8, a8 = before.clip(0, 255).astype(np.uint8), after.clip(0, 255).astype(np.uint8)
    if b8.shape != a8.shape:
        return 0, False
    h = b8.shape[0]
    y0, y1 = int(h * 0.72), int(h * 0.95)
    res = cv2.matchTemplate(a8, b8[y0:y1], cv2.TM_CCOEFF_NORMED)[:, 0][:y0 + 1]
    best = float(res.max())
    if best < 0.6:
        return 0, False
    peaks = [i for i in range(len(res)) if res[i] >= best - 0.03 and res[i] == res[max(0, i - 3):i + 4].max()]
    if len({round((y0 - p) / 8) for p in peaks}) > 1:
        return 0, False
    shift = y0 - int(res.argmax())
    if shift > 0 and float(np.abs(before[shift:].astype(int) - after[:h - shift].astype(int)).mean()) > 14:
        return 0, False
    if shift == 0 and float(np.abs(before.astype(int) - after.astype(int)).mean()) > 3:
        return 0, False
    return shift, True

_SAC_HEAD_B64 = (
    "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"
)
_SAC_BTN_B64 = (
    "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"
    "QmCC"
)
_SAC_TPL = {}


def _sac_tpl(name):
    if name not in _SAC_TPL:
        data = _SAC_HEAD_B64 if name == "head" else _SAC_BTN_B64
        _SAC_TPL[name] = cv2.imdecode(np.frombuffer(base64.b64decode(data), np.uint8), cv2.IMREAD_COLOR)
    return _SAC_TPL[name]


def sacrifice_popup(img):
    if img is None:
        return None
    H, W = img.shape[:2]
    f = 640.0 / W if W > 640 else 1.0
    small = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
    head, btn = _sac_tpl("head"), _sac_tpl("btn")
    sw = small.shape[1]
    best = None
    for frac in np.arange(0.30, 1.12, 0.06):
        s = frac * sw / 925.0
        th = cv2.resize(head, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if th.shape[0] < 8 or th.shape[0] >= small.shape[0] or th.shape[1] >= small.shape[1]:
            continue
        res = cv2.matchTemplate(small, th, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score < 0.55:
            continue
        hx, hy = loc[0] + th.shape[1] / 2, loc[1] + th.shape[0] / 2
        ex, ey = hx + 309 * s, hy + 406.5 * s
        tb = cv2.resize(btn, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        pad = max(6, int(30 * s))
        x0, y0 = int(ex - tb.shape[1] / 2 - pad), int(ey - tb.shape[0] / 2 - pad)
        x1, y1 = int(ex + tb.shape[1] / 2 + pad), int(ey + tb.shape[0] / 2 + pad)
        if x0 < 0 or y0 < 0 or x1 > small.shape[1] or y1 > small.shape[0]:
            continue
        r2 = cv2.matchTemplate(small[y0:y1, x0:x1], tb, cv2.TM_CCOEFF_NORMED)
        _, s2, _, _ = cv2.minMaxLoc(r2)
        if s2 >= 0.6 and (best is None or score + s2 > best[0]):
            best = (score + s2, (hx + 309 * s) / f, (hy + 200 * s) / f)
    return (int(best[1]), int(best[2])) if best else None


TOPBAR_AREA = (0.2, 0.0, 0.8, 0.16)
WELCOME_AREA = (0.05, 0.05, 0.75, 0.45)


def shops_button(img):
    sub, ox, oy = _region(img, TOPBAR_AREA)
    hits = _match(sub, ox, oy, _tpl("shops_btn"), _scales(img, (0.85, 0.92, 1.0, 1.08, 1.15)), 0.7, max_hits=1)
    return (hits[0][1], hits[0][2]) if hits else None


def welcome_back(img):
    sub, ox, oy = _region(img, WELCOME_AREA)
    return bool(_match(sub, ox, oy, _tpl("welcome_back"), _scales(img, (0.85, 0.92, 1.0, 1.08, 1.15)),
                       0.6, mask="white", max_hits=1))


DISCONNECT_AREA = (0.25, 0.2, 0.75, 0.8)


def disconnected(img):
    if not ocr_ready():
        return ""
    sub, _, _ = _region(img, DISCONNECT_AREA)
    if sub is None:
        return ""
    sc = ui_scale(img)
    f = max(1.0, min(3.0, 1.2 / max(sc, 0.2)))
    big = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    tess = _OCR["mod"]
    for v in (gray, 255 - gray):
        try:
            text = tess.image_to_string(v, config="--psm 6", lang=_OCR.get("lang", "eng")).lower()
        except Exception:
            continue
        flat = re.sub(r"\s+", " ", text)
        if "error code" in flat or ("disconnected" in flat and ("reconnect" in flat or "leave" in flat)):
            m = re.search(r"error code:?\s*(\d+)", flat)
            return f"error {m.group(1)}" if m else "disconnected"
    return ""
