"""
Finding things on screen: calibrated targets (image templates and regions)
plus template matching. All coordinates are relative to a window's client area.
"""
import json
import os
import threading
import time

import cv2
import numpy as np

from .storage import CALIB_DIR

# name: (kind, label, help)
TARGETS = {
    # --- buying (shared by Boost shop and Selene) ---
    "cash_icon": ("image", "Cash icon on a buy button",
                  "Crop JUST the $ / cash icon on one of the green buy buttons."),
    "gem_icon": ("image", "Gem icon on a buy button",
                 "Crop JUST the gem icon on a gem buy button."),
    "robux_icon": ("image", "Robux icon on a buy button",
                   "Crop the Robux icon. Buttons near it are NEVER clicked."),
    "close_x": ("image", "Shop close (X) button",
                "Crop the red X that closes shop windows."),
    "shop_region": ("region", "Shop button area (optional)",
                    "Drag a box around where buy buttons appear. Leave empty to search the whole window."),
    "robux_prompt": ("image", "Roblox purchase pop-up (optional extra)",
                     "Already recognised automatically (dark box + blue Buy button). Only capture this if a "
                     "Robux pop-up ever slips past: crop its title."),
    "robux_prompt_cancel": ("image", "Close button on that pop-up (optional extra)",
                            "Already found automatically. Only needed if the X ever isn't found."),
    # --- boost shop ---
    "boost_prompt": ("image", "Boosts stand E prompt",
                     "Stand next to the boosts stand and crop the E prompt that appears (its name / key)."),
    # --- Selene ---
    "selene_prompt": ("image", "Selene's 'Talk' prompt",
                      "Stand next to Selene and crop the prompt that appears (her name / Talk)."),
    # --- rebirth ---
    "rebirth_open": ("image", "Rebirth button",
                     "Crop the button that opens the rebirth menu."),
    "rebirth_confirm": ("image", "Rebirth confirm button",
                        "Open the rebirth menu and crop the button that actually rebirths."),
    "sacrifice_prompt": ("image", "Sacrifice prompt (rebirth 250)",
                         "When it shows, crop its title/question text. The app then leaves it alone and waits for you."),
    # --- Hallow's Eve / Ada ---
    "event_banner": ("image", "Hallow's Eve event banner",
                     "During the event, crop a distinctive part of the banner (e.g. the title text)."),
    "event_region": ("region", "Event banner area (optional)",
                     "Box where the event banner appears. Speeds up and steadies detection."),
    "slot_first": ("region", "Hotbar: first character slot",
                   "Drag a box exactly around the first slot to manage (Ada, slot 2 by default)."),
    "slot_next": ("region", "Hotbar: the slot after it",
                  "Drag a box exactly around the next slot. Used to work out slot spacing."),
    "dracula_label": ("image", "Dracula mutation label",
                      "Crop the [Dracula] label above a character that has it."),
    "mutation_region": ("region", "Area above your character",
                        "Box around where the mutation label shows above your held character."),
}

GROUPS = [
    ("Buying (Boost shop + Selene)", ["cash_icon", "gem_icon", "robux_icon", "close_x",
                                      "shop_region", "robux_prompt", "robux_prompt_cancel"]),
    ("Boost shop", ["boost_prompt"]),
    ("Selene", ["selene_prompt"]),
    ("Rebirth", ["rebirth_open", "rebirth_confirm", "sacrifice_prompt"]),
    ("Hallow's Eve / Ada", ["event_banner", "event_region", "slot_first", "slot_next",
                            "dracula_label", "mutation_region"]),
]

INDEX_FILE = os.path.join(CALIB_DIR, "targets.json")

# Prompts/labels drawn over the 3D world on a see-through background. Besides normal colour
# matching, these are also matched on their bright pixels only (the text and key icon), so
# whatever shows through behind them (water, lighting, day/night) doesn't matter.
# Roblox's E prompts use white text + a white key icon. Matching on "near-white" pixels only
# ignores whatever colourful world shows through the see-through box behind them.
TEXT_TARGETS = {"boost_prompt", "selene_prompt", "sacrifice_prompt"}
WHITE_LEVEL = 195


def bright_only(img):
    """Keep just the near-white parts (text, key icon), as a slightly softened mask."""
    if img is None:
        return None
    v = img.min(axis=2) if img.ndim == 3 else img      # white = all three channels high
    mask = np.where(v >= WHITE_LEVEL, 255, 0).astype(np.uint8)
    return cv2.GaussianBlur(mask, (3, 3), 0)


