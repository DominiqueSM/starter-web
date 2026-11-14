"""Desktop interface (Tkinter). Runs entirely offline."""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import tkinter as tk
import webbrowser
from collections import defaultdict
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import theme as T
from .categorize import NON_SPENDING, Categorizer, infer_rent
from .checks import missing_statements
from .extract import parse_file, process_folder
from .insights import analyze, money, summarize_groups
from .linking import link
from .gui_planning import PlanningPages
from .planning import apply_tags
from .report import export_csv, export_html

log = logging.getLogger(__name__)

APP_NAME = "Spending Analyzer"
DATA_DIR = os.path.join(os.path.expanduser("~"), ".spending_analyzer")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
ALL_FOLDERS = "All folders"
TOP_LEVEL = "(files not in a subfolder)"
DATE_CHOICES = {"Dates: auto-detect": "auto", "Dates: MM/DD (US)": "MDY", "Dates: DD/MM": "DMY"}

PAGES = [
    ("overview", "Overview", "◉", "Where your money goes"),
    ("cashflow", "Cash flow", "⇅", "Money in vs. money out, month by month, and exactly what was counted"),
    ("insights", "Cut back", "★", "Ranked ideas with estimated savings"),
    ("review", "Needs review", "⚐", "What the app wasn't sure about, one line per company"),
    ("budgets", "Budgets", "◔", "Monthly limits per category, and spending by tag"),
    ("transactions", "Transactions", "≡", "Everything found in your statements"),
    ("recurring", "Recurring", "⟳", "Subscriptions, bills and regular payments, one line per company"),
    ("debt", "Debt payoff", "↘", "When you'll be debt-free, and what paying extra saves"),
    ("folders", "By folder", "▤", "Each subfolder side by side"),
    ("files", "Files & checks", "✓", "What was read from each file, and whether it adds up"),
    ("rules", "Rules & backup", "⚙", "Everything you've taught the app, and backups of it"),
]
RECON_LABEL = {"reconciled": ("✓ Adds up", T.GOOD), "balance-verified": ("✓ Balance checked", T.GOOD),
               "mismatch": ("⚠ Doesn't add up", T.WARN), "unverified": ("– Not checkable", T.MUTED)}
DIAG_STYLE = {"transaction": ("✓", T.GOOD), "continuation": ("+", T.INFO), "header": ("▸", T.ACCENT),
              "section": ("§", T.INFO), "summary": ("Σ", T.MUTED), "skipped": ("✕", T.WARN),
              "info": ("·", T.SUBTLE)}


