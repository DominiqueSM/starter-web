"""Colours, fonts and small custom widgets shared by the interface.

Custom widgets are drawn with plain tk Frames/Labels/Canvas so they look the same on Windows,
macOS (where tk.Button ignores colours) and Linux.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

BG = "#F3F5F9"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F8FAFC"
BORDER = "#E3E7EE"
TEXT = "#111827"
MUTED = "#6B7280"
SUBTLE = "#9CA3AF"
ACCENT = "#4F46E5"
ACCENT_HOVER = "#4338CA"
ACCENT_SOFT = "#EEF2FF"
SIDEBAR = "#0F172A"
SIDEBAR_HOVER = "#1E293B"
SIDEBAR_TEXT = "#CBD5E1"
SIDEBAR_MUTED = "#64748B"
GOOD = "#059669"
GOOD_SOFT = "#ECFDF5"
WARN = "#D97706"
WARN_SOFT = "#FFFBEB"
BAD = "#DC2626"
BAD_SOFT = "#FEF2F2"
INFO = "#2563EB"
INFO_SOFT = "#EFF6FF"

PALETTE = ["#4F46E5", "#0EA5E9", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#14B8A6",
           "#F97316", "#6366F1", "#84CC16", "#06B6D4", "#A855F7", "#64748B", "#E11D48", "#22C55E"]

FONTS = {}


def _pick_family():
    have = set(tkfont.families())
    prefs = (["Segoe UI"] if sys.platform.startswith("win") else
             ["SF Pro Text", "Helvetica Neue", "Helvetica"] if sys.platform == "darwin" else
             ["Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans"])
    for f in prefs:
        if f in have:
            return f
    return tkfont.nametofont("TkDefaultFont").actual("family")


def _mono_family():
    have = set(tkfont.families())
    for f in ("Cascadia Mono", "Consolas", "SF Mono", "Menlo", "DejaVu Sans Mono", "Liberation Mono", "Courier New"):
        if f in have:
            return f
    return "TkFixedFont"


def setup(root: tk.Tk):
    fam = _pick_family()
    base = 10 if not sys.platform == "darwin" else 13
    FONTS.update(
        body=(fam, base), small=(fam, base - 1), tiny=(fam, base - 2),
        bold=(fam, base, "bold"), h1=(fam, base + 8, "bold"), h2=(fam, base + 3, "bold"),
        h3=(fam, base + 1, "bold"), kpi=(fam, base + 10, "bold"), brand=(fam, base + 3, "bold"),
        mono=(_mono_family(), base - 1),
    )
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(name).configure(family=fam, size=base)
        except tk.TclError:
            pass
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, font=FONTS["body"], bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, troughcolor=BG, focuscolor=ACCENT)
    s.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, rowheight=30,
                borderwidth=0, relief="flat", font=FONTS["body"])
    s.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT)])
    s.configure("Treeview.Heading", background=SURFACE_ALT, foreground=MUTED, font=FONTS["small"] + ("bold",),
                relief="flat", borderwidth=0, padding=(8, 7))
    s.map("Treeview.Heading", background=[("active", "#EEF1F6")])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("TEntry", fieldbackground=SURFACE, padding=(8, 6), bordercolor=BORDER, lightcolor=BORDER)
    s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
    s.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE, padding=(8, 5), arrowcolor=MUTED,
                bordercolor=BORDER, lightcolor=BORDER)
    s.map("TCombobox", fieldbackground=[("readonly", SURFACE)], selectbackground=[("readonly", SURFACE)],
          selectforeground=[("readonly", TEXT)], bordercolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.font", FONTS["body"])
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    s.configure("Vertical.TScrollbar", background=BG, troughcolor=SURFACE, bordercolor=SURFACE, arrowcolor=MUTED,
                relief="flat", gripcount=0, arrowsize=12)
    s.map("Vertical.TScrollbar", background=[("active", "#D1D5DB")])
    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#E5E7EB", bordercolor=BG,
                lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
    s.configure("TCheckbutton", background=SURFACE, font=FONTS["body"])
    s.map("TCheckbutton", background=[("active", SURFACE)])


class Button(tk.Label):
    """Flat button that honours colours on every platform."""
    STYLES = {
        "primary": (ACCENT, "#FFFFFF", ACCENT_HOVER),
        "secondary": (SURFACE, TEXT, "#F1F5F9"),
        "ghost": (BG, TEXT, "#E8ECF3"),
        "sidebar": (ACCENT, "#FFFFFF", ACCENT_HOVER),
        "sidebar2": (SIDEBAR_HOVER, SIDEBAR_TEXT, "#273449"),
        "danger": (SURFACE, BAD, BAD_SOFT),
    }

    def __init__(self, parent, text, command=None, style="secondary", **kw):
        bg, fg, hover = self.STYLES[style]
        border = style in ("secondary", "danger")
        super().__init__(parent, text=text, bg=bg, fg=fg, font=kw.pop("font", FONTS["bold"]),
                         padx=kw.pop("padx", 14), pady=kw.pop("pady", 7), cursor="hand2",
                         highlightthickness=1 if border else 0, highlightbackground=BORDER, **kw)
        self._colors = (bg, fg, hover)
        self._command = command
        self._enabled = True
        self.bind("<Enter>", lambda e: self._enabled and self.configure(bg=hover))
        self.bind("<Leave>", lambda e: self.configure(bg=bg))
        self.bind("<ButtonRelease-1>", self._click)

    def _click(self, e):
        if self._enabled and self._command and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self._command()

    def set_enabled(self, on: bool):
        self._enabled = on
        bg, fg, _ = self._colors
        self.configure(fg=fg if on else SUBTLE, cursor="hand2" if on else "arrow")


def card(parent, padding=16, **kw):
    """White rounded-looking panel. Returns (outer, inner)."""
    outer = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER, **kw)
    inner = tk.Frame(outer, bg=SURFACE)
    inner.pack(fill="both", expand=True, padx=padding, pady=padding)
    return outer, inner


def pill(parent, text, fg, bg, font=None):
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=font or FONTS["small"] + ("bold",), padx=8, pady=2)


def round_rect(cv: tk.Canvas, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r < 1:
        return cv.create_rectangle(x0, y0, x1, y1, **kw)
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
           x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


class ScrollFrame(tk.Frame):
    """A vertically scrolling frame (used for the insight cards)."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<Button-4>", lambda e: self._wheel(e, -1), add="+")
        self.bind_all("<Button-5>", lambda e: self._wheel(e, 1), add="+")

    def _wheel(self, e, direction=None):
        if not self.winfo_ismapped():
            return
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None and w is not self:
            w = w.master
        if w is None:
            return
        if direction is None:
            direction = -1 if e.delta > 0 else 1
            steps = max(1, abs(e.delta) // 120) if sys.platform.startswith("win") else 1
        else:
            steps = 1
        self.canvas.yview_scroll(direction * steps * 2, "units")

    def scroll_top(self):
        self.canvas.yview_moveto(0)
