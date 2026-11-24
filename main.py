import sys
import os
import traceback

if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _crash(exc_text):
    try:
        os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
        with open(os.path.join(HERE, "data", "crash.log"), "a", encoding="utf-8") as f:
            f.write(exc_text + "\n")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("FAAR Manager crashed",
                             exc_text[-1500:] + "\n\n(Saved to data\\crash.log)")
        r.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from app import win
        from app.gui import main
        main()
    except ImportError:
        _crash(traceback.format_exc() + "\nSomething the app needs isn't installed: double-click run.bat once.")
        sys.exit(1)
    except Exception:
        _crash(traceback.format_exc())
        sys.exit(1)
