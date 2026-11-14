"""Budgets, tags, debt payoff, and the Rules & backup page (mixed into the main window)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from . import backup
from .checks import needs_review
from . import theme as T
from .insights import money
from .planning import (Debt, budget_rows, debts_from_statements, left_to_spend, month_label, simulate,
                       spending_by_tag, suggest_budgets)


def _parse_money(s: str):
    s = (s or "").strip().replace("$", "").replace(",", "").replace("%", "")
    if not s:
        return None
    return float(s)


class PlanningPages:
    # ================================================================ small dialogs
    def _dialog(self, title):
        win = tk.Toplevel(self.root, bg=T.SURFACE)
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        body = tk.Frame(win, bg=T.SURFACE)
        body.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(body, text=title, bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["h2"]).pack(anchor="w", pady=(0, 8))
        return win, body

    def _finish_dialog(self, win, body, on_ok, focus=None):
        btns = tk.Frame(body, bg=T.SURFACE)
        btns.pack(fill="x", pady=(16, 0))
        T.Button(btns, "Save", on_ok, style="primary").pack(side="right")
        T.Button(btns, "Cancel", win.destroy).pack(side="right", padx=8)
        win.bind("<Return>", lambda e: on_ok())
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()
        if focus is not None:
            focus.focus_set()

    def _field(self, body, label, value="", width=30, values=None, hint=""):
        tk.Label(body, text=label, bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["bold"]).pack(anchor="w", pady=(6, 2))
        var = tk.StringVar(value=value)
        w = (ttk.Combobox(body, textvariable=var, values=values, width=width) if values is not None
             else ttk.Entry(body, textvariable=var, width=width))
        w.pack(anchor="w")
        if hint:
            tk.Label(body, text=hint, bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["tiny"], wraplength=380,
                     justify="left").pack(anchor="w")
        return var, w

    # ================================================================ budgets
    def _build_budgets(self, page):
        top = tk.Frame(page, bg=T.BG)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="Month", bg=T.BG, fg=T.MUTED, font=T.FONTS["small"]).pack(side="left")
        self.bud_month = tk.StringVar()
        self.bud_combo = ttk.Combobox(top, textvariable=self.bud_month, state="readonly", width=12)
        self.bud_combo.pack(side="left", padx=(6, 0))
        self.bud_combo.bind("<<ComboboxSelected>>", lambda e: self.render_budgets())
        T.Button(top, "Suggest budgets", self.suggest_budgets_action).pack(side="right")
        T.Button(top, "Set budget…", self.edit_budget, style="primary").pack(side="right", padx=6)
        so, self.bud_summary = T.card(page, padding=16)
        so.pack(fill="x", pady=(0, 10))
        outer, self.bud_tree = self._table(page, [
            ("Category", "Category", 220, "w", True), ("Budget", "Budget", 100, "e", False),
            ("Spent", "Spent", 100, "e", False), ("Left", "Left", 100, "e", False),
            ("Used", "Used", 190, "w", False), ("Typical", "Typical month", 110, "e", False)])
        outer.pack(fill="both", expand=True)
        self.bud_tree.bind("<Double-1>", lambda e: self.edit_budget())
        tk.Label(page, text="Double-click a category to set its monthly budget. 'Typical month' is the median of the "
                            "three full months before. Refunds and shared bills paid back are already subtracted.",
                 bg=T.BG, fg=T.MUTED, font=T.FONTS["small"]).pack(anchor="w", pady=(6, 10))
        hdr = tk.Frame(page, bg=T.BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Spending by tag", bg=T.BG, fg=T.TEXT, font=T.FONTS["h3"]).pack(side="left")
        tk.Label(hdr, text="Tag transactions on the Transactions page (Tag…). Double-click a tag to see them.",
                 bg=T.BG, fg=T.MUTED, font=T.FONTS["small"]).pack(side="left", padx=12)
        o2, self.tag_tree = self._table(page, [
            ("Tag", "Tag", 220, "w", True), ("Total", "Total", 110, "e", False),
            ("PerMonth", "Per month", 110, "e", False), ("Count", "Transactions", 110, "center", False)])
        o2.configure(height=150)
        o2.pack(fill="x", pady=(6, 0))
        self.tag_tree.configure(height=4)
        self.tag_tree.bind("<Double-1>", self._tag_drill)

    def _budget_months(self):
        return [m for m, _ in self.analysis.by_month] if self.analysis else []

    def render_budgets(self):
        a = self.analysis
        for w in self.bud_summary.winfo_children():
            w.destroy()
        for tv in (self.bud_tree, self.tag_tree):
            tv.delete(*tv.get_children())
        months = self._budget_months()
        self.bud_combo["values"] = list(reversed(months))
        if not months:
            tk.Label(self.bud_summary, text="Run an analysis to set budgets.", bg=T.SURFACE, fg=T.MUTED).pack(anchor="w")
            return
        today = date.today()
        if self.bud_month.get() not in months:
            cur = f"{today.year:04d}-{today.month:02d}"
            self.bud_month.set(cur if cur in months else months[-1])
        m = self.bud_month.get()
        budgets = self.settings.get("budgets", {})
        rows = budget_rows(a, budgets, m)
        budgeted = [r for r in rows if r.budget > 0]
        row = tk.Frame(self.bud_summary, bg=T.SURFACE)
        row.pack(fill="x")
        if not budgeted:
            tk.Label(row, text="No budgets yet. Click 'Suggest budgets' to start from your typical month, or "
                               "double-click a category.", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["body"]).pack(anchor="w")
        else:
            tb, ts = sum(r.budget for r in budgeted), sum(r.spent for r in budgeted)
            over = [r for r in budgeted if r.spent > r.budget + 0.005]
            items = [("Budgeted", money(tb), T.TEXT), ("Spent", money(ts), T.TEXT),
                     ("Left", money(tb - ts), T.GOOD if tb >= ts else T.BAD),
                     ("Over budget", f"{len(over)} categor{'y' if len(over) == 1 else 'ies'}", T.BAD if over else T.GOOD)]
            for label, val, col in items:
                box = tk.Frame(row, bg=T.SURFACE)
                box.pack(side="left", padx=(0, 40))
                tk.Label(box, text=label.upper(), bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["tiny"] + ("bold",)).pack(anchor="w")
                tk.Label(box, text=val, bg=T.SURFACE, fg=col, font=T.FONTS["kpi"]).pack(anchor="w")
            lts = left_to_spend(rows, m, today)
            note = (f"About {money(lts[1])} a day\nfor the {lts[2]} days left" if lts else "Same budgets every\nmonth")
            tk.Label(row, text=note, bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["small"], justify="right",
                     anchor="e").pack(side="right")
        for i, r in enumerate(rows):
            if r.budget > 0:
                n = max(0, min(10, round(r.used * 10)))
                used = "■" * n + "□" * (10 - n) + f"  {r.used:.0%}"
                tags = ["bad"] if r.spent > r.budget + 0.005 else (["warn"] if r.used >= 0.9 else [])
            else:
                used, tags = "no budget", ["muted"]
            if i % 2:
                tags.append("odd")
            self.bud_tree.insert("", "end", tags=tags, values=(
                r.category, f"{r.budget:,.2f}" if r.budget else "–", f"{r.spent:,.2f}",
                f"{r.remaining:,.2f}" if r.budget else "", used, f"{r.typical:,.2f}" if r.typical else ""))
        for i, t in enumerate(spending_by_tag(a, self._scoped())):
            self.tag_tree.insert("", "end", tags=["odd"] if i % 2 else [], values=(
                t["tag"], f"{t['total']:,.2f}", f"{t['per_month']:,.2f}", t["count"]))

    def edit_budget(self):
        sel = self.bud_tree.selection()
        cat = self.bud_tree.set(sel[0], "Category") if sel else ""
        win, body = self._dialog("Set a monthly budget")
        cv, cw = self._field(body, "Category", cat, values=self.cat.all_categories())
        cur = self.settings.get("budgets", {}).get(cat)
        av, aw = self._field(body, "Monthly budget", f"{cur:.0f}" if cur else "", width=14,
                             hint="Leave empty to remove this category's budget.")

        def ok():
            c = cv.get().strip()
            try:
                v = _parse_money(av.get())
            except ValueError:
                messagebox.showwarning(self.APP_NAME, "Enter an amount like 300.", parent=win)
                return
            if not c:
                return
            b = self.settings.setdefault("budgets", {})
            if v:
                b[c] = round(v, 2)
            else:
                b.pop(c, None)
            self._save_settings()
            win.destroy()
            self.refresh()
            self.show_page("budgets")
        self._finish_dialog(win, body, ok, aw if cat else cw)

    def suggest_budgets_action(self):
        if not self.analysis or not self.transactions:
            messagebox.showinfo(self.APP_NAME, "Run an analysis first.")
            return
        sug = suggest_budgets(self.analysis)
        have = self.settings.get("budgets", {})
        new = {c: v for c, v in sug.items() if c not in have}
        if not new:
            messagebox.showinfo(self.APP_NAME, "Every category you spend in already has a budget.")
            return
        lines = "\n".join(f"  {c}: {money(v)}" for c, v in sorted(new.items(), key=lambda kv: -kv[1])[:14])
        if messagebox.askyesno(self.APP_NAME, f"Set these budgets from your typical month (median of recent full "
                                              f"months)? Budgets you already set stay as they are.\n\n{lines}"
                                              "\n\nTip: then lower the ones you want to cut back on."):
            have.update(new)
            self.settings["budgets"] = have
            self._save_settings()
            self.refresh()

    # ================================================================ tags
    def _all_tags(self):
        return sorted({r.get("tag", "") for r in self.settings.get("tag_rules", []) if r.get("tag")})

    def tag_dialog(self):
        sel = self._selected()
        if not sel:
            messagebox.showinfo(self.APP_NAME, "Select one or more transactions first.")
            return
        merchants = sorted({t.merchant for t in sel})
        win, body = self._dialog("Add a tag")
        tk.Label(body, text=f"{len(sel)} transaction(s) from {', '.join(merchants)[:80]}", bg=T.SURFACE, fg=T.MUTED,
                 font=T.FONTS["small"], wraplength=380, justify="left").pack(anchor="w")
        tv, tw = self._field(body, "Tag", "", values=self._all_tags(),
                             hint="A label across categories, e.g. alcohol, work, vacation 2026.")
        tk.Label(body, text="Apply to", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["bold"]).pack(anchor="w", pady=(8, 2))
        scope = tk.StringVar(value="company")
        ttk.Radiobutton(body, text=f"Every transaction from {merchants[0] if len(merchants) == 1 else 'these companies'}",
                        variable=scope, value="company").pack(anchor="w")
        ttk.Radiobutton(body, text="Every transaction whose description contains", variable=scope,
                        value="contains").pack(anchor="w")
        contains = tk.StringVar(value=(sel[0].description.split() or [""])[0])
        ttk.Entry(body, textvariable=contains, width=30).pack(anchor="w", padx=(24, 0))
        contains.trace_add("write", lambda *a: scope.set("contains"))
        ttk.Radiobutton(body, text="Only the selected transaction(s)", variable=scope, value="only").pack(anchor="w")

        def ok():
            tag = tv.get().strip()
            if not tag:
                return
            rules = self.settings.setdefault("tag_rules", [])
            how = scope.get()
            if how == "company":
                rules += [{"by": "company", "value": m, "tag": tag} for m in merchants]
            elif how == "contains":
                if len(contains.get().strip()) < 3:
                    messagebox.showwarning(self.APP_NAME, "Type at least 3 characters to match on.", parent=win)
                    return
                rules.append({"by": "contains", "value": contains.get().strip(), "tag": tag})
            else:
                rules += [{"by": "tx", "value": t.uid, "tag": tag} for t in sel]
            self._save_settings()
            win.destroy()
            self.rebuild()
        self._finish_dialog(win, body, ok, tw)

    def _tag_drill(self, e=None):
        sel = self.tag_tree.selection()
        if sel:
            self.tag_filter.set(self.tag_tree.set(sel[0], "Tag"))
            self.search_var.set("")
            self.cat_filter.set("All categories")
            self.show_credits.set(True)
            self.render_transactions()
            self.show_page("transactions")

    # ================================================================ debt payoff
    def _debts(self) -> list[Debt]:
        saved = self.settings.get("debts", {})
        out = []
        for d in debts_from_statements(self.file_results):
            o = saved.get(d.key, {})
            if o.get("removed"):
                continue
            for k in ("balance", "apr", "minimum", "include"):
                if k in o:
                    setattr(d, k, o[k])
            if o:
                d.note = (d.note + " · " if d.note else "") + "your changes"
            out.append(d)
        for key, o in saved.items():
            if o.get("user") and not o.get("removed"):
                out.append(Debt(name=o.get("name", key), balance=o.get("balance", 0), apr=o.get("apr", 0),
                                minimum=o.get("minimum", 0), source="you", include=o.get("include", True), key=key))
        return out

    def _build_debt(self, page):
        top = tk.Frame(page, bg=T.BG)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="Extra each month", bg=T.BG, fg=T.MUTED, font=T.FONTS["small"]).pack(side="left")
        self.debt_extra = tk.StringVar(value=str(self.settings.get("debt_extra", "") or ""))
        ttk.Entry(top, textvariable=self.debt_extra, width=10).pack(side="left", padx=(6, 16))
        self.debt_extra.trace_add("write", lambda *a: self._debt_settings_changed())
        tk.Label(top, text="Strategy", bg=T.BG, fg=T.MUTED, font=T.FONTS["small"]).pack(side="left")
        self.debt_strategy = tk.StringVar(value={"snowball": "Snowball: smallest balance first"}.get(
            self.settings.get("debt_strategy"), "Avalanche: highest rate first"))
        sc = ttk.Combobox(top, textvariable=self.debt_strategy, state="readonly", width=32,
                          values=["Avalanche: highest rate first", "Snowball: smallest balance first"])
        sc.pack(side="left", padx=6)
        sc.bind("<<ComboboxSelected>>", lambda e: self._debt_settings_changed())
        T.Button(top, "Remove", self.remove_debt).pack(side="right")
        T.Button(top, "Edit…", self.edit_debt).pack(side="right", padx=6)
        T.Button(top, "Add a debt…", lambda: self.edit_debt(new=True), style="primary").pack(side="right")
        kp = tk.Frame(page, bg=T.BG)
        kp.pack(fill="x", pady=(0, 10))
        self.debt_kpis = {}
        for i, name in enumerate(["Total owed", "Debt-free", "Interest you'll pay", "With the extra"]):
            kp.columnconfigure(i, weight=1, uniform="dk")
            outer, inner = T.card(kp, padding=14)
            outer.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
            tk.Label(inner, text=name.upper(), bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["tiny"] + ("bold",)).pack(anchor="w")
            v = tk.Label(inner, text="–", bg=T.SURFACE, fg=T.TEXT, font=T.FONTS["kpi"], anchor="w")
            v.pack(anchor="w", fill="x")
            s = tk.Label(inner, text="", bg=T.SURFACE, fg=T.MUTED, font=T.FONTS["small"], anchor="w")
            s.pack(anchor="w", fill="x")
            self.debt_kpis[name] = (v, s)
        outer, self.debt_tree = self._table(page, [
            ("Debt", "Debt", 220, "w", True), ("Balance", "Balance", 100, "e", False), ("APR", "APR", 70, "e", False),
            ("Min", "Monthly payment", 135, "e", False), ("From", "From", 90, "w", False),
            ("Base", "Minimums only", 120, "w", False), ("Plan", "With your plan", 120, "w", False),
            ("Note", "Note", 260, "w", True)])
        outer.pack(fill="both", expand=True)
        self.debt_tree.bind("<Double-1>", lambda e: self.edit_debt())
        tk.Label(page, text="Cards come from your newest statement (balance, APR and minimum payment). Add loans "
                            "yourself. The extra goes to one debt at a time; when a debt is paid off, its payment "
                            "rolls to the next. Cards paid in full every month cost no interest and are left out.",
                 bg=T.BG, fg=T.MUTED, font=T.FONTS["small"], wraplength=1000, justify="left").pack(anchor="w", pady=(8, 0))

    def _debt_settings_changed(self):
        try:
            v = _parse_money(self.debt_extra.get()) or 0
        except ValueError:
            return
        self.settings["debt_extra"] = v
        self.settings["debt_strategy"] = "snowball" if self.debt_strategy.get().startswith("Snowball") else "avalanche"
        self._save_settings()
        self.render_debt()

    def render_debt(self):
        tv = self.debt_tree
        tv.delete(*tv.get_children())
        self._debt_index = {}
        debts = self._debts()
        extra = float(self.settings.get("debt_extra") or 0)
        strat = self.settings.get("debt_strategy", "avalanche")
        base, plan = simulate(debts, 0, strat, rollover=False), simulate(debts, extra, strat, rollover=True)
        today = date.today()
        live = [d for d in debts if d.include and d.balance > 0]
        owed = sum(d.balance for d in live)

        def kpi(name, val, sub="", col=None):
            v, s = self.debt_kpis[name]
            v.configure(text=val, fg=col or T.TEXT)
            s.configure(text=sub)
        kpi("Total owed", money(owed), f"{len(live)} debt(s) in the plan")
        if not live:
            for n in ("Debt-free", "Interest you'll pay", "With the extra"):
                kpi(n, "–")
        else:
            if plan.never:
                kpi("Debt-free", "Never", "a payment doesn't cover its interest", T.BAD)
            else:
                kpi("Debt-free", month_label(today, plan.months), f"in {plan.months} months", T.GOOD)
            kpi("Interest you'll pay", money(plan.interest), "")
            if extra > 0 and not base.never and not plan.never:
                kpi("With the extra", f"{base.months - plan.months} months",
                    f"sooner \u00B7 {money(base.interest - plan.interest)} less interest", T.GOOD)
            elif extra > 0 and base.never and not plan.never:
                kpi("With the extra", "Pays it off", "minimums alone never would", T.GOOD)
            else:
                kpi("With the extra", "–", "type an amount above")
        for i, d in enumerate(debts):
            key = d.key or d.name

            def when(p, key=key):
                if key in p.never:
                    return "never"
                return month_label(today, p.done[key]) if key in p.done else ""
            tags = [] if d.include and d.balance > 0 else ["muted"]
            if d.include and key in plan.never:
                tags = ["bad"]
            if i % 2:
                tags.append("odd")
            iid = str(i)
            self._debt_index[iid] = d
            note = d.note if d.include else (d.note or "not in the plan")
            if d.include and not d.apr:
                note = "add the APR for an accurate plan" + (" · " + d.note if d.note else "")
            tv.insert("", "end", iid=iid, tags=tags, values=(
                d.name, f"{d.balance:,.2f}", f"{d.apr:.2f}%" if d.apr else "–",
                f"{d.minimum:,.2f}" if d.minimum else "–", "statement" if d.source == "statement" else "you",
                when(base) if d.include else "", when(plan) if d.include else "", note))

    def edit_debt(self, new=False):
        d = None
        if not new:
            sel = self.debt_tree.selection()
            d = self._debt_index.get(sel[0]) if sel and hasattr(self, "_debt_index") else None
            if not d:
                messagebox.showinfo(self.APP_NAME, "Select a debt first, or click 'Add a debt'.")
                return
        win, body = self._dialog("Add a debt" if new else "Edit debt")
        nv, nw = self._field(body, "Name", "" if new else d.name, hint="e.g. Car loan, Student loan")
        if d and d.source == "statement":
            nw.configure(state="disabled")
        bv, _ = self._field(body, "Balance owed", "" if new else f"{d.balance:.2f}", width=14)
        av, _ = self._field(body, "APR (yearly interest rate, %)", "" if new or not d.apr else f"{d.apr:g}", width=14,
                            hint="On your statement as 'Annual Percentage Rate'. 0 for an interest-free loan.")
        mv, _ = self._field(body, "Monthly payment", "" if new or not d.minimum else f"{d.minimum:.2f}", width=14,
                            hint="The minimum or the fixed loan payment.")
        inc = tk.BooleanVar(value=True if new else d.include)
        ttk.Checkbutton(body, text="Include in the payoff plan", variable=inc).pack(anchor="w", pady=(8, 0))

        def ok():
            try:
                bal, apr, mn = _parse_money(bv.get()) or 0, _parse_money(av.get()) or 0, _parse_money(mv.get()) or 0
            except ValueError:
                messagebox.showwarning(self.APP_NAME, "Enter numbers like 2500, 24.99 and 75.", parent=win)
                return
            name = nv.get().strip()
            if new and not name:
                messagebox.showwarning(self.APP_NAME, "Give the debt a name.", parent=win)
                return
            saved = self.settings.setdefault("debts", {})
            key = ("you:" + name) if new else (d.key or d.name)
            entry = saved.setdefault(key, {})
            entry.update({"balance": round(bal, 2), "apr": apr, "minimum": round(mn, 2), "include": bool(inc.get())})
            if new or (d and d.source == "you"):
                entry.update({"user": True, "name": name or d.name})
            self._save_settings()
            win.destroy()
            self.render_debt()
        self._finish_dialog(win, body, ok, nw if new else bv)

    def remove_debt(self):
        sel = self.debt_tree.selection()
        d = self._debt_index.get(sel[0]) if sel and hasattr(self, "_debt_index") else None
        if not d:
            return
        saved = self.settings.setdefault("debts", {})
        key = d.key or d.name
        if d.source == "you":
            saved.pop(key, None)
        else:
            saved.setdefault(key, {})["removed"] = True
        self._save_settings()
        self.render_debt()

    # ================================================================ rules & backup
    def _build_rules(self, page):
        top = tk.Frame(page, bg=T.BG)
        top.pack(fill="x", pady=(0, 10))
        T.Button(top, "Add rule…", self.add_rule_dialog, style="primary").pack(side="left")
        T.Button(top, "Change category…", self.change_rule_category).pack(side="left", padx=6)
        T.Button(top, "Delete", self.delete_rules, style="danger").pack(side="left")
        T.Button(top, "Restore from backup…", self.restore_choices).pack(side="right")
        T.Button(top, "Back up…", self.backup_choices).pack(side="right", padx=6)
        T.Button(top, "Keyword list…", self.open_keyword_file).pack(side="right")
        outer, self.rules_tree = self._table(page, [
            ("Type", "Type", 230, "w", False), ("Match", "Applies to", 320, "w", True),
            ("Result", "Result", 240, "w", False), ("Count", "Transactions now", 130, "center", False)])
        outer.pack(fill="both", expand=True)
        self.rules_tree.bind("<Double-1>", lambda e: self.change_rule_category())
        tk.Label(page, text="Everything you've taught the app. Select rows and Delete to undo them (select several "
                            "with Ctrl/Shift). Back up saves all of it, plus budgets, tags and debts, to one file.",
                 bg=T.BG, fg=T.MUTED, font=T.FONTS["small"], wraplength=1000, justify="left").pack(anchor="w", pady=(8, 0))

    def _rule_items(self):
        txs = self.transactions
        by_uid = {t.uid: t for t in txs}
        items = []
        for m, c in sorted(self.cat.overrides.items(), key=lambda kv: kv[0].lower()):
            items.append(dict(kind="override", key=m, type="Company → category", match=m, result=c,
                              count=sum(1 for t in txs if t.merchant == m)))
        for r in self.cat.user_rules:
            txt = r.get("contains", "")
            items.append(dict(kind="contains", key=txt, type="Description contains → category", match=txt,
                              result=r.get("category", ""), count=sum(1 for t in txs if txt in t.description.upper())))
        for uid, c in self.settings.get("tx_categories", {}).items():
            t = by_uid.get(uid)
            items.append(dict(kind="tx_cat", key=uid, type="One transaction → category",
                              match=f"{t.date} {t.description}" if t else uid, result=c, count=1 if t else 0))
        for i, r in enumerate(self.settings.get("tag_rules", [])):
            t = by_uid.get(r.get("value")) if r.get("by") == "tx" else None
            match = (f"{t.date} {t.description}" if t else r.get("value")) if r.get("by") == "tx" else r.get("value")
            label = {"company": "Company → tag", "contains": "Description contains → tag",
                     "tx": "One transaction → tag"}.get(r.get("by"), "Tag")
            n = sum(1 for x in txs if r.get("tag") in getattr(x, "tags", []) and (
                (r.get("by") == "company" and x.merchant == r.get("value")) or
                (r.get("by") == "contains" and str(r.get("value", "")).upper() in x.description.upper()) or
                (r.get("by") == "tx" and x.uid == r.get("value"))))
            items.append(dict(kind="tag", key=i, type=label, match=match, result="tag: " + r.get("tag", ""), count=n))
        for key, label, res in (("excluded", "Excluded", "not counted"), ("direction_flips", "Money in/out flipped",
                                                                             "flipped"),
                                ("not_duplicates", "Not a duplicate", "counted")):
            for uid in self.settings.get(key, []):
                t = by_uid.get(uid)
                items.append(dict(kind=key, key=uid, type=label, match=f"{t.date} {t.description}" if t else uid,
                                  result=res, count=1 if t else 0))
        for m, yes in sorted(self.settings.get("pay_sources", {}).items()):
            items.append(dict(kind="pay_sources", key=m, type="Job income (savings rate)", match=m,
                              result="counts as job pay" if yes else "not job pay",
                              count=sum(1 for t in txs if t.merchant == m and t.is_credit)))
        names = {r.sha1: os.path.basename(r.path) for r in self.file_results}
        for sha in self.settings.get("include_files", []):
            items.append(dict(kind="include_files", key=sha, type="Included non-statement file",
                              match=names.get(sha, sha[:12]), result="included", count=0))
        return items

    def render_rules(self):
        tv = self.rules_tree
        tv.delete(*tv.get_children())
        self._rule_index = {}
        for i, it in enumerate(self._rule_items()):
            iid = str(i)
            self._rule_index[iid] = it
            tags = ["muted"] if it["count"] == 0 and it["kind"] not in ("include_files",) else []
            if i % 2:
                tags.append("odd")
            tv.insert("", "end", iid=iid, tags=tags, values=(it["type"], it["match"], it["result"], it["count"]))

    def _selected_rules(self):
        return [self._rule_index[i] for i in self.rules_tree.selection() if i in getattr(self, "_rule_index", {})]

    def add_rule_dialog(self):
        win, body = self._dialog("Add a rule")
        tv, tw = self._field(body, "When the description contains", "",
                             hint="Not case-sensitive, e.g. OPENHOUSETEXAS or COSTCO GAS.")
        cv, _ = self._field(body, "Set the category to", "", values=self.cat.all_categories())

        def ok():
            txt, c = tv.get().strip(), cv.get().strip()
            if len(txt) < 3 or not c:
                messagebox.showwarning(self.APP_NAME, "Type at least 3 characters and pick a category.", parent=win)
                return
            self.cat.add_rule(txt, c)
            win.destroy()
            self.rebuild()
        self._finish_dialog(win, body, ok, tw)

    def change_rule_category(self):
        sel = [it for it in self._selected_rules() if it["kind"] in ("override", "contains", "tx_cat")]
        if not sel:
            messagebox.showinfo(self.APP_NAME, "Select a category rule first.")
            return
        win, body = self._dialog("Change category")
        cv, cw = self._field(body, f"New category for {len(sel)} rule(s)", sel[0]["result"],
                             values=self.cat.all_categories())

        def ok():
            c = cv.get().strip()
            if not c:
                return
            for it in sel:
                if it["kind"] == "override":
                    self.cat.set_override(it["key"], c)
                elif it["kind"] == "contains":
                    self.cat.add_rule(it["key"], c)
                else:
                    self.settings.setdefault("tx_categories", {})[it["key"]] = c
            self._save_settings()
            win.destroy()
            self.rebuild()
        self._finish_dialog(win, body, ok, cw)

    def delete_rules(self):
        sel = self._selected_rules()
        if not sel or not messagebox.askyesno(self.APP_NAME, f"Delete {len(sel)} rule(s)? The app goes back to "
                                                             "deciding these itself."):
            return
        tag_idx = sorted((it["key"] for it in sel if it["kind"] == "tag"), reverse=True)
        for it in sel:
            k = it["kind"]
            if k == "override":
                self.cat.remove_override(it["key"])
            elif k == "contains":
                self.cat.remove_rule(it["key"])
            elif k == "tx_cat":
                self.settings.get("tx_categories", {}).pop(it["key"], None)
            elif k == "pay_sources":
                self.settings.get("pay_sources", {}).pop(it["key"], None)
            elif k in ("excluded", "direction_flips", "not_duplicates", "include_files"):
                self.settings[k] = [x for x in self.settings.get(k, []) if x != it["key"]]
        rules = self.settings.get("tag_rules", [])
        for i in tag_idx:
            if 0 <= i < len(rules):
                rules.pop(i)
        self._save_settings()
        self.rebuild()

    def open_keyword_file(self):
        path = self.cat.rules_path
        if not os.path.exists(path):
            self.cat.reload()
        if not messagebox.askyesno(self.APP_NAME, "The keyword list is a text file: each category with the words "
                                                  "that put a transaction in it. Open it in your text editor?\n\n"
                                                  "After saving your changes, click Analyze to use them.\n\n" + path):
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606 - opens a local file with its default app
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-t", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror(self.APP_NAME, f"Couldn't open the file: {e}\n\n{path}")

    def backup_choices(self):
        p = filedialog.asksaveasfilename(defaultextension=".json",
                                         initialfile=f"spending-analyzer-backup-{date.today():%Y-%m-%d}.json",
                                         filetypes=[("Backup", "*.json")])
        if not p:
            return
        data = backup.make_backup(self.settings, self.cat)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.set_status(f"Backup saved: {p} ({backup.summarize(data)})", T.GOOD)

    def restore_choices(self):
        p = filedialog.askopenfilename(filetypes=[("Backup", "*.json"), ("All files", "*.*")])
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror(self.APP_NAME, f"Couldn't read that file: {e}")
            return
        problem = backup.validate(data)
        if problem:
            messagebox.showerror(self.APP_NAME, problem)
            return
        if not messagebox.askyesno(self.APP_NAME, f"Replace your current choices with this backup from "
                                                  f"{data.get('created', 'an earlier date')}?\n\n{backup.summarize(data)}"):
            return
        backup.restore(data, self.settings, self.cat)
        self._save_settings()
        self.rebuild()
        self.set_status("Backup restored.", T.GOOD)

    # ================================================================ needs review
    def _build_review(self, page):
        top = tk.Frame(page, bg=T.BG)
        top.pack(fill="x", pady=(0, 10))
        T.Button(top, "Approve", self.approve_review, style="primary").pack(side="left")
        T.Button(top, "Set category\u2026", self.review_set_category).pack(side="left", padx=6)
        T.Button(top, "Show transactions", self._review_drill).pack(side="left")
        self.review_sum = tk.Label(top, text="", bg=T.BG, fg=T.TEXT, font=T.FONTS["bold"])
        self.review_sum.pack(side="right")
        outer, self.review_tree = self._table(page, [
            ("Company", "Company", 200, "w", False), ("Why", "Why it's here", 260, "w", False),
            ("Proposed", "Category", 190, "w", False), ("Count", "Transactions", 100, "center", False),
            ("Total", "Total", 100, "e", False), ("Example", "Example", 300, "w", True)])
        outer.pack(fill="both", expand=True)
        self.review_tree.bind("<Double-1>", self._review_drill)
        tk.Label(page, text="Approve confirms the category shown (select rows first, or approve everything listed; "
                            "rows with no category are skipped, use Set category for those); "
                            "the app remembers it for that company and stops asking. Set category picks a different "
                            "one. Approved choices are on Rules & backup, where you can undo them.",
                 bg=T.BG, fg=T.MUTED, font=T.FONTS["small"], wraplength=1000, justify="left").pack(anchor="w", pady=(8, 0))

    def render_review(self):
        tv = self.review_tree
        tv.delete(*tv.get_children())
        self._review_index = {}
        items = needs_review(self._scoped()) if self.transactions else []
        for i, it in enumerate(items):
            iid = str(i)
            self._review_index[iid] = it
            tags = ["warn"] if it.reason.startswith("Possible card payment") else []
            if i % 2:
                tags.append("odd")
            tv.insert("", "end", iid=iid, tags=tags, values=(
                it.merchant, it.reason, "\u2013 (pick one)" if it.reason == "No category" else it.proposed, it.count,
                ("+" if it.money_in else "") + f"{it.total:,.2f}", it.example))
        n = len(items)
        self.review_sum.configure(text=f"{n} to review \u00B7 {sum(i.count for i in items)} transactions" if n else
                                  "Nothing to review \u2713", fg=T.TEXT if n else T.GOOD)
        row, bar, lbl = self.nav["review"]
        icon = next(ic for k, _, ic, _ in self.PAGES if k == "review")
        lbl.configure(text=f"{icon}   Needs review" + (f"  ({n})" if n else ""))

    def _review_selected(self, all_if_none=False):
        sel = [self._review_index[i] for i in self.review_tree.selection() if i in getattr(self, "_review_index", {})]
        if not sel and all_if_none:
            sel = list(getattr(self, "_review_index", {}).values())
        return sel

    def approve_review(self):
        picked = bool(self.review_tree.selection())
        items = self._review_selected(all_if_none=True)
        if not items:
            return
        if not picked and not messagebox.askyesno(
                self.APP_NAME, f"Approve all {len(items)} rows with the category shown? (Select rows first to "
                               "approve only some.)"):
            return
        ok = [it for it in items if it.reason != "No category"]
        skipped = len(items) - len(ok)
        for it in ok:
            self.cat.set_override(it.merchant, it.proposed)
        self.rebuild()
        msg = f"Approved {len(ok)} \u00B7 remembered for those companies."
        if skipped:
            msg += f" {skipped} with no category skipped: use Set category for those."
        self.set_status(msg, T.GOOD if ok else T.WARN)

    def review_set_category(self):
        items = self._review_selected()
        if not items:
            messagebox.showinfo(self.APP_NAME, "Select one or more rows first.")
            return
        win, body = self._dialog("Set category")
        cv, cw = self._field(body, f"Category for {len(items)} compan{'y' if len(items) == 1 else 'ies'}",
                             items[0].proposed, values=self.cat.all_categories(),
                             hint="Remembered for these companies; undo it on Rules & backup.")

        def ok():
            c = cv.get().strip()
            if not c:
                return
            for it in items:
                self.cat.set_override(it.merchant, c)
            win.destroy()
            self.rebuild()
        self._finish_dialog(win, body, ok, cw)

    def _review_drill(self, e=None):
        items = self._review_selected()
        if items:
            self.search_var.set(items[0].merchant)
            self.cat_filter.set("All categories")
            self.tag_filter.set("All tags")
            self.show_credits.set(True)
            self.show_hidden.set(True)
            self.render_transactions()
            self.show_page("transactions")
