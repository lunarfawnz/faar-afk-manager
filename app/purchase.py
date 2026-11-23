import base64

import cv2
import numpy as np

_REF_BUTTON_W = 416.0
_X_FROM_RIGHT = 31 / _REF_BUTTON_W
_X_FROM_TOP = 27.5 / _REF_BUTTON_W
_X_TEMPLATE = cv2.imdecode(np.frombuffer(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABcAAAAWCAIAAACkFJBSAAAB8UlEQVQ4EaXBsU7bQBwH4N8/DnsY75YbsENy6atUEQuI2IezgFpV0AdoywBiLm0HVDrUzsVBZEP0VTiH2OkrkLmJk0pIlhIlmfx9xLhAYcS4QGHEuEBhxLhAYcS4QK7ZfPvx7PT45N1o9Bcb2PbO7c+br9ffHx//IEeMC+Qc2+737yaTfy33KE1HWOHYdhSF5fLW/sFhmo6QI8YFFrxpNDqd31k2bbl+kiRY4DhOLwotq6xU+8kYLCDGBZY1pNQ6yLKp6/nDYYJX1arTizqlkqVU+8kYLCPGBVY0pNQ6mM0y1/Ofn4e12m5XB6WS5SnfmBgriHGBdaSsax1gPr+4vDr/8glESrWNibEOMS6wgZR1rYPtSuVlPPY8P44H2IAYF9igXq91u+F2pfIyHnueH8cDbECMC6wjZV3rAPP5xeXV+flnAJ7nx/EA6xDjAiukrHd1OJtlnmoPBs+12m7UDUGkVNuYGCuIcYFlDSm1DmazrOUeDYcJXlWrTi/qlEqWp3xjYiwjxgUWNKTUOsiyacv1kyTBAsdxelFoWWWl2k/GYAExLpCz7Z3+/d10OnFdP0lTrHBsO4rCcnlr/+AwTUfIEeMCub295tnph+OT92k6wga2vfPr9ub624+Hh0fkiHGBwohxgcKIcYHCiHGBwv4DGBS/I7OIacgAAAAASUVORK5CYII="), np.uint8), cv2.IMREAD_COLOR)


def _blue_mask(img):
    b, g, r = img[:, :, 0].astype(np.int16), img[:, :, 1].astype(np.int16), img[:, :, 2].astype(np.int16)
    mask = ((b >= 110) & (b - r >= 70) & (b - g >= 50) & (r <= 110)).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5)))


def _is_panel(px):
    px = px.astype(np.int16)
    return int(px.max()) <= 58 and int(px.max()) - int(px.min()) <= 14


def _panel_fraction(img, x0, x1, y0, y1):
    reg = img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)].astype(np.int16)
    if reg.size == 0:
        return 0.0
    mx, mn = reg.max(axis=2), reg.min(axis=2)
    return float(((mx <= 58) & (mx - mn <= 14)).mean())


def find_buy_button(img):
    if img is None:
        return None
    H, W = img.shape[:2]
    n, _, stats, _ = cv2.connectedComponentsWithStats(_blue_mask(img), connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < W * 0.12 or h < 10:
            continue
        if not (5.0 <= w / h <= 16.0) or area < 0.75 * w * h:
            continue
        above = _panel_fraction(img, x, x + w, y - int(w * 0.25), y - 4)
        below = _panel_fraction(img, x, x + w, y + h + 2, y + h + max(6, int(w * 0.04)))
        if above >= 0.45 and below >= 0.45:
            return int(x), int(y), int(w), int(h)
    return None


def is_open(img):
    return find_buy_button(img) is not None


def _same_colour(px, ref, tol=5):
    return int(np.abs(px.astype(np.int16) - ref.astype(np.int16)).max()) <= tol


def _match_x(img, x0, y0, x1, y1, scale):
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    best = (0.0, 0, 0)
    for f in (0.9, 1.0, 1.1):
        t = cv2.resize(_X_TEMPLATE, None, fx=scale * f, fy=scale * f,
                       interpolation=cv2.INTER_AREA if scale * f < 1 else cv2.INTER_LINEAR)
        sub = img[y0:y1, x0:x1]
        if t.shape[0] < 6 or sub.shape[0] < t.shape[0] or sub.shape[1] < t.shape[1]:
            continue
        res = cv2.matchTemplate(sub, t, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score > best[0]:
            best = (float(score), x0 + loc[0] + t.shape[1] // 2, y0 + loc[1] + t.shape[0] // 2)
    return best


def find_close(img):
    btn = find_buy_button(img)
    if not btn:
        return None
    H, W = img.shape[:2]
    bx, by, bw, bh = btn
    scale = bw / _REF_BUTTON_W
    y_mid = by + bh // 2
    ref = img[y_mid, min(W - 1, bx + bw + max(2, int(4 * scale)))]
    if not _is_panel(ref):
        ref = np.array([31, 26, 25], np.uint8)
    right = bx + bw
    while right + 1 < W and _same_colour(img[y_mid, right + 1], ref):
        right += 1
    col = max(0, right - max(3, int(8 * scale)))
    top, gap, y = by - 1, 0, by - 1
    while y > 0 and gap <= max(3, int(5 * scale)):
        if _same_colour(img[y, col], ref):
            top, gap = y, 0
        else:
            gap += 1
        y -= 1
    ex = int(right - _X_FROM_RIGHT * bw)
    ey = int(top + _X_FROM_TOP * bw)
    pad = max(12, int(bw * 0.07))
    score, cx, cy = _match_x(img, ex - pad, ey - pad, ex + pad, ey + pad, scale)
    if score >= 0.6:
        return cx, cy
    score, cx, cy = _match_x(img, bx + int(bw * 0.6), by - int(bw * 0.75), right + pad, by, scale)
    if score >= 0.7:
        return cx, cy
    return None


def x_still_there(img, xy, scale):
    if img is None or not xy:
        return False
    pad = max(14, int(30 * scale))
    score, _, _ = _match_x(img, xy[0] - pad, xy[1] - pad, xy[0] + pad, xy[1] + pad, scale)
    return score >= 0.6
