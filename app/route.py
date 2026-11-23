import time

from . import win, builtin, purchase


def game_loaded(img):
    return img is not None and (builtin.shops_button(img) is not None or builtin.welcome_back(img))


def wait_loaded(hwnd, timeout=120, stop=lambda: False):
    end = time.time() + timeout
    while time.time() < end and not stop():
        if not win.is_window(hwnd):
            return False
        if game_loaded(win.capture_window(hwnd)):
            return True
        time.sleep(2)
    return False


def close_welcome_back(ctx, timeout=30):
    end = time.time() + timeout
    closed = False
    while time.time() < end:
        img = ctx.shot()
        if purchase.is_open(img):
            if not ctx.dismiss_purchase():
                return False
            continue
        if builtin.welcome_back(img):
            x = builtin.close_x(img)
            if x:
                ctx.log("Closing the Welcome Back pop-up (with its X, not YES).")
                ctx.click(*x)
                closed = True
            ctx.wait(1.5)
            continue
        if builtin.shops_button(img):
            return True
        ctx.wait(1.0)
    return closed
