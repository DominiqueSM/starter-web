"""Spending Analyzer - entry point. Runs 100% offline."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))  # bundled pypdf, no install needed
sys.path.insert(0, HERE)


def _offline_guard():
    """Belt and braces: make any accidental network connection fail inside this process."""
    import socket

    def blocked(*a, **k):
        raise OSError("Network access is disabled in Spending Analyzer")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        print("Spending Analyzer needs Python 3.10 or newer. Download it from python.org.")
        input("Press Enter to close...")
        sys.exit(1)
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("Tkinter is missing. On Linux install it with: sudo apt install python3-tk\n"
              "(The python.org installers for Windows and macOS include it.)")
        sys.exit(1)
    _offline_guard()
    from spending_analyzer.gui import main
    main()
