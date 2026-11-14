"""Spending Analyzer - entry point. Runs 100% offline."""
import logging
import logging.handlers
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))  # bundled pypdf (see vendor/VERSIONS.txt), no install needed
sys.path.insert(0, HERE)

DATA_DIR = os.path.join(os.path.expanduser("~"), ".spending_analyzer")
LOG_PATH = os.path.join(DATA_DIR, "app.log")


def _offline_guard():
    """Belt and braces: make any accidental network connection fail inside this process."""
    import socket

    def blocked(*a, **k):
        raise OSError("Network access is disabled in Spending Analyzer")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked


def _setup_logging():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[h])
    except OSError:
        logging.basicConfig(level=logging.WARNING)


def _show_fatal(msg):
    """Show an error even when started without a console (pythonw on Windows)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("Spending Analyzer", msg)
        r.destroy()
    except Exception:
        print(msg, file=sys.stderr)


def main():
    _setup_logging()
    log = logging.getLogger("main")
    if sys.version_info < (3, 10):
        _show_fatal("Spending Analyzer needs Python 3.10 or newer.\nDownload it from python.org.")
        sys.exit(1)
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        print("Tkinter is missing. On Linux install it with: sudo apt install python3-tk\n"
              "(The python.org installers for Windows and macOS include it.)")
        sys.exit(1)
    _offline_guard()

    def report(exc_type, exc, tb):
        log.error("Unhandled error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        messagebox.showerror("Spending Analyzer",
                             f"Something went wrong: {exc_type.__name__}: {exc}\n\n"
                             f"Details were saved to:\n{LOG_PATH}")

    sys.excepthook = report
    log.info("starting (Python %s)", sys.version.split()[0])
    try:
        from spending_analyzer.gui import App
        root = tk.Tk()
        root.report_callback_exception = report
        App(root)
        root.mainloop()
    except Exception:
        log.exception("fatal error")
        _show_fatal("Spending Analyzer couldn't start:\n\n" + traceback.format_exc(limit=3) +
                    f"\nDetails were saved to {LOG_PATH}")
        sys.exit(1)


if __name__ == "__main__":
    main()