class App(PlanningPages):
    APP_NAME = APP_NAME
    PAGES = PAGES

    def __init__(self, root: tk.Tk):
        self.root = root
        T.setup(root)
        self.cat = Categorizer(DATA_DIR)
        self.settings = self._load_settings()
        self.file_results = []
        self.transactions = []
        self.analysis = None
        self.passwords = {}
        self.q = queue.Queue()
        self._color_map = {}
        self._sort_state = {}
        self._tx_index = {}
        self._wrap_labels = []
        self.scan_folder = ""
        self.page = None

        root.title(APP_NAME)
        root.geometry(self.settings.get("geometry", "1320x840"))
        root.minsize(1060, 640)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.folder_var = tk.StringVar(value=self.settings.get("folder", ""))
        self.group_var = tk.StringVar(value=ALL_FOLDERS)
        self._build_sidebar()
        self._build_main()
        self._update_folder_label()
        self.show_page("overview")
        self.render_all()

    # ================================================================ settings
    def _load_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            log.warning("could not save settings: %s", e)

    def on_close(self):
        self.settings["geometry"] = self.root.geometry()
        self.settings["folder"] = self.folder_var.get()
        self._save_settings()
        self.root.destroy()

    def color(self, category: str) -> str:
        if category not in self._color_map:
            self._color_map[category] = T.PALETTE[len(self._color_map) % len(T.PALETTE)]
        return self._color_map[category]

    # ================================================================ layout
    def _build_sidebar(self):
        sb = tk.Frame(self.root, bg=T.SIDEBAR, width=236)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)
        top = tk.Frame(sb, bg=T.SIDEBAR)
        top.pack(fill="x", padx=20, pady=(24, 18))
        tk.Label(top, text="◎  Spending Analyzer", bg=T.SIDEBAR, fg="#FFFFFF", font=T.FONTS["brand"]).pack(anchor="w")
        tk.Label(top, text="Private · works offline", bg=T.SIDEBAR, fg=T.SIDEBAR_MUTED,
                 font=T.FONTS["small"]).pack(anchor="w", pady=(4, 0), padx=(30, 0))
        self.nav = {}
        for key, title, icon, _ in PAGES:
            row = tk.Frame(sb, bg=T.SIDEBAR, cursor="hand2")
            row.pack(fill="x", padx=12, pady=1)
            bar = tk.Frame(row, bg=T.SIDEBAR, width=3)
            bar.pack(side="left", fill="y")
            lbl = tk.Label(row, text=f"{icon}   {title}", bg=T.SIDEBAR, fg=T.SIDEBAR_TEXT, font=T.FONTS["body"],
                           anchor="w", padx=14, pady=7, cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True)
            for w in (row, lbl):
                w.bind("<Button-1>", lambda e, k=key: self.show_page(k))
                w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))
            self.nav[key] = (row, bar, lbl)

        tk.Frame(sb, bg=T.SIDEBAR).pack(fill="both", expand=True)
        bottom = tk.Frame(sb, bg=T.SIDEBAR)
        bottom.pack(fill="x", padx=20, pady=20)
        tk.Label(bottom, text="STATEMENTS FOLDER", bg=T.SIDEBAR, fg=T.SIDEBAR_MUTED,
                 font=T.FONTS["tiny"] + ("bold",)).pack(anchor="w")
        self.folder_lbl = tk.Label(bottom, text="", bg=T.SIDEBAR, fg="#FFFFFF", font=T.FONTS["small"],
                                   wraplength=196, justify="left", anchor="w")
        self.folder_lbl.pack(anchor="w", fill="x", pady=(4, 10))
        T.Button(bottom, "Choose folder…", self.browse, style="sidebar2").pack(fill="x")
        self.analyze_btn = T.Button(bottom, "Analyze", self.start_analysis, style="sidebar")
        self.analyze_btn.pack(fill="x", pady=(8, 10))
        self.date_var = tk.StringVar(value=next((k for k, v in DATE_CHOICES.items()
                                                 if v == self.settings.get("date_order", "auto")), "Dates: auto-detect"))
        dc = ttk.Combobox(bottom, textvariable=self.date_var, values=list(DATE_CHOICES), state="readonly")
        dc.pack(fill="x")
        dc.bind("<<ComboboxSelected>>", self._date_order_changed)

    def _nav_hover(self, key, on):
        if key == self.page:
            return
        row, bar, lbl = self.nav[key]
        c = T.SIDEBAR_HOVER if on else T.SIDEBAR
        for w in (row, bar, lbl):
            w.configure(bg=c)

    def _build_main(self):
        main = tk.Frame(self.root, bg=T.BG)
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, bg=T.BG)
        header.pack(fill="x", padx=28, pady=(22, 4))
        left = tk.Frame(header, bg=T.BG)
        left.pack(side="left", fill="x", expand=True)
        self.title_lbl = tk.Label(left, text="", bg=T.BG, fg=T.TEXT, font=T.FONTS["h1"], anchor="w")
        self.title_lbl.pack(anchor="w")
        self.subtitle_lbl = tk.Label(left, text="", bg=T.BG, fg=T.MUTED, font=T.FONTS["body"], anchor="w")
        self.subtitle_lbl.pack(anchor="w", pady=(2, 0))
        right = tk.Frame(header, bg=T.BG)
        right.pack(side="right")
        T.Button(right, "Export report", self.export_html).pack(side="right")
        T.Button(right, "Export CSV", self.export_csv).pack(side="right", padx=8)
        self.group_combo = ttk.Combobox(right, textvariable=self.group_var, state="readonly", width=24,
                                        values=[ALL_FOLDERS])
        self.group_combo.pack(side="right", padx=(0, 6))
        self.group_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        tk.Label(right, text="Show", bg=T.BG, fg=T.MUTED, font=T.FONTS["small"]).pack(side="right", padx=6)

        status = tk.Frame(main, bg=T.BG)
        status.pack(fill="x", padx=28, pady=(6, 10))
        self.status_lbl = tk.Label(status, text="", bg=T.BG, fg=T.MUTED, font=T.FONTS["small"], anchor="w")
        self.status_lbl.pack(side="left")
        self.progress = ttk.Progressbar(status, length=220, mode="determinate")

        content = tk.Frame(main, bg=T.BG)
        content.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        self.pages = {}
        for key, *_ in PAGES:
            f = tk.Frame(content, bg=T.BG)
            f.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = f
        self._build_overview(self.pages["overview"])
        self._build_cashflow(self.pages["cashflow"])
        self._build_insights(self.pages["insights"])
        self._build_transactions(self.pages["transactions"])
        self._build_recurring(self.pages["recurring"])
        self._build_folders(self.pages["folders"])
        self._build_files(self.pages["files"])
        self._build_budgets(self.pages["budgets"])
        self._build_debt(self.pages["debt"])
        self._build_rules(self.pages["rules"])
        self._build_review(self.pages["review"])

    def show_page(self, key):
        self.page = key
        for k, (row, bar, lbl) in self.nav.items():
            on = k == key
            for w in (row, lbl):
                w.configure(bg=T.SIDEBAR_HOVER if on else T.SIDEBAR)
            lbl.configure(fg="#FFFFFF" if on else T.SIDEBAR_TEXT, font=T.FONTS["bold"] if on else T.FONTS["body"])
            bar.configure(bg=T.ACCENT if on else T.SIDEBAR)
        title, sub = next((t, s) for k, t, _, s in PAGES if k == key)
        if key == "insights":
            title = "What to cut back on"
        self.title_lbl.configure(text=title)
        self.subtitle_lbl.configure(text=sub)
        self.pages[key].tkraise()

    def set_status(self, text, color=None):
        self.status_lbl.configure(text=text, fg=color or T.MUTED)

    # ---------------------------------------------------------------- table helper
    def _table(self, parent, cols):
        """cols: list of (id, heading, width, anchor, stretch). Returns treeview inside a card."""
        outer, inner = T.card(parent, padding=1)
        tv = ttk.Treeview(inner, columns=[c[0] for c in cols], show="headings", selectmode="extended")
        for cid, head, w, anchor, stretch in cols:
            tv.heading(cid, text=head, anchor=anchor, command=lambda c=cid, t=tv: self.sort_tree(t, c))
            tv.column(cid, width=w, minwidth=40, anchor=anchor, stretch=stretch)
        ys = ttk.Scrollbar(inner, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        tv.tag_configure("odd", background=T.SURFACE_ALT)
        tv.tag_configure("credit", foreground=T.GOOD)
        tv.tag_configure("muted", foreground=T.SUBTLE)
        tv.tag_configure("warn", foreground=T.WARN)
        tv.tag_configure("bad", foreground=T.BAD)
        tv.tag_configure("bold", font=T.FONTS["bold"])
        return outer, tv

    @staticmethod
    def _restripe(tv):
        for i, iid in enumerate(tv.get_children("")):
            tags = [t for t in tv.item(iid, "tags") if t != "odd"]
            if i % 2:
                tags.append("odd")
            tv.item(iid, tags=tags)

    def sort_tree(self, tv, col):
        rev = self._sort_state.get((id(tv), col), False)
        items = [(tv.set(k, col), k) for k in tv.get_children("")]

        def key(v):
            s = v[0].replace(",", "").replace("$", "").replace("+", "").strip()
            try:
                return (0, float(s), "")
            except ValueError:
                return (1, 0.0, s.lower())
        items.sort(key=key, reverse=rev)
        for idx, (_, k) in enumerate(items):
            tv.move(k, "", idx)
        self._sort_state[(id(tv), col)] = not rev
        self._restripe(tv)

    # ================================================================ overview
    def _build_overview(self, page):
        # Empty state
        self.ov_empty, inner = T.card(page, padding=40)
        tk.Label(inner, text="◎", bg=T.SURFACE, fg=T.ACCENT, font=(T.FONTS["h1"][0], 40)).pack(pady=(10, 4))
        tk.Label(inner, text="See where your money goes", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["h1"]).pack()
        tk.Label(inner, text="Choose the folder that holds your bank and credit-card statement PDFs.\n"
                             "Subfolders (one per card or account) are read too. Everything stays on this computer.",
                 bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["body"], justify="center").pack(pady=(8, 18))
        row = tk.Frame(inner, bg=T.SURFACE)
        row.pack()
        T.Button(row, "Choose folder…", self.browse).pack(side="left", padx=4)
        T.Button(row, "Analyze", self.start_analysis, style="primary").pack(side="left", padx=4)

        self.ov_main = tk.Frame(page, bg=T.BG)
        kp = tk.Frame(self.ov_main, bg=T.BG)
        kp.pack(fill="x")
        self.kpis = {}
        for i, name in enumerate(["Spent", "Average per month", "Money in", "Could save", "Statements checked"]):
            kp.columnconfigure(i, weight=1, uniform="kpi")
            outer, inner = T.card(kp, padding=14)
            outer.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 4 else 6))
            tk.Label(inner, text=name.upper(), bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["tiny"] + ("bold",)).pack(anchor="w")
            v = tk.Label(inner, text="-", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["kpi"], anchor="w")
            v.pack(anchor="w", fill="x", pady=(4, 0))
            sub = tk.Label(inner, text="", bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["small"], anchor="w",
                           justify="left", wraplength=170)
            sub.pack(anchor="w", fill="x")
            inner.bind("<Configure>", lambda e, a=sub: a.configure(wraplength=max(80, e.width - 4)))
            self.kpis[name] = (v, sub, outer)
        self.kpis["Statements checked"][2].bind("<Button-1>", lambda e: self.show_page("files"))

        charts = tk.Frame(self.ov_main, bg=T.BG)
        charts.pack(fill="both", expand=True, pady=12)
        charts.columnconfigure(0, weight=5, uniform="c")
        charts.columnconfigure(1, weight=4, uniform="c")
        charts.rowconfigure(0, weight=1)
        o1, i1 = T.card(charts, padding=16)
        o1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(i1, text="Where your money goes", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["h3"]).pack(anchor="w")
        tk.Label(i1, text="Average per month · click a bar to see its transactions", bg=T.SURFACE, fg=T.MUTED,
                 font=T.FONTS["small"]).pack(anchor="w")
        self.cat_canvas = tk.Canvas(i1, bg=T.SURFACE, highlightthickness=0, height=280)
        self.cat_canvas.pack(fill="both", expand=True, pady=(10, 0))
        o2, i2 = T.card(charts, padding=16)
        o2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tk.Label(i2, text="Monthly spending", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["h3"]).pack(anchor="w")
        self.mon_sub = tk.Label(i2, text="Hover a bar for details", bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["small"])
        self.mon_sub.pack(anchor="w")
        self.mon_canvas = tk.Canvas(i2, bg=T.SURFACE, highlightthickness=0, height=280)
        self.mon_canvas.pack(fill="both", expand=True, pady=(10, 0))
        self.cat_canvas.bind("<Configure>", lambda e: self.draw_category_chart())
        self.mon_canvas.bind("<Configure>", lambda e: self.draw_month_chart())
        self.mon_canvas.bind("<Motion>", self._month_hover)
        self.mon_canvas.bind("<Leave>", lambda e: self.mon_canvas.delete("tip"))
        self.cat_canvas.bind("<Button-1>", self._category_click)
        self.cat_canvas.bind("<Motion>", self._category_cursor)

        o3, self.top_sugg = T.card(self.ov_main, padding=16)
        o3.pack(fill="x")

    def render_overview(self):
        a = self.analysis
        if not a or not self.transactions:
            self.ov_main.pack_forget()
            self.ov_empty.pack(fill="x", pady=40, padx=80)
            return
        self.ov_empty.pack_forget()
        self.ov_main.pack(fill="both", expand=True)
        span = f"{a.first_date:%b %Y} – {a.last_date:%b %Y}" if a.first_date else ""
        self._kpi("Spent", money(a.total_spent), span)
        self._kpi("Average per month", money(a.total_spent / a.months), f"over {a.months:.0f} months")
        c = a.compare
        if c and c["money_in"] > 0:
            n = len(c["months"])
            share = c["spent"] / c["money_in"]
            self._kpi("Money in", money(c["money_in"] / n),
                      f"a month · you spend {share:.0%} of it", T.BAD if share > 1 else None)
        else:
            self._kpi("Money in", "–", "add a checking statement")
        self._kpi("Could save", money(a.potential_monthly_savings),
                  f"a month · {money(a.potential_monthly_savings * 12)} a year", T.GOOD)
        files = [r for r in self._scoped_files() if r.transactions]
        ok = sum(1 for r in files if r.info.recon_status in ("reconciled", "balance-verified"))
        bad = sum(1 for r in files if r.info.recon_status == "mismatch")
        self._kpi("Statements checked", f"{ok} / {len(files)}",
                  f"{bad} don't add up – see Files" if bad else "add up to their balances",
                  T.WARN if bad else (T.GOOD if ok == len(files) else None))
        self.draw_category_chart()
        self.draw_month_chart()
        for w in self.top_sugg.winfo_children():
            w.destroy()
        head = tk.Frame(self.top_sugg, bg=T.SURFACE)
        head.pack(fill="x")
        tk.Label(head, text="Top ideas to cut back", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["h3"]).pack(side="left")
        lnk = tk.Label(head, text="See all →", bg=T.SURFACE, fg=T.ACCENT, font=T.FONTS["bold"], cursor="hand2")
        lnk.pack(side="right")
        lnk.bind("<Button-1>", lambda e: self.show_page("insights"))
        top = [s for s in a.suggestions if s.kind != "info"][:4]
        for s in top:
            r = tk.Frame(self.top_sugg, bg=T.SURFACE)
            r.pack(fill="x", pady=(8, 0))
            dot = {"warn": T.WARN, "save": T.GOOD}.get(s.kind, T.INFO)
            tk.Label(r, text="●", bg=T.SURFACE, fg=dot, font=T.FONTS["small"]).pack(side="left")
            tk.Label(r, text=s.title, bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["body"]).pack(side="left", padx=8)
            if s.monthly_savings >= 1:
                T.pill(r, f"save ~{money(s.monthly_savings)}/mo", T.GOOD, T.GOOD_SOFT).pack(side="right")
        if not top:
            tk.Label(self.top_sugg, text="Nothing stands out. Nice.", bg=T.SURFACE, fg=T.MUTED).pack(anchor="w")

    def _kpi(self, name, value, sub, color=None):
        v, s, _ = self.kpis[name]
        v.configure(text=value, fg=color or T.TEXT)
        s.configure(text=sub)

    def draw_category_chart(self):
        cv = self.cat_canvas
        cv.delete("all")
        self._cat_hits = []
        a = self.analysis
        if not a or not a.spending:
            return
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 50:
            return
        rows = [(c, v / a.months) for c, v in a.by_category]
        if len(rows) > 11:
            rows = rows[:10] + [("Everything else", sum(v for _, v in rows[10:]))]
        f = T.FONTS["small"]
        from tkinter import font as tkfont
        meas = tkfont.Font(font=f)
        label_w = min(190, 12 + max(meas.measure(c) for c, _ in rows))
        val_w = 120
        row_h = max(24, min(34, H / max(len(rows), 1)))
        mx = max(v for _, v in rows) or 1
        total = sum(v for _, v in rows) or 1
        track = W - label_w - val_w
        for i, (c, v) in enumerate(rows):
            y = i * row_h + row_h / 2
            cv.create_text(label_w - 10, y, text=c, anchor="e", fill=T.TEXT, font=f)
            T.round_rect(cv, label_w, y - 6, label_w + track, y + 6, 6, fill="#F1F5F9", outline="")
            bw = max(8, track * v / mx)
            col = T.SUBTLE if c == "Everything else" else self.color(c)
            T.round_rect(cv, label_w, y - 6, label_w + bw, y + 6, 6, fill=col, outline="")
            cv.create_text(label_w + track + 10, y, text=f"{money(v)}", anchor="w", fill=T.TEXT, font=T.FONTS["bold"])
            cv.create_text(W - 2, y, text=f"{v / total:.0%}", anchor="e", fill=T.MUTED, font=f)
            if c != "Everything else":
                self._cat_hits.append((y - row_h / 2, y + row_h / 2, c))

    def _category_at(self, y):
        return next((c for y0, y1, c in getattr(self, "_cat_hits", []) if y0 <= y <= y1), None)

    def _category_cursor(self, e):
        self.cat_canvas.configure(cursor="hand2" if self._category_at(e.y) else "")

    def _category_click(self, e):
        c = self._category_at(e.y)
        if c:
            self.search_var.set("")
            self.cat_filter.set(c)
            self.render_transactions()
            self.show_page("transactions")

    def draw_month_chart(self):
        cv = self.mon_canvas
        cv.delete("all")
        self._mon_bars = []
        a = self.analysis
        if not a or not a.spending:
            return
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 50:
            return
        months = a.by_month[-18:]
        mx = max(v for _, v in months) or 1
        nice = 10 ** (len(str(int(mx))) - 1)
        top_v = ((mx // nice) + 1) * nice
        left, base, topm = 52, H - 26, 12
        for k in range(4):
            v = top_v * k / 3
            y = base - (base - topm) * v / top_v
            cv.create_line(left, y, W, y, fill="#EEF1F5")
            cv.create_text(left - 8, y, text=f"${v / 1000:.0f}k" if top_v >= 3000 else f"${v:,.0f}", anchor="e",
                           fill=T.MUTED, font=T.FONTS["tiny"])
        slot = (W - left) / max(len(months), 1)
        bw = max(6, min(46, slot * 0.6))
        for i, (m, v) in enumerate(months):
            cx = left + slot * (i + 0.5)
            h = (base - topm) * v / top_v
            T.round_rect(cv, cx - bw / 2, base - h, cx + bw / 2, base, min(6, bw / 2), fill=T.ACCENT, outline="",
                         tags=("bar", f"b{i}"))
            cv.create_rectangle(cx - bw / 2, base - min(h, 6), cx + bw / 2, base, fill=T.ACCENT, outline="",
                                tags=("bar", f"b{i}"))
            if len(months) <= 12 or i % 2 == 0:
                import calendar
                lbl = calendar.month_abbr[int(m[5:])] + (f" '{m[2:4]}" if m.endswith("-01") or i == 0 else "")
                cv.create_text(cx, base + 13, text=lbl, fill=T.MUTED, font=T.FONTS["tiny"])
            self._mon_bars.append((cx - slot / 2, cx + slot / 2, m, v, i))
        avg = a.total_spent / a.months
        ya = base - (base - topm) * avg / top_v
        cv.create_line(left, ya, W, ya, fill=T.WARN, dash=(5, 4), width=1)
        self.mon_sub.configure(text=f"Dashed line: average {money(avg)} · hover a bar for details")

    def _month_hover(self, e):
        cv = self.mon_canvas
        cv.delete("tip")
        hit = next((b for b in getattr(self, "_mon_bars", []) if b[0] <= e.x <= b[1]), None)
        cv.itemconfigure("bar", fill=T.ACCENT)
        if not hit:
            return
        _, _, m, v, i = hit
        cv.itemconfigure(f"b{i}", fill=T.ACCENT_HOVER)
        cats = sorted(self.analysis.by_month_category.get(m, {}).items(), key=lambda kv: -kv[1])[:3]
        lines = [f"{m}   {money(v)}"] + [f"{c}: {money(x)}" for c, x in cats]
        w, h = 220, 16 * len(lines) + 14
        x = min(e.x + 14, cv.winfo_width() - w - 4)
        y = max(4, e.y - h - 8)
        T.round_rect(cv, x, y, x + w, y + h, 8, fill=T.SIDEBAR, outline="", tags="tip")
        for k, line in enumerate(lines):
            cv.create_text(x + 12, y + 14 + k * 16, text=line, anchor="w", fill="#FFFFFF" if k == 0 else T.SIDEBAR_TEXT,
                           font=T.FONTS["bold"] if k == 0 else T.FONTS["small"], tags="tip")

    # ================================================================ cash flow
    def _build_cashflow(self, page):
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=3)
        page.rowconfigure(4, weight=2)
        so, self.cf_summary = T.card(page, padding=16)
        so.grid(row=0, column=0, sticky="ew")
        tk.Label(page, text="Only whole months covered by your statements are compared (others are greyed out). "
                            "* Moved in / card payments / transfers / savings are money between your own accounts. "
                            "Card payments, transfers between your accounts and money moved to savings are shown "
                            "but not counted as spending. Refunds are subtracted from spending. Money from a person (e.g. "
                            "Zelle) counts as money in; if it's their share of bills, set its category to "
                            "'Shared bills (paid back)' and it lowers your spending instead.",
                 bg=T.BG, fg=T.MUTED, font=T.FONTS["small"], justify="left", anchor="w",
                 wraplength=1000).grid(row=1, column=0, sticky="ew", pady=(10, 8))
        outer, self.cf_tree = self._table(page, [
            ("Month", "Month", 72, "w", False), ("In", "Money in", 85, "e", False),
            ("Pay", "of which pay", 84, "e", False), ("MovedIn", "Moved in*", 76, "e", False),
            ("Spent", "Spent", 85, "e", False),
            ("Cards", "on cards", 75, "e", False), ("Bank", "from bank", 78, "e", False),
            ("Net", "Left over", 85, "e", False), ("Rate", "Saved %", 66, "e", False),
            ("Refunds", "Refunds", 70, "e", False), ("CardPay", "Card pmts*", 80, "e", False),
            ("Transfers", "Transfers*", 80, "e", False), ("Saved", "Savings*", 72, "e", False),
            ("Note", "", 60, "w", True)])
        outer.grid(row=2, column=0, sticky="nsew")
        bottom = tk.Frame(page, bg=T.BG)
        bottom.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        bottom.columnconfigure(0, weight=1, uniform="cf")
        bottom.columnconfigure(1, weight=1, uniform="cf")
        bottom.rowconfigure(1, weight=1)
        tk.Label(bottom, text="Where money in came from", bg=T.BG, fg=T.TEXT, font=T.FONTS["h3"]).grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        tk.Label(bottom, text="* Not counted as spending", bg=T.BG, fg=T.TEXT, font=T.FONTS["h3"]).grid(
            row=0, column=1, sticky="w", pady=(0, 6), padx=(12, 0))
        o1, self.cf_in = self._table(bottom, [("From", "From", 140, "w", True), ("Type", "Counted as", 170, "w", False),
                                              ("Times", "Times", 50, "center", False), ("Total", "Total", 95, "e", False)])
        o1.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        o2, self.cf_out = self._table(bottom, [("To", "To", 150, "w", True), ("Why", "Why", 150, "w", False),
                                               ("Times", "Times", 50, "center", False), ("Total", "Total", 95, "e", False)])
        o2.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        for tv in (self.cf_in, self.cf_out):
            tv.bind("<Double-1>", lambda e, t=tv: self._cf_drill(t))

    def _cf_drill(self, tv):
        sel = tv.selection()
        if sel:
            self.search_var.set(tv.set(sel[0], "#1"))
            self.cat_filter.set("All categories")
            self.show_credits.set(True)
            self.show_hidden.set(True)
            self.render_transactions()
            self.show_page("transactions")

    def render_cashflow(self):
        for w in self.cf_summary.winfo_children():
            w.destroy()
        for tv in (self.cf_tree, self.cf_in, self.cf_out):
            tv.delete(*tv.get_children())
        a = self.analysis
        if not a or not self.transactions:
            tk.Label(self.cf_summary, text="Run an analysis first.", bg=T.SURFACE, fg=T.MUTED).pack(anchor="w")
            return
        c = a.compare
        row = tk.Frame(self.cf_summary, bg=T.SURFACE)
        row.pack(fill="x")
        if c and c["months"]:
            n = len(c["months"])
            inn, out = c["money_in"] / n, c["spent"] / n
            for label, val, col in [("Money in / month", money(inn), T.TEXT), ("Spent / month", money(out), T.TEXT),
                                    ("Left over / month", money(inn - out), T.GOOD if inn >= out else T.BAD)] + (
                    [(f"Savings rate · last {len(a.savings['months'])} full mo.", f"{a.savings['rate']:.0%}",
                      T.GOOD if a.savings["rate"] >= 0.2 else (T.WARN if a.savings["rate"] >= 0 else T.BAD))]
                    if a.savings else []):
                box = tk.Frame(row, bg=T.SURFACE)
                box.pack(side="left", padx=(0, 36))
                tk.Label(box, text=label.upper(), bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["tiny"] + ("bold",)).pack(anchor="w")
                tk.Label(box, text=val, bg=T.SURFACE, fg=col, font=T.FONTS["kpi"]).pack(anchor="w")
            note = f"Compared over {n} month(s): {c['months'][0]} to {c['months'][-1]}"
            if c["left_out"]:
                note += f" · {len(c['left_out'])} partly covered month(s) left out"
            tk.Label(self.cf_summary, text=note, bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["small"],
                     anchor="w").pack(anchor="w", pady=(8, 0))
        else:
            tk.Label(row, text="No bank statements found, so there's no money-in to compare with. Add your "
                               "checking account statements.", bg=T.SURFACE, fg=T.WARN, font=T.FONTS["body"]).pack(anchor="w")
        f = lambda v: f"{v:,.2f}" if v else ""
        for i, r in enumerate(a.cashflow):
            tags = [] if r["has_bank"] else ["muted"]
            note = "" if r["has_bank"] else ("partial month" if r.get("partial") else "card only")
            if r["has_bank"] and r["spent"] > r["money_in"]:
                tags.append("bad")
            if i % 2:
                tags.append("odd")
            net = r["money_in"] - r["spent"]
            self.cf_tree.insert("", "end", tags=tags, values=(
                r["month"], f(r["money_in"]), f(r["income"]), f(r.get("moved_in", 0)), f(r["spent"]), f(r["spent_card"]), f(r["spent_bank"]),
                f"{net:,.2f}" if r["has_bank"] else "", f"{r['rate']:.0%}" if r.get("rate") is not None else "",
                f(r["refunds"]), f(r["card_payments"]), f(r["transfers"]), f(r["saved"]), note))
        from collections import defaultdict as dd
        from .insights import NOT_MONEY_IN, _is_refund
        live = [t for t in self._scoped() if not t.excluded and not t.duplicate]
        ins, outs = dd(lambda: [0, 0.0, ""]), dd(lambda: [0, 0.0, ""])
        for t in live:
            if t.is_credit and t.category == "Shared bills (paid back)":
                k = ins[t.merchant]
                k[0] += 1; k[1] += t.amount; k[2] = "Paid back (lowers spending)"
            elif t.is_credit and t.category in NOT_MONEY_IN and t.kind != "card":
                k = ins[t.merchant]
                k[0] += 1; k[1] += t.amount; k[2] = "Your other account (not new)"
            elif t.is_credit and t.category not in NOT_MONEY_IN and t.kind != "card" and not _is_refund(t):
                k = ins[t.merchant]
                k[0] += 1; k[1] += t.amount
                k[2] = ("Pay / income" if t.category == "Income" else
                        "From a person" if t.category == "Zelle / Venmo / Cash App" else "Other money in")
            elif not t.is_credit and t.category in NON_SPENDING:
                k = outs[t.merchant]
                k[0] += 1; k[1] += t.amount
                k[2] = ("Saved / invested" if t.category == "Savings & Investments" else
                        "Card payment (matched)" if t.transfer_match else "Transfer / card payment")
        for tv, data in ((self.cf_in, ins), (self.cf_out, outs)):
            for i, (m, (n, tot, why)) in enumerate(sorted(data.items(), key=lambda kv: -kv[1][1])):
                tv.insert("", "end", tags=["odd"] if i % 2 else [], values=(m, why, n, f"{tot:,.2f}"))

    # ================================================================ insights
    def _build_insights(self, page):
        self.ins_scroll = T.ScrollFrame(page)
        self.ins_scroll.pack(fill="both", expand=True)
        self.ins_scroll.body.bind("<Configure>", self._rewrap, add="+")

    def _rewrap(self, e=None):
        w = max(300, self.ins_scroll.body.winfo_width() - 110)
        for lbl in self._wrap_labels:
            try:
                lbl.configure(wraplength=w)
            except tk.TclError:
                pass

    def render_insights(self):
        body = self.ins_scroll.body
        for w in body.winfo_children():
            w.destroy()
        self._wrap_labels = []
        a = self.analysis
        if not a or not a.spending:
            tk.Label(body, text="Run an analysis to see suggestions.", bg=T.BG, fg=T.MUTED,
                     font=T.FONTS["body"]).pack(anchor="w", pady=20)
            return
        # Summary banner
        ban = tk.Frame(body, bg=T.ACCENT)
        ban.pack(fill="x", pady=(0, 14), padx=(0, 6))
        bi = tk.Frame(ban, bg=T.ACCENT)
        bi.pack(fill="x", padx=22, pady=18)
        tk.Label(bi, text=f"You could save about {money(a.potential_monthly_savings)} a month",
                 bg=T.ACCENT, fg="#FFFFFF", font=T.FONTS["h2"]).pack(anchor="w")
        tk.Label(bi, text=f"That's {money(a.potential_monthly_savings * 12)} a year. Estimates come from your own "
                          "spending patterns using realistic cuts, not perfection.",
                 bg=T.ACCENT, fg="#E0E7FF", font=T.FONTS["body"]).pack(anchor="w", pady=(4, 0))
        for s in a.suggestions:
            self._suggestion_card(body, s)
        self._rewrap()
        self.ins_scroll.scroll_top()

    def _suggestion_card(self, parent, s):
        stripe = {"warn": T.WARN, "save": T.GOOD, "info": T.INFO}[s.kind]
        outer = tk.Frame(parent, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.BORDER)
        outer.pack(fill="x", pady=6, padx=(0, 6))
        tk.Frame(outer, bg=stripe, width=4).pack(side="left", fill="y")
        inner = tk.Frame(outer, bg=T.SURFACE)
        inner.pack(side="left", fill="both", expand=True, padx=18, pady=14)
        top = tk.Frame(inner, bg=T.SURFACE)
        top.pack(fill="x")
        tk.Label(top, text=s.title, bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["h3"]).pack(side="left")
        conf_col = {"high": (T.GOOD, T.GOOD_SOFT), "medium": (T.WARN, T.WARN_SOFT), "low": (T.MUTED, "#F3F4F6")}
        fg, bg = conf_col.get(s.confidence, conf_col["medium"])
        T.pill(top, f"{s.confidence} confidence", fg, bg, T.FONTS["tiny"] + ("bold",)).pack(side="right")
        if s.monthly_savings >= 1:
            T.pill(top, f"save ~{money(s.monthly_savings)}/mo · {money(s.monthly_savings * 12)}/yr",
                   T.GOOD, T.GOOD_SOFT).pack(side="right", padx=6)
        d = tk.Label(inner, text=s.detail, bg=T.SURFACE, fg="#374151", font=T.FONTS["body"], justify="left",
                     anchor="w")
        d.pack(fill="x", anchor="w", pady=(6, 0))
        self._wrap_labels.append(d)
        if s.items:
            box = tk.Frame(inner, bg=T.SURFACE)
            box.pack(fill="x", pady=(8, 0))
            more = tk.Frame(inner, bg=T.SURFACE)
            shown = s.items[:6] if not s.item_ids else s.items
            for k, it in enumerate(shown):
                row = tk.Frame(box, bg=T.SURFACE)
                row.pack(anchor="w", fill="x")
                tk.Label(row, text="•  " + it, bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["small"], anchor="w",
                         justify="left").pack(side="left")
                if s.item_ids and k < len(s.item_ids):
                    lnk = tk.Label(row, text="Not a duplicate", bg=T.SURFACE, fg=T.ACCENT, cursor="hand2",
                                   font=T.FONTS["small"] + ("bold",))
                    lnk.pack(side="left", padx=12)
                    lnk.bind("<Button-1>", lambda e, ids=s.item_ids[k]: self.mark_not_duplicate(ids))
            if len(s.items) > 6 and not s.item_ids:
                for it in s.items[6:]:
                    tk.Label(more, text="•  " + it, bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["small"],
                             anchor="w").pack(anchor="w")
                toggle = tk.Label(inner, text=f"Show all {len(s.items)} ▾", bg=T.SURFACE, fg=T.ACCENT,
                                  font=T.FONTS["small"] + ("bold",), cursor="hand2")
                toggle.pack(anchor="w", pady=(4, 0))

                def flip(e, m=more, t=toggle, n=len(s.items)):
                    if m.winfo_ismapped():
                        m.pack_forget()
                        t.configure(text=f"Show all {n} ▾")
                    else:
                        m.pack(fill="x", before=t)
                        t.configure(text="Show fewer ▴")
                toggle.bind("<Button-1>", flip)

    # ================================================================ transactions
    def _build_transactions(self, page):
        bar_o, card_in = T.card(page, padding=10)
        bar_o.pack(fill="x", pady=(0, 10))
        bar = tk.Frame(card_in, bg=T.SURFACE)
        bar.pack(fill="x")
        tk.Label(bar, text="Search", bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["small"]).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.render_transactions())
        ttk.Entry(bar, textvariable=self.search_var, width=22).pack(side="left", padx=(6, 10))
        self.cat_filter = tk.StringVar(value="All categories")
        self.cat_combo = ttk.Combobox(bar, textvariable=self.cat_filter, state="readonly", width=24)
        self.cat_combo.pack(side="left")
        self.cat_combo.bind("<<ComboboxSelected>>", lambda e: self.render_transactions())
        T.Button(bar, "Set category…", self.set_category_dialog, style="primary").pack(side="right")
        T.Button(bar, "Exclude", self.toggle_exclude).pack(side="right", padx=6)
        T.Button(bar, "Flip in/out", self.toggle_direction).pack(side="right")
        row2 = tk.Frame(card_in, bg=T.SURFACE)
        row2.pack(fill="x", pady=(8, 0))
        self.show_credits = tk.BooleanVar(value=False)
        self.show_hidden = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="Show money in", variable=self.show_credits,
                        command=self.render_transactions).pack(side="left")
        ttk.Checkbutton(row2, text="Show transfers, card payments & duplicates", variable=self.show_hidden,
                        command=self.render_transactions).pack(side="left", padx=14)
        T.Button(row2, "Not a duplicate", self.toggle_not_duplicate, font=T.FONTS["small"] + ("bold",),
                 pady=4).pack(side="right")
        T.Button(row2, "Tag…", self.tag_dialog, font=T.FONTS["small"] + ("bold",), pady=4).pack(side="right", padx=6)
        self.tag_filter = tk.StringVar(value="All tags")
        self.tag_combo = ttk.Combobox(row2, textvariable=self.tag_filter, state="readonly", width=16,
                                      values=["All tags"])
        self.tag_combo.pack(side="left", padx=(0, 6))
        self.tag_combo.bind("<<ComboboxSelected>>", lambda e: self.render_transactions())
        tk.Label(row2, text="Exclude hides a row from all totals; select it again to bring it back.", bg=T.SURFACE,
                 fg=T.SUBTLE, font=T.FONTS["tiny"]).pack(side="right", padx=10)
        outer, self.tx_tree = self._table(page, [
            ("Date", "Date", 92, "w", False), ("Description", "Description", 280, "w", True),
            ("Company", "Company", 150, "w", False), ("Category", "Category", 170, "w", False),
            ("Amount", "Amount", 90, "e", False), ("Folder", "From statement", 170, "w", False),
            ("Tags", "Tags", 110, "w", False), ("Note", "Note", 150, "w", True)])
        outer.pack(fill="both", expand=True)
        self.tx_tree.bind("<Double-1>", lambda e: self.set_category_dialog())
        self.tx_sum = tk.Label(page, text="", bg=T.BG, fg=T.MUTED, font=T.FONTS["small"], anchor="w")
        self.tx_sum.pack(fill="x", pady=(8, 0))

    def render_transactions(self):
        tv = self.tx_tree
        tv.delete(*tv.get_children())
        self._tx_index = {}
        q = self.search_var.get().strip().lower()
        c = self.cat_filter.get()
        rows = []
        for t in self._scoped():
            hidden = t.duplicate or t.category in NON_SPENDING and not t.is_credit
            if hidden and not self.show_hidden.get():
                continue
            if t.is_credit and not self.show_credits.get() and not (hidden and self.show_hidden.get()):
                continue
            if c and c != "All categories" and t.category != c:
                continue
            if q and q not in t.description.lower() and q not in t.category.lower() and q not in t.merchant.lower() \
                    and not any(q in g.lower() for g in t.tags):
                continue
            tg = self.tag_filter.get()
            if tg and tg != "All tags" and tg not in t.tags:
                continue
            rows.append(t)
        rows.sort(key=lambda t: t.date, reverse=True)
        total = 0.0
        src_mark = {"guess": " ?", "none": " ?", "learned": " ★", "matched": " ⇄"}
        for i, t in enumerate(rows):
            tags = []
            if t.excluded or t.duplicate:
                tags.append("muted")
            elif t.is_credit:
                tags.append("credit")
            if i % 2:
                tags.append("odd")
            note = t.note or ("excluded" if t.excluded else "")
            amt = f"+{t.amount:,.2f}" if t.is_credit else f"{t.amount:,.2f}"
            iid = str(i)
            self._tx_index[iid] = t
            tv.insert("", "end", iid=iid, tags=tags, values=(
                t.date.isoformat(), t.description, t.merchant, t.category + src_mark.get(t.category_source, ""),
                amt, os.path.basename(t.source_file), ", ".join(t.tags), note))
            if t.is_spending and t.category not in NON_SPENDING:
                total += t.amount
        self.tx_sum.configure(text=f"{len(rows)} shown · spending in view {money(total)}   ·   "
                                   "? = broad guess   ★ = your choice   ⇄ = matched transfer   ·   "
                                   "Double-click a row to change its category")

    # ================================================================ recurring
    def _build_recurring(self, page):
        top = tk.Frame(page, bg=T.BG)
        top.pack(fill="x", pady=(0, 10))
        self.rec_filter = tk.StringVar(value="All")
        self.rec_tabs = {}
        for name in ("All", "Subscriptions", "Bills & loans", "Regular spending"):
            b = tk.Label(top, text=name, bg=T.BG, fg=T.MUTED, font=T.FONTS["bold"], padx=14, pady=6, cursor="hand2")
            b.pack(side="left", padx=(0, 4))
            b.bind("<Button-1>", lambda e, n=name: (self.rec_filter.set(n), self.render_recurring()))
            self.rec_tabs[name] = b
        self.rec_sum = tk.Label(top, text="", bg=T.BG, fg=T.TEXT, font=T.FONTS["bold"])
        self.rec_sum.pack(side="right")
        outer, self.rec_tree = self._table(page, [
            ("Company", "Company", 230, "w", True), ("Type", "Type", 110, "w", False),
            ("Category", "Category", 170, "w", False), ("Frequency", "Frequency", 110, "w", False),
            ("Amount", "Amount", 90, "e", False), ("Per year", "Per year", 100, "e", False),
            ("Times", "Times", 60, "center", False), ("Last", "Last charged", 100, "w", False),
            ("Note", "Note", 240, "w", True)])
        outer.pack(fill="both", expand=True)
        self.rec_tree.bind("<Double-1>", self._rec_drill)
        tk.Label(page, text="Double-click a row to see its transactions and which statement each came from.",
                 bg=T.BG, fg=T.MUTED, font=T.FONTS["small"]).pack(anchor="w", pady=(8, 0))

    def _rec_drill(self, e=None):
        sel = self.rec_tree.selection()
        if not sel:
            return
        self.search_var.set(self.rec_tree.set(sel[0], "Company"))
        self.cat_filter.set("All categories")
        self.show_hidden.set(True)
        self.render_transactions()
        self.show_page("transactions")

    def render_recurring(self):
        sel = self.rec_filter.get()
        for n, b in self.rec_tabs.items():
            on = n == sel
            b.configure(bg=T.SURFACE if on else T.BG, fg=T.ACCENT if on else T.MUTED,
                        highlightthickness=1 if on else 0, highlightbackground=T.BORDER)
        kind_of = {"Subscriptions": "Subscription", "Bills & loans": "Bill / loan", "Regular spending": "Regular"}
        tv = self.rec_tree
        tv.delete(*tv.get_children())
        recs = self.analysis.recurring if self.analysis else []
        if sel != "All":
            recs = [r for r in recs if r.kind == kind_of[sel]]
        for i, r in enumerate(recs):
            notes = []
            if r.price_change:
                notes.append(f"price up {money(r.price_change[0])} → {money(r.price_change[1])}")
            if r.aliases:
                notes.append("also listed as " + ", ".join(r.aliases))
            tags = ["warn"] if r.price_change else []
            if i % 2:
                tags.append("odd")
            tv.insert("", "end", tags=tags, values=(
                r.merchant, r.kind, r.category, r.frequency, f"{r.typical_amount:,.2f}", f"{r.monthly_cost * 12:,.2f}",
                r.count, r.last_date.isoformat(), "; ".join(notes)))
        tot = sum(r.monthly_cost for r in recs)
        self.rec_sum.configure(text=f"{len(recs)} recurring · {money(tot)}/month · {money(tot * 12)}/year")

    # ================================================================ folders
    def _build_folders(self, page):
        tk.Label(page, text="Each subfolder of the chosen folder is a group (e.g. one per card or account). "
                            "Moved in / out is money between your own accounts (e.g. checking to savings): it isn't "
                            "new money or spending. Double-click a row to look at just that folder.", bg=T.BG, fg=T.MUTED,
                 font=T.FONTS["small"], wraplength=1000, justify="left", anchor="w").pack(anchor="w", fill="x",
                                                                                         pady=(0, 8))
        outer, self.group_tree = self._table(page, [
            ("Folder", "Folder", 160, "w", True), ("Files", "Files", 50, "center", False),
            ("Transactions", "Rows", 50, "center", False), ("Spent", "Spent", 90, "e", False),
            ("Per month", "Per month", 80, "e", False), ("Money in", "New money in", 100, "e", False),
            ("MovedIn", "Moved in", 80, "e", False), ("MovedOut", "Moved out", 85, "e", False),
            ("Fees", "Fees", 60, "e", False), ("Top", "Biggest category", 130, "w", False),
            ("Period", "Period", 120, "w", False)])
        outer.pack(fill="both", expand=True)
        self.group_tree.bind("<Double-1>", self._open_group)

    def _open_group(self, e=None):
        sel = self.group_tree.selection()
        if not sel:
            return
        g = self.group_tree.set(sel[0], "Folder")
        self.group_var.set(ALL_FOLDERS if g == ALL_FOLDERS else g)
        self.refresh()
        self.show_page("overview")

    def render_folders(self):
        tv = self.group_tree
        tv.delete(*tv.get_children())
        if not self.transactions:
            return
        for i, g in enumerate(summarize_groups([t for t in self.transactions], self.file_results, ALL_FOLDERS)):
            period = f"{g['first']:%b '%y} – {g['last']:%b '%y}" if g["first"] else "–"
            tags = ["bold"] if g["name"] == ALL_FOLDERS else []
            if i % 2:
                tags.append("odd")
            tv.insert("", "end", tags=tags, values=(
                g["name"], g["files"], g["transactions"], f"{g['spent']:,.2f}", f"{g['per_month']:,.2f}",
                f"{g['money_in']:,.2f}", f"{g['moved_in']:,.2f}", f"{g['moved_out']:,.2f}", f"{g['fees']:,.2f}",
                g["top_category"], period))

    # ================================================================ files
    def _build_files(self, page):
        page.rowconfigure(1, weight=3)
        page.rowconfigure(3, weight=2)
        page.columnconfigure(0, weight=1)
        top = tk.Frame(page, bg=T.BG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.files_note = tk.Label(top, text="Select a file to see how each line was read.", bg=T.BG, fg=T.MUTED,
                                   font=T.FONTS["small"], justify="left", anchor="w")
        self.files_note.pack(side="left")
        self.pw_btn = T.Button(top, "Enter password…", self.ask_password_selected)
        self.pw_btn.pack(side="right")
        T.Button(top, "Include / skip file", self.toggle_include_file).pack(side="right", padx=8)
        outer, self.file_tree = self._table(page, [
            ("File", "File", 300, "w", True), ("Account", "Account", 190, "w", False),
            ("Period", "Period", 190, "w", False), ("Check", "Check", 150, "w", False),
            ("Rows", "Rows", 60, "center", False), ("Notes", "Notes", 320, "w", True)])
        outer.grid(row=1, column=0, sticky="nsew")
        self.file_tree.bind("<<TreeviewSelect>>", lambda e: self.render_preview())
        hdr = tk.Frame(page, bg=T.BG)
        hdr.grid(row=2, column=0, sticky="ew", pady=(14, 6))
        tk.Label(hdr, text="Line-by-line preview", bg=T.BG, fg=T.TEXT, font=T.FONTS["h3"]).pack(side="left")
        legend = tk.Frame(hdr, bg=T.BG)
        legend.pack(side="right")
        for k, lab in [("transaction", "transaction"), ("continuation", "description continued"),
                       ("skipped", "skipped"), ("header", "column headings"), ("summary", "totals")]:
            sym, col = DIAG_STYLE[k]
            tk.Label(legend, text=f"{sym} {lab}", bg=T.BG, fg=col, font=T.FONTS["small"]).pack(side="left", padx=6)
        po, pi = T.card(page, padding=1)
        po.grid(row=3, column=0, sticky="nsew")
        self.preview = tk.Text(pi, wrap="none", relief="flat", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["mono"],
                               padx=12, pady=10, height=10, cursor="arrow", highlightthickness=0)
        ys = ttk.Scrollbar(pi, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.preview.pack(fill="both", expand=True)
        for k, (sym, col) in DIAG_STYLE.items():
            self.preview.tag_configure(k, foreground=col)
        self.preview.tag_configure("text", foreground=T.TEXT)
        self.preview.tag_configure("reason", foreground=T.MUTED)
        self.preview.tag_configure("title", font=T.FONTS["bold"], foreground=T.TEXT)
        self.preview.configure(state="disabled")

    def render_files(self):
        gaps = getattr(self, "gaps", [])
        if gaps:
            shown = "\n".join(f"⚠ Missing: {g.account}, {g.start:%b %d, %Y} – {g.end:%b %d, %Y} "
                              f"(about {g.months} statement{'s' if g.months != 1 else ''})" for g in gaps[:4])
            more = f"\n…and {len(gaps) - 4} more (see Cut back)" if len(gaps) > 4 else ""
            self.files_note.configure(text=shown + more, fg=T.WARN, font=T.FONTS["bold"])
        else:
            self.files_note.configure(text="No gaps between statements. Select a file to see how each line was read.",
                                      fg=T.MUTED, font=T.FONTS["small"])
        tv = self.file_tree
        tv.delete(*tv.get_children())
        self._file_index = {}
        base = self.scan_folder or self.folder_var.get() or "."
        for i, r in enumerate(self.file_results):
            info = r.info
            check, _ = RECON_LABEL.get(info.recon_status, ("", T.MUTED))
            if r.status != "ok":
                check = {"password": "Locked", "duplicate": "Duplicate file", "no-text": "No text",
                         "not-statement": "Not a statement" + (" (included)" if r.transactions else ""),
                         "no-transactions": "Nothing found", "error": "Error"}.get(r.status, r.status)
            acct = info.account_key or " ".join(x for x in [info.bank, {"card": "card", "bank": "account"}.get(
                info.kind, "")] if x)
            period = (f"{info.period_start:%b %d} – {info.period_end:%b %d, %Y}" if info.period_start
                      else (f"closing {info.period_end:%b %d, %Y}" if info.period_end else ""))
            notes = r.note
            if r.status == "ok" and info.recon_status == "mismatch":
                notes = info.recon_detail
            if r.duplicates_removed:
                notes = (notes + "; " if notes else "") + f"{r.duplicates_removed} rows also in another statement"
            tags = []
            if r.status in ("error", "no-text", "no-transactions", "password") or info.recon_status == "mismatch":
                tags.append("warn")
            elif r.status == "duplicate":
                tags.append("muted")
            if i % 2:
                tags.append("odd")
            iid = str(i)
            self._file_index[iid] = r
            tv.insert("", "end", iid=iid, tags=tags, values=(
                os.path.relpath(r.path, base), acct, period, check, len(r.transactions) or len(r.held) or 0, notes))
        self.render_preview()

    def render_preview(self):
        p = self.preview
        p.configure(state="normal")
        p.delete("1.0", "end")
        sel = self.file_tree.selection()
        r = self._file_index.get(sel[0]) if sel and hasattr(self, "_file_index") else None
        if not r:
            p.insert("end", "Select a file above.", "reason")
        else:
            p.insert("end", os.path.basename(r.path) + "\n", "title")
            i = r.info
            bits = [x for x in [i.bank, {"card": "credit card", "bank": "bank account"}.get(i.kind, ""),
                                f"…{i.last4}" if i.last4 else "", f"dates {i.date_order}",
                                f"read by {r.method}" if r.method else ""] if x]
            p.insert("end", " · ".join(bits) + "\n", "reason")
            if i.recon_detail:
                p.insert("end", i.recon_detail + "\n", "reason")
            if r.note:
                p.insert("end", r.note + "\n", "reason")
            p.insert("end", "\n")
            page = None
            for d in r.diags:
                if d.page != page:
                    page = d.page
                    p.insert("end", f"── page {page + 1} ──\n", "reason")
                sym, _ = DIAG_STYLE.get(d.status, ("·", T.SUBTLE))
                p.insert("end", f" {sym}  ", d.status)
                p.insert("end", d.text, "text" if d.status != "info" else "info")
                if d.reason:
                    p.insert("end", f"     ← {d.reason}", "reason")
                p.insert("end", "\n")
        p.configure(state="disabled")

    # ================================================================ data flow
    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder_var.get() or os.path.expanduser("~"),
                                    title="Choose the folder with your statement PDFs")
        if d:
            self.folder_var.set(d)
            self._update_folder_label()
            self.start_analysis()

    def _update_folder_label(self):
        f = self.folder_var.get()
        self.folder_lbl.configure(text=os.path.basename(f.rstrip("/\\")) or f if f else "None chosen yet")

    def _date_order_changed(self, e=None):
        self.settings["date_order"] = DATE_CHOICES[self.date_var.get()]
        self._save_settings()
        if self.transactions:
            self.start_analysis()

    def start_analysis(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            self.browse() if not folder else messagebox.showwarning(APP_NAME, "That folder doesn't exist anymore.")
            return
        self.settings["folder"] = folder
        self._save_settings()
        self._update_folder_label()
        self.scan_folder = folder
        self.analyze_btn.set_enabled(False)
        self.set_status("Reading statements…")
        self.progress.pack(side="right")
        self.progress["value"] = 0
        order = self.settings.get("date_order", "auto")

        def work():
            try:
                res = process_folder(folder, progress=lambda i, n, name: self.q.put(("progress", i, n, name)),
                                     passwords=self.passwords, cache_dir=CACHE_DIR, order_pref=order)
                self.q.put(("done", res))
            except Exception as ex:
                log.exception("analysis failed")
                self.q.put(("error", f"{type(ex).__name__}: {ex}"))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(80, self.poll)

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    _, i, n, name = msg
                    self.progress["maximum"] = max(n, 1)
                    self.progress["value"] = i
                    if name:
                        self.set_status(f"Reading {i + 1} of {n}: {name}")
                elif msg[0] == "done":
                    self.analysis_finished(msg[1])
                    return
                elif msg[0] == "error":
                    self.analyze_btn.set_enabled(True)
                    self.progress.pack_forget()
                    messagebox.showerror(APP_NAME, msg[1])
                    return
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def _group_of(self, path):
        rel = os.path.relpath(path, self.scan_folder or ".")
        parts = rel.split(os.sep)
        return parts[0] if len(parts) > 1 else TOP_LEVEL

    def analysis_finished(self, results):
        self.analyze_btn.set_enabled(True)
        self.progress.pack_forget()
        self.file_results = results
        self.rebuild()
        n_ok = sum(1 for r in results if r.transactions)
        locked = [r for r in results if r.status == "password"]
        mism = sum(1 for r in results if r.transactions and r.info.recon_status == "mismatch")
        if not results:
            self.set_status("No PDF files found in that folder (subfolders included).", T.WARN)
        else:
            msg = f"Read {len(results)} files · {len(self.transactions)} transactions from {n_ok} statements"
            if mism:
                msg += f" · {mism} don't add up (see Files & checks)"
            self.set_status(msg, T.WARN if mism else T.MUTED)
        if results and not self.transactions and not locked:
            self.show_page("files")
        if locked and messagebox.askyesno(
                APP_NAME, f"{len(locked)} statement(s) are password-protected. Enter the password(s) now?\n\n"
                          "Passwords are only kept in memory while the app is open."):
            self.ask_passwords(locked)

    def toggle_include_file(self):
        sel = self.file_tree.selection()
        r = self._file_index.get(sel[0]) if sel and hasattr(self, "_file_index") else None
        if not r or r.status != "not-statement":
            messagebox.showinfo(APP_NAME, "Select a file marked 'Not a statement' first.\n\nThose are documents like "
                                          "hotel bills, receipts or loan statements whose charges are already on "
                                          "your bank/card statements.")
            return
        inc = set(self.settings.get("include_files", []))
        (inc.discard if r.sha1 in inc else inc.add)(r.sha1)
        self.settings["include_files"] = sorted(inc)
        self._save_settings()
        self.rebuild()

    def ask_password_selected(self):
        sel = self.file_tree.selection()
        r = self._file_index.get(sel[0]) if sel and hasattr(self, "_file_index") else None
        if not r or r.status != "password":
            messagebox.showinfo(APP_NAME, "Select a file marked Locked in the list first.")
            return
        self.ask_passwords([r])

    def ask_passwords(self, files):
        todo = []
        for r in files:
            pw = simpledialog.askstring(APP_NAME, f"Password for {os.path.basename(r.path)}:", show="*",
                                        parent=self.root)
            if pw:
                self.passwords[r.path] = pw
                todo.append(r)
        if not todo:
            return
        order = self.settings.get("date_order", "auto")
        for r in todo:
            new = parse_file(r.path, r.sha1, order, self.passwords[r.path], None)
            if new.status == "password":
                messagebox.showwarning(APP_NAME, f"Wrong password for {os.path.basename(r.path)}.")
                self.passwords.pop(r.path, None)
                continue
            self.file_results[self.file_results.index(r)] = new
        self.rebuild()

    def rebuild(self):
        """Categorise, link transfers/duplicates and apply the user's corrections, from scratch."""
        include = set(self.settings.get("include_files", []))
        for r in self.file_results:
            if r.status == "not-statement" or r.held:
                r.transactions = list(r.held) if r.sha1 in include else []
            r.group = self._group_of(r.path)
            r.duplicates_removed = 0
            for t in r.transactions:
                t.group = r.group
                t.duplicate = t.transfer_match = False
                t.note = ""
                if t.parsed_credit is None:
                    t.parsed_credit = t.is_credit
                t.is_credit = t.parsed_credit
        self.transactions = [t for r in self.file_results for t in r.transactions]
        self._assign_uids()
        ex = set(self.settings.get("excluded", []))
        flips = set(self.settings.get("direction_flips", []))
        for t in self.transactions:
            t.excluded = t.uid in ex
            if t.uid in flips:
                t.is_credit = not t.is_credit
        self.cat.apply(self.transactions)
        not_dup = set(self.settings.get("not_duplicates", []))
        for t in self.transactions:
            t.not_duplicate = t.uid in not_dup
        one_offs = self.settings.get("tx_categories", {})
        for t in self.transactions:
            if t.uid in one_offs:
                t.category, t.category_source = one_offs[t.uid], "learned"
        link(self.file_results)
        infer_rent(self.transactions)
        apply_tags(self.transactions, self.settings.get("tag_rules", []))
        groups = sorted({r.group for r in self.file_results if r.transactions},
                        key=lambda g: (g == TOP_LEVEL, g.lower()))
        self.group_combo["values"] = [ALL_FOLDERS] + groups
        if self.group_var.get() not in self.group_combo["values"]:
            self.group_var.set(ALL_FOLDERS)
        self.refresh()

    def _assign_uids(self):
        seen = defaultdict(int)
        for t in self.transactions:   # stable id that survives description clean-up changes
            base = f"{t.account or t.group}|{t.date}|{t.amount:.2f}"
            seen[base] += 1
            t.uid = base if seen[base] == 1 else f"{base}#{seen[base]}"

    def _scoped(self):
        g = self.group_var.get()
        if not g or g == ALL_FOLDERS:
            return self.transactions
        return [t for t in self.transactions if t.group == g]

    def _scoped_files(self):
        g = self.group_var.get()
        return [r for r in self.file_results if not g or g == ALL_FOLDERS or r.group == g]

    def refresh(self):
        scoped = self._scoped()
        good = {r.path for r in self.file_results if r.info.recon_status in ("reconciled", "balance-verified")}
        quality = (sum(1 for t in scoped if t.source_file in good) / len(scoped)) if scoped else 1.0
        coverage = []
        for r in self._scoped_files():
            if r.transactions:
                ds = [t.date for t in r.transactions]
                coverage.append((r.info.kind, r.info.period_start or min(ds), r.info.period_end or max(ds),
                                 r.info.account_key or f"{r.group}|{r.info.kind}"))
        self.gaps = missing_statements(self._scoped_files())
        self.analysis = analyze(scoped, quality, coverage, budgets=self.settings.get("budgets"), gaps=self.gaps)
        tags = ["All tags"] + sorted({g for t in scoped for g in t.tags})
        self.tag_combo["values"] = tags
        if self.tag_filter.get() not in tags:
            self.tag_filter.set("All tags")
        cats = ["All categories"] + sorted({t.category for t in scoped})
        self.cat_combo["values"] = cats
        if self.cat_filter.get() not in cats:
            self.cat_filter.set("All categories")
        self.render_all()

    def render_all(self):
        self.render_overview()
        self.render_cashflow()
        self.render_insights()
        self.render_transactions()
        self.render_recurring()
        self.render_folders()
        self.render_files()
        self.render_budgets()
        self.render_debt()
        self.render_rules()
        self.render_review()

    # ================================================================ edits
    def _selected(self):
        return [self._tx_index[i] for i in self.tx_tree.selection() if i in self._tx_index]

    def set_category_dialog(self):
        sel = self._selected()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select one or more transactions first.")
            return
        win = tk.Toplevel(self.root, bg=T.SURFACE)
        win.title("Set category")
        win.transient(self.root)
        win.resizable(False, False)
        body = tk.Frame(win, bg=T.SURFACE)
        body.pack(fill="both", expand=True, padx=22, pady=18)
        merchants = sorted({t.merchant for t in sel})
        tk.Label(body, text="Set category", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["h2"]).pack(anchor="w")
        tk.Label(body, text=f"{len(sel)} transaction(s) from {', '.join(merchants)[:90]}", bg=T.SURFACE,
                 fg=T.MUTED, font=T.FONTS["small"], wraplength=380, justify="left").pack(anchor="w", pady=(4, 12))
        var = tk.StringVar(value=sel[0].category)
        cb = ttk.Combobox(body, textvariable=var, values=self.cat.all_categories(), width=38)
        cb.pack(anchor="w")
        tk.Label(body, text="Pick one, or type a new category name.", bg=T.SURFACE, fg=T.MUTED,
                 font=T.FONTS["tiny"]).pack(anchor="w", pady=(4, 8))
        tk.Label(body, text="Apply to", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["bold"]).pack(anchor="w", pady=(6, 2))
        scope = tk.StringVar(value="company")
        ttk.Radiobutton(body, text=f"Every transaction from {merchants[0] if len(merchants) == 1 else 'these companies'}"
                                   " (remembered)", variable=scope, value="company").pack(anchor="w")
        crow = tk.Frame(body, bg=T.SURFACE)
        crow.pack(anchor="w", fill="x")
        ttk.Radiobutton(crow, text="Every transaction whose description contains", variable=scope,
                        value="contains").pack(side="left")
        first_word = (sel[0].description.split() or [""])[0]
        contains = tk.StringVar(value=first_word)
        ent = ttk.Entry(body, textvariable=contains, width=30)
        ent.pack(anchor="w", padx=(24, 0), pady=(2, 0))
        count_lbl = tk.Label(body, text="", bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["tiny"])
        count_lbl.pack(anchor="w", padx=(24, 0))

        def recount(*_):
            txt = contains.get().strip().upper()
            n = sum(1 for t in self.transactions if txt and txt in t.description.upper()) if txt else 0
            count_lbl.configure(text=f"matches {n} transaction(s) \u00B7 remembered for future statements")
        contains.trace_add("write", lambda *a: (scope.set("contains"), recount()))
        recount()
        ttk.Radiobutton(body, text="Only the selected transaction(s)", variable=scope, value="only").pack(
            anchor="w", pady=(4, 0))

        def ok():
            c = var.get().strip()
            if not c:
                return
            how = scope.get()
            if how == "company":
                for m in merchants:
                    self.cat.set_override(m, c)
            elif how == "contains":
                txt = contains.get().strip()
                if len(txt) < 3:
                    messagebox.showwarning(APP_NAME, "Type at least 3 characters to match on.", parent=win)
                    return
                self.cat.add_rule(txt, c)
            else:
                one_offs = self.settings.setdefault("tx_categories", {})
                for t in sel:
                    one_offs[t.uid] = c
                self._save_settings()
            win.destroy()
            self.rebuild()

        btns = tk.Frame(body, bg=T.SURFACE)
        btns.pack(fill="x", pady=(16, 0))
        T.Button(btns, "Save", ok, style="primary").pack(side="right")
        T.Button(btns, "Cancel", win.destroy).pack(side="right", padx=8)
        win.bind("<Return>", lambda e: ok())
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()
        cb.focus_set()

    def mark_not_duplicate(self, uids, on=True):
        nd = set(self.settings.get("not_duplicates", []))
        for u in uids:
            (nd.add if on else nd.discard)(u)
        self.settings["not_duplicates"] = sorted(nd)
        self._save_settings()
        self.rebuild()

    def toggle_not_duplicate(self):
        sel = self._selected()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select the transaction(s) that are not duplicates first.")
            return
        nd = set(self.settings.get("not_duplicates", []))
        turn_on = not all(t.uid in nd for t in sel)
        self.mark_not_duplicate([t.uid for t in sel], on=turn_on)
        self.set_status(("Marked as not a duplicate: counted normally." if turn_on else
                         "Duplicate check turned back on for the selection."), T.GOOD)

    def toggle_exclude(self):
        sel = self._selected()
        if not sel:
            return
        ex = set(self.settings.get("excluded", []))
        for t in sel:
            (ex.discard if t.uid in ex else ex.add)(t.uid)
        self.settings["excluded"] = sorted(ex)
        self._save_settings()
        self.rebuild()

    def toggle_direction(self):
        sel = self._selected()
        if not sel:
            return
        flips = set(self.settings.get("direction_flips", []))
        for t in sel:
            flips.symmetric_difference_update({t.uid})
        self.settings["direction_flips"] = sorted(flips)
        self._save_settings()
        self.show_credits.set(True)
        self.rebuild()

    # ================================================================ export
    def _need_data(self):
        if not self.analysis or not self.transactions:
            messagebox.showinfo(APP_NAME, "Run an analysis first.")
            return False
        return True

    def export_csv(self):
        if not self._need_data():
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="transactions.csv",
                                         filetypes=[("CSV", "*.csv")])
        if p:
            export_csv(p, self._scoped())
            self.set_status(f"Saved {p}", T.GOOD)

    def export_html(self):
        if not self._need_data():
            return
        p = filedialog.asksaveasfilename(defaultextension=".html", initialfile="spending_report.html",
                                         filetypes=[("HTML", "*.html")])
        if p:
            g = self.group_var.get()
            groups = summarize_groups(self.transactions, self.file_results, ALL_FOLDERS) \
                if g == ALL_FOLDERS and len(self.group_combo["values"]) > 2 else None
            export_html(p, self.analysis, self.color, scope=None if g == ALL_FOLDERS else g, groups=groups,
                        files=self._scoped_files())
            self.set_status(f"Saved {p}", T.GOOD)
            if messagebox.askyesno(APP_NAME, "Report saved. Open it in your browser now? (It's a local file.)"):
                webbrowser.open("file://" + os.path.abspath(p))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
