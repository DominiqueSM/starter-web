"""Tkinter desktop interface. Runs entirely offline."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from .categorize import NON_SPENDING, Categorizer
from .extract import process_folder
from .insights import analyze, money, summarize_groups
from .report import export_csv, export_html

ALL_FOLDERS = "All folders"
TOP_LEVEL = "(files not in a subfolder)"

APP_NAME = "Spending Analyzer"
DATA_DIR = os.path.join(os.path.expanduser("~"), ".spending_analyzer")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

PALETTE = ["#2f6fde", "#e8a33d", "#2e9d5b", "#d9534f", "#8a5cd6", "#1fa2b8", "#c2569a", "#7a8a2e",
           "#e07b39", "#4b5fb5", "#3aa37c", "#b0473f", "#6d7887", "#a17c2b", "#5aa0d8", "#9a5fb0"]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cat = Categorizer(DATA_DIR)
        self.settings = self._load_settings()
        self.file_results = []
        self.transactions = []
        self.analysis = None
        self.q = queue.Queue()
        self._color_map = {}
        self._sort_state = {}

        root.title(APP_NAME)
        root.geometry(self.settings.get("geometry", "1180x760"))
        root.minsize(900, 560)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style()
        self._build()
        if self.settings.get("folder") and os.path.isdir(self.settings["folder"]):
            self.folder_var.set(self.settings["folder"])

    # ---------- setup ----------
    def _style(self):
        s = ttk.Style()
        if "clam" in s.theme_names() and sys.platform.startswith("linux"):
            s.theme_use("clam")
        s.configure("Treeview", rowheight=24)
        s.configure("KPI.TLabel", font=("TkDefaultFont", 18, "bold"))
        s.configure("KPIName.TLabel", foreground="#5d6676")
        s.configure("H.TLabel", font=("TkDefaultFont", 12, "bold"))

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
        except Exception:
            pass

    def on_close(self):
        self.settings["geometry"] = self.root.geometry()
        self.settings["folder"] = self.folder_var.get()
        self._save_settings()
        self.root.destroy()

    def color(self, category: str) -> str:
        if category not in self._color_map:
            self._color_map[category] = PALETTE[len(self._color_map) % len(PALETTE)]
        return self._color_map[category]

    def _build(self):
        top = ttk.Frame(self.root, padding=(10, 10, 10, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Folder with PDF statements:").pack(side="left")
        self.folder_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.folder_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Browse...", command=self.browse).pack(side="left")
        self.analyze_btn = ttk.Button(top, text="Analyze", command=self.start_analysis)
        self.analyze_btn.pack(side="left", padx=(6, 0))
        ttk.Label(top, text="Show:").pack(side="left", padx=(14, 4))
        self.group_var = tk.StringVar(value=ALL_FOLDERS)
        self.group_combo = ttk.Combobox(top, textvariable=self.group_var, state="readonly", width=24,
                                        values=[ALL_FOLDERS])
        self.group_combo.pack(side="left")
        self.group_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        bar = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        bar.pack(fill="x")
        self.status_var = tk.StringVar(value="Choose a folder containing bank or credit-card statement PDFs, then click Analyze. "
                                            "Nothing leaves this computer.")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(bar, length=200, mode="determinate")
        self.progress.pack(side="right")
        ttk.Button(bar, text="Export report (HTML)", command=self.export_html).pack(side="right", padx=4)
        ttk.Button(bar, text="Export CSV", command=self.export_csv).pack(side="right")

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._build_overview()
        self._build_suggestions()
        self._build_transactions()
        self._build_recurring()
        self._build_groups()
        self._build_files()

    def _build_overview(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Overview")
        kp = ttk.Frame(f)
        kp.pack(fill="x")
        self.kpi_vars = {}
        for i, name in enumerate(["Total spent", "Average / month", "Money in", "Possible savings / month", "Period"]):
            box = ttk.Frame(kp, padding=(8, 4))
            box.grid(row=0, column=i, sticky="w", padx=(0, 16))
            ttk.Label(box, text=name, style="KPIName.TLabel").pack(anchor="w")
            v = tk.StringVar(value="-")
            ttk.Label(box, textvariable=v, style="KPI.TLabel").pack(anchor="w")
            self.kpi_vars[name] = v
        charts = ttk.Frame(f)
        charts.pack(fill="both", expand=True, pady=(10, 0))
        charts.columnconfigure(0, weight=1)
        charts.columnconfigure(1, weight=1)
        charts.rowconfigure(1, weight=1)
        ttk.Label(charts, text="Spending by category (per month)", style="H.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(charts, text="Spending by month", style="H.TLabel").grid(row=0, column=1, sticky="w")
        self.cat_canvas = tk.Canvas(charts, background="white", highlightthickness=0)
        self.cat_canvas.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=4)
        self.mon_canvas = tk.Canvas(charts, background="white", highlightthickness=0)
        self.mon_canvas.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=4)
        self.cat_canvas.bind("<Configure>", lambda e: self.draw_charts())
        self.mon_canvas.bind("<Configure>", lambda e: self.draw_charts())

    def _build_suggestions(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="What to cut back on")
        self.sugg_text = tk.Text(f, wrap="word", relief="flat", padx=12, pady=10, background="white",
                                 font=("TkDefaultFont", 11), cursor="arrow")
        sb = ttk.Scrollbar(f, command=self.sugg_text.yview)
        self.sugg_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.sugg_text.pack(fill="both", expand=True)
        t = self.sugg_text
        t.tag_configure("title", font=("TkDefaultFont", 13, "bold"), spacing1=14, spacing3=4)
        t.tag_configure("p1", foreground="#c0392b")
        t.tag_configure("p2", foreground="#b9770e")
        t.tag_configure("p3", foreground="#5d6676")
        t.tag_configure("save", foreground="#2e9d5b", font=("TkDefaultFont", 11, "bold"), spacing1=4)
        t.tag_configure("item", lmargin1=24, lmargin2=36, foreground="#333")
        t.tag_configure("head", font=("TkDefaultFont", 16, "bold"), spacing3=6)
        t.configure(state="disabled")

    def _tree(self, parent, cols, widths, anchors=None):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tv = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c, w in zip(cols, widths):
            tv.heading(c, text=c, command=lambda c=c, tv=tv: self.sort_tree(tv, c))
            tv.column(c, width=w, anchor=(anchors or {}).get(c, "w"), stretch=(w > 200))
        ys = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        return tv

    def _build_transactions(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Transactions")
        ctl = ttk.Frame(f)
        ctl.pack(fill="x", pady=(0, 6))
        ttk.Label(ctl, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.fill_transactions())
        ttk.Entry(ctl, textvariable=self.search_var, width=28).pack(side="left", padx=(4, 12))
        ttk.Label(ctl, text="Category:").pack(side="left")
        self.cat_filter = tk.StringVar(value="All")
        self.cat_combo = ttk.Combobox(ctl, textvariable=self.cat_filter, state="readonly", width=26)
        self.cat_combo.pack(side="left", padx=4)
        self.cat_combo.bind("<<ComboboxSelected>>", lambda e: self.fill_transactions())
        self.show_credits = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl, text="Show money in", variable=self.show_credits,
                        command=self.fill_transactions).pack(side="left", padx=8)
        ttk.Button(ctl, text="Set category...", command=self.set_category_dialog).pack(side="right")
        ttk.Button(ctl, text="Exclude / include", command=self.toggle_exclude).pack(side="right", padx=4)
        ttk.Button(ctl, text="Flip in/out", command=self.toggle_direction).pack(side="right")
        self.tx_tree = self._tree(f, ("Date", "Description", "Category", "Amount", "In/Out", "Folder", "File"),
                                  (95, 330, 190, 95, 55, 130, 170), {"Amount": "e", "In/Out": "center"})
        self.tx_tree.bind("<Double-1>", lambda e: self.set_category_dialog())
        self.tx_tree.tag_configure("excluded", foreground="#a0a0a0")
        self.tx_tree.tag_configure("credit", foreground="#2e9d5b")
        self.tx_sum_var = tk.StringVar()
        ttk.Label(f, textvariable=self.tx_sum_var).pack(anchor="w", pady=(6, 0))

    def _build_recurring(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Recurring charges")
        ttk.Label(f, text="Charges that repeat on a schedule with a similar amount: subscriptions, memberships, bills.",
                  ).pack(anchor="w", pady=(0, 6))
        self.rec_tree = self._tree(f, ("Merchant", "Category", "Frequency", "Amount", "Per year", "Times", "Last charged", "Note"),
                                   (220, 170, 100, 90, 100, 60, 100, 220),
                                   {"Amount": "e", "Per year": "e", "Times": "center"})

    def _build_groups(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="By folder")
        ttk.Label(f, text="Each subfolder of the chosen folder is a group (e.g. one per card or account). "
                          "Double-click a row to analyze just that folder.").pack(anchor="w", pady=(0, 6))
        self.group_tree = self._tree(
            f, ("Folder", "Files", "Transactions", "Spent", "Per month", "Money in", "Fees & interest",
                "Biggest category", "Period"),
            (190, 50, 95, 100, 90, 100, 105, 160, 180),
            {"Files": "center", "Transactions": "center", "Spent": "e", "Per month": "e", "Money in": "e",
             "Fees & interest": "e"})
        self.group_tree.bind("<Double-1>", self._open_group)
        self.group_tree.tag_configure("total", font=("TkDefaultFont", 10, "bold"))

    def _open_group(self, event=None):
        sel = self.group_tree.selection()
        if not sel:
            return
        g = self.group_tree.set(sel[0], "Folder")
        self.group_var.set(ALL_FOLDERS if g.startswith("All ") else g)
        self.refresh()
        self.nb.select(0)

    def _build_files(self):
        f = ttk.Frame(self.nb, padding=10)
        self.files_tab = f
        self.nb.add(f, text="Files")
        self.file_tree = self._tree(f, ("File", "Status", "Pages", "Transactions", "Notes"),
                                    (320, 110, 60, 100, 420), {"Pages": "center", "Transactions": "center"})
        self.file_tree.tag_configure("bad", foreground="#c0392b")

    # ---------- actions ----------
    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder_var.get() or os.path.expanduser("~"),
                                    title="Choose folder with PDF statements")
        if d:
            self.folder_var.set(d)

    def start_analysis(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(APP_NAME, "Please choose a folder that exists.")
            return
        self.settings["folder"] = folder
        self._save_settings()
        self.scan_folder = folder
        self.analyze_btn.configure(state="disabled")
        self.status_var.set("Reading PDFs...")
        self.progress["value"] = 0

        def work():
            try:
                res = process_folder(folder, progress=lambda i, n, name: self.q.put(("progress", i, n, name)))
                self.q.put(("done", res))
            except Exception as ex:
                self.q.put(("error", str(ex)))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self.poll)

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    _, i, n, name = msg
                    self.progress["maximum"] = max(n, 1)
                    self.progress["value"] = i
                    if name:
                        self.status_var.set(f"Reading {i + 1} of {n}: {name}")
                elif msg[0] == "done":
                    self.analysis_finished(msg[1])
                    return
                elif msg[0] == "error":
                    self.analyze_btn.configure(state="normal")
                    messagebox.showerror(APP_NAME, msg[1])
                    return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def analysis_finished(self, results):
        self.analyze_btn.configure(state="normal")
        self.file_results = results
        self.transactions = [t for r in results for t in r.transactions]
        for r in results:
            r.group = self._group_of(r.path)
            for t in r.transactions:
                t.group = r.group
        groups = sorted({r.group for r in results if r.transactions}, key=lambda g: (g == TOP_LEVEL, g.lower()))
        self.group_combo["values"] = [ALL_FOLDERS] + groups
        if self.group_var.get() not in self.group_combo["values"]:
            self.group_var.set(ALL_FOLDERS)
        self.cat.apply(self.transactions)
        self._apply_saved_flags()
        n_ok = sum(1 for r in results if r.transactions)
        if not results:
            self.status_var.set("No PDF files found in that folder (subfolders are included).")
        else:
            self.status_var.set(f"Read {len(results)} PDF(s); found {len(self.transactions)} transactions in {n_ok} file(s).")
        self.refresh()
        if results and not self.transactions:
            self.nb.select(self.files_tab)
            messagebox.showinfo(APP_NAME, "No transactions were recognised. See the Files tab for details on each PDF.")

    def _group_of(self, path):
        rel = os.path.relpath(path, getattr(self, "scan_folder", None) or self.folder_var.get() or ".")
        parts = rel.split(os.sep)
        return parts[0] if len(parts) > 1 else TOP_LEVEL

    def _scoped(self):
        g = self.group_var.get()
        if not g or g == ALL_FOLDERS:
            return self.transactions
        return [t for t in self.transactions if t.group == g]

    def _tx_key(self, t):
        return t.uid

    def _apply_saved_flags(self):
        seen = {}
        for t in self.transactions:  # stable id; '#n' separates identical charges (e.g. a double charge)
            base = f"{t.date}|{t.description}|{t.amount:.2f}"
            seen[base] = seen.get(base, 0) + 1
            t.uid = base if seen[base] == 1 else f"{base}#{seen[base]}"
        ex = set(self.settings.get("excluded", []))
        flips = set(self.settings.get("direction_flips", []))
        for t in self.transactions:
            k = self._tx_key(t)
            t.excluded = k in ex
            if k in flips:
                t.is_credit = not t.is_credit

    def refresh(self):
        scoped = self._scoped()
        self.analysis = analyze(scoped)
        cats = ["All"] + sorted({t.category for t in scoped})
        self.cat_combo["values"] = cats
        if self.cat_filter.get() not in cats:
            self.cat_filter.set("All")
        self.fill_overview()
        self.fill_suggestions()
        self.fill_transactions()
        self.fill_recurring()
        self.fill_groups()
        self.fill_files()

    def fill_overview(self):
        a = self.analysis
        self.kpi_vars["Total spent"].set(money(a.total_spent))
        self.kpi_vars["Average / month"].set(money(a.total_spent / a.months))
        self.kpi_vars["Money in"].set(money(a.total_in))
        self.kpi_vars["Possible savings / month"].set(money(a.potential_monthly_savings))
        self.kpi_vars["Period"].set(f"{a.first_date:%b %Y} - {a.last_date:%b %Y}" if a.first_date else "-")
        self.draw_charts()

    def draw_charts(self):
        a = self.analysis
        for cv in (self.cat_canvas, self.mon_canvas):
            cv.delete("all")
        if not a or not a.spending:
            for cv in (self.cat_canvas, self.mon_canvas):
                cv.create_text(cv.winfo_width() / 2, 40, text="No data yet", fill="#888")
            return
        # Category horizontal bars
        cv = self.cat_canvas
        W, H = cv.winfo_width(), cv.winfo_height()
        rows = a.by_category[:16]
        from tkinter import font as tkfont
        f = tkfont.nametofont("TkDefaultFont")
        label_w = 16 + max(f.measure(c) for c, _ in rows)
        val_w, top = 90, 10
        row_h = max(16, min(28, (H - 20) / max(len(rows), 1)))
        mx = rows[0][1] / a.months if rows else 1
        for i, (c, v) in enumerate(rows):
            pm = v / a.months
            y = top + i * row_h
            cv.create_text(label_w - 8, y + row_h / 2, text=c, anchor="e", fill="#1d2330")
            bw = max(2, (W - label_w - val_w) * pm / mx)
            cv.create_rectangle(label_w, y + 4, label_w + bw, y + row_h - 4, fill=self.color(c), outline="")
            cv.create_text(label_w + bw + 6, y + row_h / 2, text=money(pm), anchor="w", fill="#5d6676")
        # Monthly vertical bars
        cv = self.mon_canvas
        W, H = cv.winfo_width(), cv.winfo_height()
        months = a.by_month[-24:]
        mx = max(v for _, v in months) or 1
        base, left, topm = H - 34, 10, 44
        bw = (W - 2 * left) / max(len(months), 1)
        avg = a.total_spent / a.months
        for i, (m, v) in enumerate(months):
            x0 = left + i * bw + bw * 0.15
            x1 = left + (i + 1) * bw - bw * 0.15
            h = (base - topm) * v / mx
            cv.create_rectangle(x0, base - h, x1, base, fill="#2f6fde", outline="")
            if len(months) <= 14 or i % 2 == 0:
                cv.create_text((x0 + x1) / 2, base + 12, text=m[2:], fill="#5d6676", font=("TkDefaultFont", 8))
            if len(months) <= 12:
                cv.create_text((x0 + x1) / 2, base - h - 8, text=f"${v:,.0f}", fill="#1d2330", font=("TkDefaultFont", 8))
        ya = base - (base - topm) * avg / mx
        cv.create_line(left, ya, W - left, ya, fill="#e8a33d", dash=(4, 3))
        cv.create_text(left, 10, text=f"- - -  monthly average {money(avg)}", anchor="w", fill="#b9770e",
                       font=("TkDefaultFont", 9))

    def fill_suggestions(self):
        a = self.analysis
        t = self.sugg_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not a.spending:
            t.insert("end", "Run an analysis to see suggestions.")
        else:
            t.insert("end", f"You could save about {money(a.potential_monthly_savings)}/month "
                            f"({money(a.potential_monthly_savings * 12)}/year)\n", "head")
            t.insert("end", "Estimates are based on your own spending patterns. Red = biggest impact, "
                            "orange = worth a look, grey = for information.\n", "p3")
            for s in a.suggestions:
                t.insert("end", "● ", f"p{s.priority}")
                t.insert("end", s.title + "\n", "title")
                t.insert("end", s.detail + "\n")
                for it in s.items:
                    t.insert("end", "• " + it + "\n", "item")
                if s.monthly_savings >= 1:
                    t.insert("end", f"Potential savings: ~{money(s.monthly_savings)}/month "
                                    f"({money(s.monthly_savings * 12)}/year)\n", "save")
        t.configure(state="disabled")

    def _visible_transactions(self):
        q = self.search_var.get().strip().lower()
        c = self.cat_filter.get()
        out = []
        for t in self._scoped():
            if t.is_credit and not self.show_credits.get():
                continue
            if c and c != "All" and t.category != c:
                continue
            if q and q not in t.description.lower() and q not in t.category.lower():
                continue
            out.append(t)
        return sorted(out, key=lambda t: t.date, reverse=True)

    def fill_transactions(self):
        tv = self.tx_tree
        tv.delete(*tv.get_children())
        self._tx_index = {}
        vis = self._visible_transactions()
        total = 0.0
        for i, t in enumerate(vis):
            tags = ("excluded",) if t.excluded else (("credit",) if t.is_credit else ())
            iid = str(i)
            self._tx_index[iid] = t
            tv.insert("", "end", iid=iid, tags=tags, values=(
                t.date.isoformat(), t.description, t.category + (" (excluded)" if t.excluded else ""),
                f"{t.amount:,.2f}", "in" if t.is_credit else "out", t.group, os.path.basename(t.source_file)))
            if t.is_spending and t.category not in NON_SPENDING:
                total += t.amount
        self.tx_sum_var.set(f"{len(vis)} transactions shown · spending in view: {money(total)}  "
                            "· Tip: double-click a row to change its category; the app remembers it for that merchant.")

    def fill_recurring(self):
        tv = self.rec_tree
        tv.delete(*tv.get_children())
        for r in self.analysis.recurring:
            note = f"Price went up {money(r.price_change[0])} -> {money(r.price_change[1])}" if r.price_change else ""
            tv.insert("", "end", values=(r.merchant, r.category, r.frequency, f"{r.typical_amount:,.2f}",
                                         f"{r.monthly_cost * 12:,.2f}", r.count, r.last_date.isoformat(), note))

    def fill_groups(self):
        tv = self.group_tree
        tv.delete(*tv.get_children())
        if not self.transactions:
            return
        for g in summarize_groups(self.transactions, self.file_results, ALL_FOLDERS):
            period = f"{g['first']:%b %Y} - {g['last']:%b %Y}" if g["first"] else "-"
            tv.insert("", "end", tags=("total",) if g["name"] == ALL_FOLDERS else (), values=(
                g["name"], g["files"], g["transactions"], f"{g['spent']:,.2f}", f"{g['per_month']:,.2f}",
                f"{g['money_in']:,.2f}", f"{g['fees']:,.2f}", g["top_category"], period))

    def fill_files(self):
        tv = self.file_tree
        tv.delete(*tv.get_children())
        for r in self.file_results:
            tags = ("bad",) if r.status in ("error", "no-text", "no-transactions") else ()
            tv.insert("", "end", tags=tags, values=(os.path.relpath(r.path, self.folder_var.get() or "."),
                                                     r.status, r.pages, len(r.transactions), r.note))

    def sort_tree(self, tv, col):
        rev = self._sort_state.get((id(tv), col), False)
        items = [(tv.set(k, col), k) for k in tv.get_children("")]

        def key(v):
            s = v[0].replace(",", "").replace("$", "")
            try:
                return (0, float(s), "")
            except ValueError:
                return (1, 0.0, s.lower())
        items.sort(key=key, reverse=rev)
        for idx, (_, k) in enumerate(items):
            tv.move(k, "", idx)
        self._sort_state[(id(tv), col)] = not rev

    def _selected(self):
        return [self._tx_index[i] for i in self.tx_tree.selection() if i in self._tx_index]

    def set_category_dialog(self):
        sel = self._selected()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select one or more transactions first.")
            return
        win = tk.Toplevel(self.root)
        win.title("Set category")
        win.transient(self.root)
        win.resizable(False, False)
        merchants = sorted({t.merchant for t in sel})
        ttk.Label(win, text=f"{len(sel)} transaction(s) from: {', '.join(merchants)[:120]}", padding=10).pack(anchor="w")
        var = tk.StringVar(value=sel[0].category)
        cb = ttk.Combobox(win, textvariable=var, values=self.cat.all_categories(), width=34)
        cb.pack(padx=10, anchor="w")
        ttk.Label(win, text="(You can also type a new category name.)", padding=(10, 2)).pack(anchor="w")
        remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(win, text="Apply to all transactions from these merchants (remembered)",
                        variable=remember).pack(anchor="w", padx=10, pady=6)

        def ok():
            c = var.get().strip()
            if not c:
                return
            if remember.get():
                for m in merchants:
                    self.cat.set_override(m, c)
                for t in self.transactions:
                    if t.merchant in merchants:
                        t.category = c
            else:
                for t in sel:
                    t.category = c
            for t in self.transactions:
                if t.category == "Income":
                    t.is_credit = True
            win.destroy()
            self.refresh()

        btns = ttk.Frame(win, padding=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=ok).pack(side="right", padx=6)
        win.bind("<Return>", lambda e: ok())
        win.grab_set()
        cb.focus_set()

    def toggle_exclude(self):
        sel = self._selected()
        if not sel:
            return
        ex = set(self.settings.get("excluded", []))
        for t in sel:
            t.excluded = not t.excluded
            (ex.add if t.excluded else ex.discard)(self._tx_key(t))
        self.settings["excluded"] = sorted(ex)
        self._save_settings()
        self.refresh()

    def toggle_direction(self):
        sel = self._selected()
        if not sel:
            return
        flips = set(self.settings.get("direction_flips", []))
        for t in sel:
            t.is_credit = not t.is_credit
            k = self._tx_key(t)
            flips.symmetric_difference_update({k})
        self.settings["direction_flips"] = sorted(flips)
        self._save_settings()
        if any(t.is_credit for t in sel):
            self.show_credits.set(True)
        self.refresh()

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
            self.status_var.set(f"Saved {p}")

    def export_html(self):
        if not self._need_data():
            return
        p = filedialog.asksaveasfilename(defaultextension=".html", initialfile="spending_report.html",
                                         filetypes=[("HTML", "*.html")])
        if p:
            g = self.group_var.get()
            groups = summarize_groups(self.transactions, self.file_results, ALL_FOLDERS) \
                if g == ALL_FOLDERS and len(self.group_combo["values"]) > 2 else None
            export_html(p, self.analysis, self.color, scope=None if g == ALL_FOLDERS else g, groups=groups)
            self.status_var.set(f"Saved {p}")
            if messagebox.askyesno(APP_NAME, "Report saved. Open it now in your browser? (It is a local file.)"):
                webbrowser.open("file://" + os.path.abspath(p))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
