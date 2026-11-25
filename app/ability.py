import cv2
import numpy as np

REF_H = 1017.0
ROI_W, ROI_H = 70, 16
READY_FRACTION = 0.25


def _box(img, pos):
    h, w = img.shape[:2]
    sc = max(0.3, h / REF_H)
    bw, bh = max(8, int(ROI_W * sc)), max(4, int(ROI_H * sc))
    cx, cy = float(pos[0]) * w, float(pos[1]) * h
    l, t = int(round(cx - bw / 2)), int(round(cy - bh / 2))
    l, t = max(0, min(w - bw, l)), max(0, min(h - bh, t))
    return l, t, l + bw, t + bh


def valid_pos(pos):
    try:
        return pos is not None and len(pos) == 2 and 0.0 <= float(pos[0]) <= 1.0 and 0.0 <= float(pos[1]) <= 1.0
    except (TypeError, ValueError):
        return False


def ready_fraction(img, pos):
    if img is None or not valid_pos(pos):
        return 0.0
    l, t, r, b = _box(img, pos)
    sub = np.ascontiguousarray(img[t:b, l:r, :3])
    if sub.size == 0:
        return 0.0
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    green = (hsv[:, 0] >= 35) & (hsv[:, 0] <= 85) & (hsv[:, 1] >= 120) & (hsv[:, 2] >= 140)
    return float(green.mean())


def is_ready(img, pos):
    return ready_fraction(img, pos) >= READY_FRACTION