class Calibration:
    """Stores templates (PNG crops) and regions (fractions of the window)."""

    def __init__(self):
        self._lock = threading.RLock()
        self._tpl_cache = {}
        self.data = {}
        if os.path.exists(INDEX_FILE):
            try:
                with open(INDEX_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def _save(self):
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def has(self, name):
        return name in self.data

    # ---- image variants (several crops of the same thing, e.g. the X in different shops)
    def _variants(self, name):
        d = self.data.get(name)
        if not d or d.get("kind") != "image":
            return []
        if "file" in d and "variants" not in d:          # files saved by the first version
            d["variants"] = [{"file": d.pop("file"), "ref_w": d.get("ref_w"), "ref_h": d.get("ref_h")}]
        return d["variants"]

    def count(self, name):
        return len(self._variants(name))

    def files(self, name):
        return [os.path.join(CALIB_DIR, v["file"]) for v in self._variants(name)]

    def _drop_cache(self, name):
        for k in [k for k in self._tpl_cache if k[0] == name]:
            self._tpl_cache.pop(k, None)

    def clear(self, name):
        with self._lock:
            for path in self.files(name):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self.data.pop(name, None)
            self._drop_cache(name)
            self._save()

    def set_image(self, name, crop_bgr, win_w, win_h, add=False):
        """Save a crop. add=True keeps the existing pictures and adds this one as another option."""
        with self._lock:
            keep_thr = (self.data.get(name) or {}).get("threshold")
            if not add:
                self.clear(name)
            variants = self._variants(name) if add else []
            fname = f"{name}_{int(time.time() * 1000)}.png"
            cv2.imwrite(os.path.join(CALIB_DIR, fname), crop_bgr)
            variants.append({"file": fname, "ref_w": win_w, "ref_h": win_h})
            d = {"kind": "image", "variants": variants}
            if keep_thr:
                d["threshold"] = keep_thr
            self.data[name] = d
            self._drop_cache(name)
            self._save()

    # ---- per-item strictness
    def threshold(self, name, default):
        t = (self.data.get(name) or {}).get("threshold")
        return float(t) if t else float(default)

    def set_threshold(self, name, value):
        with self._lock:
            if name in self.data:
                if value:
                    self.data[name]["threshold"] = float(value)
                else:
                    self.data[name].pop("threshold", None)
                self._save()

    def set_region(self, name, x, y, w, h, win_w, win_h):
        with self._lock:
            self.data[name] = {"kind": "region",
                               "rect": [x / win_w, y / win_h, w / win_w, h / win_h]}
            self._save()

    def region_px(self, name, win_w, win_h):
        """Region in pixels for a window of this size, or None if not set."""
        d = self.data.get(name)
        if not d or d.get("kind") != "region":
            return None
        fx, fy, fw, fh = d["rect"]
        return (int(round(fx * win_w)), int(round(fy * win_h)),
                max(1, int(round(fw * win_w))), max(1, int(round(fh * win_h))))

    def templates(self, name, win_w):
        """Every saved picture of `name`, scaled for a window of this width."""
        out = []
        with self._lock:
            for i, v in enumerate(self._variants(name)):
                key = (name, i, win_w)
                if key not in self._tpl_cache:
                    img = cv2.imread(os.path.join(CALIB_DIR, v["file"]), cv2.IMREAD_COLOR)
                    if img is not None:
                        scale = win_w / float(v.get("ref_w") or win_w)
                        if abs(scale - 1) > 0.02:
                            img = cv2.resize(img, None, fx=scale, fy=scale,
                                             interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
                    self._tpl_cache[key] = img
                if self._tpl_cache[key] is not None:
                    out.append(self._tpl_cache[key])
        return out

    def template(self, name, win_w):
        t = self.templates(name, win_w)
        return t[0] if t else None

    def max_size(self, name, win_w):
        ts = self.templates(name, win_w)
        return (max(t.shape[1] for t in ts), max(t.shape[0] for t in ts)) if ts else (30, 30)

    # ---- finding (matches any of the saved pictures)
    def find_all(self, img, name, default_thr, win_w):
        """win_w = width of the whole Roblox window (templates are scaled by it, not by the crop)."""
        if img is None:
            return []
        thr = self.threshold(name, default_thr)
        hits = []
        img_b = bright_only(img) if name in TEXT_TARGETS else None
        for t in self.templates(name, win_w):
            hits += match_all(img, t, thr)
            if img_b is not None:
                hits += match_all(img_b, bright_only(t), thr)
        hits.sort(key=lambda h: -h[0])
        out = []
        for h in hits:
            md = max(8, min(h[3], h[4]) // 2)
            if all(abs(h[1] - o[1]) > md or abs(h[2] - o[2]) > md for o in out):
                out.append(h)
        return out

    def find(self, img, name, default_thr, win_w):
        hits = self.find_all(img, name, default_thr, win_w)
        return hits[0] if hits else None

    def best_score(self, img, name, win_w):
        """Highest similarity anywhere, even below the threshold (for the Test button)."""
        best = 0.0
        pairs = [(img, t) for t in self.templates(name, win_w)]
        if name in TEXT_TARGETS:
            ib = bright_only(img)
            pairs += [(ib, bright_only(t)) for t in self.templates(name, win_w)]
        for im, t in pairs:
            if t.shape[0] <= im.shape[0] and t.shape[1] <= im.shape[1] and not is_flat(t):
                for sc in (0.92, 1.0, 1.08):
                    tt = t if sc == 1.0 else cv2.resize(t, None, fx=sc, fy=sc)
                    if tt.shape[0] > im.shape[0] or tt.shape[1] > im.shape[1]:
                        continue
                    r = np.nan_to_num(cv2.matchTemplate(im, tt, cv2.TM_CCOEFF_NORMED))
                    best = max(best, float(r.max()))
        return best


def crop(img, rect):
    if rect is None:
        return img, 0, 0
    x, y, w, h = rect
    H, W = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    return img[y0:y1, x0:x1], x0, y0


MAX_CANDIDATES = 400
MAX_RESULTS = 60


def is_flat(crop_bgr):
    """A crop with almost no detail can't be found reliably (it matches everywhere)."""
    return crop_bgr is None or crop_bgr.size == 0 or float(crop_bgr.std()) < 6


def match_all(img, tpl, threshold=0.82, scales=(0.92, 1.0, 1.08), min_dist=None):
    """All places `tpl` appears in `img`: [(score, cx, cy, w, h)], best first, de-duplicated."""
    if img is None or tpl is None or is_flat(tpl):
        return []
    hits = []
    for sc in scales:
        t = tpl if sc == 1.0 else cv2.resize(
            tpl, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR)
        th, tw = t.shape[:2]
        if th < 4 or tw < 4 or th > img.shape[0] or tw > img.shape[1]:
            continue
        res = np.nan_to_num(cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED), nan=0.0,
                            posinf=0.0, neginf=0.0)
        flat = res.ravel()
        idx = np.flatnonzero(flat >= threshold)
        if len(idx) > MAX_CANDIDATES:           # keep only the strongest (avoids slowdowns)
            idx = idx[np.argpartition(flat[idx], -MAX_CANDIDATES)[-MAX_CANDIDATES:]]
        ys, xs = np.unravel_index(idx, res.shape)
        for y, x in zip(ys, xs):
            hits.append((float(res[y, x]), int(x + tw // 2), int(y + th // 2), tw, th))
    hits.sort(key=lambda h: -h[0])
    out = []
    for h in hits:
        md = min_dist or max(8, min(h[3], h[4]) // 2)
        if all(abs(h[1] - o[1]) > md or abs(h[2] - o[2]) > md for o in out):
            out.append(h)
            if len(out) >= MAX_RESULTS:
                break
    return out


def best_match(img, tpl, threshold=0.82):
    hits = match_all(img, tpl, threshold)
    return hits[0] if hits else None


def is_held_blue(px_bgr):
    """The bright blue outline the game draws around the held hotbar item."""
    b, g, r = int(px_bgr[0]), int(px_bgr[1]), int(px_bgr[2])
    return r < 60 and 125 <= g <= 215 and b >= 215


def blue_border_fraction(slot_img, thickness=5):
    """Share of pixels along the slot's border that are the 'held' blue."""
    if slot_img is None or slot_img.size == 0:
        return 0.0
    h, w = slot_img.shape[:2]
    t = max(1, min(thickness, h // 3, w // 3))
    mask = np.zeros((h, w), dtype=bool)
    mask[:t, :] = mask[-t:, :] = True
    mask[:, :t] = mask[:, -t:] = True
    px = slot_img[mask].astype(int)
    b, g, r = px[:, 0], px[:, 1], px[:, 2]
    blue = (r < 60) & (g >= 125) & (g <= 215) & (b >= 215)
    return float(blue.mean()) if len(px) else 0.0


def images_similar(a, b, tol=2.0):
    if a is None or b is None or a.shape != b.shape:
        return False
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()) < tol
