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
        base = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else None
        folder = os.path.join(base, "FAAR Manager") if base else os.path.join(HERE, "data")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "crash.log"), "a", encoding="utf-8") as f:
            f.write(exc_text + "\n")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("FAAR Manager crashed",
                             exc_text[-1500:] + "\n\n(Saved to %LOCALAPPDATA%\\FAAR Manager\\crash.log)")
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
