import cv2
import numpy as np

REF_H = 1017.0
ROI_W, ROI_H = 70, 16
READY_FRACTION = 0.25


REF_W = 1920.0


def _hud(w, h):
    return min(w / REF_W, h / REF_H)


def _box_at(img, cx, cy):
    h, w = img.shape[:2]
    sc = max(0.3, h / REF_H)
    bw, bh = max(8, int(ROI_W * sc)), max(4, int(ROI_H * sc))
    l, t = int(round(cx - bw / 2)), int(round(cy - bh / 2))
    l, t = max(0, min(w - bw, l)), max(0, min(h - bh, t))
    return l, t, l + bw, t + bh


def _box(img, pos):
    h, w = img.shape[:2]
    return _box_at(img, float(pos[0]) * w, float(pos[1]) * h)


def candidate_boxes(img, pos, ref=None):
    h, w = img.shape[:2]
    boxes = [_box(img, pos)]
    try:
        rw, rh = float(ref[0]), float(ref[1])
    except (TypeError, ValueError, IndexError):
        return boxes
    if rw <= 0 or rh <= 0 or (abs(rw - w) <= 2 and abs(rh - h) <= 2):
        return boxes
    k = _hud(w, h) / _hud(rw, rh)
    px, py = float(pos[0]) * rw, float(pos[1]) * rh
    for ax in (0.0, 0.5, 1.0):
        for ay in (0.0, 0.5, 1.0):
            cx = ax * w + (px - ax * rw) * k
            cy = ay * h + (py - ay * rh) * k
            if 0 <= cx < w and 0 <= cy < h:
                b = _box_at(img, cx, cy)
                if b not in boxes:
                    boxes.append(b)
    return boxes


def valid_pos(pos):
    try:
        return pos is not None and len(pos) == 2 and 0.0 <= float(pos[0]) <= 1.0 and 0.0 <= float(pos[1]) <= 1.0
    except (TypeError, ValueError):
        return False


def _green(img, box, need_text=False):
    l, t, r, b = box
    sub = np.ascontiguousarray(img[t:b, l:r, :3])
    if sub.size == 0:
        return 0.0
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    green = (hsv[:, 0] >= 35) & (hsv[:, 0] <= 85) & (hsv[:, 1] >= 120) & (hsv[:, 2] >= 140)
    if need_text:
        white = (hsv[:, 1] < 45) & (hsv[:, 2] > 200)
        if white.mean() < 0.03:
            return 0.0
    return float(green.mean())


def ready_fraction(img, pos, ref=None):
    if img is None or not valid_pos(pos):
        return 0.0
    boxes = candidate_boxes(img, pos, ref)
    return max(_green(img, b, need_text=i > 0) for i, b in enumerate(boxes))


def is_ready(img, pos, ref=None):
    return ready_fraction(img, pos, ref) >= READY_FRACTION
