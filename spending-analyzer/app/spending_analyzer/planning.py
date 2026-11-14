"""Budgets, tags and the debt payoff planner. Pure functions: the window code only displays the results."""
from __future__ import annotations

import calendar
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date

# ------------------------------------------------------------------ budgets


def complete_months(analysis) -> list[str]:
    """Months that the statements cover completely (the same months the cash-flow comparison uses).
    Without bank statements, every month except the last one (which is usually partial)."""
    if analysis.compare and analysis.compare.get("months"):
        return list(analysis.compare["months"])
    ms = [m for m, _ in analysis.by_month]
    return ms[:-1] if len(ms) > 1 else ms


def suggest_budgets(analysis, months_back: int = 3, step: int = 10) -> dict[str, float]:
    """Median monthly spending per category over the last few complete months, rounded up to the next $10.
    A starting point; trimming the discretionary ones is how you save."""
    ms = complete_months(analysis)[-months_back:]
    if not ms:
        return {}
    cats = {c for m in ms for c in analysis.by_month_category.get(m, {})}
    out = {}
    for c in cats:
        med = statistics.median(analysis.by_month_category.get(m, {}).get(c, 0.0) for m in ms)
        if med >= 1:
            out[c] = float(math.ceil(med / step) * step)
    return out


@dataclass
class BudgetRow:
    category: str
    budget: float
    spent: float
    typical: float          # median of the previous complete months
    remaining: float
    used: float             # spent / budget (0 if no budget)


def budget_rows(analysis, budgets: dict, month: str) -> list[BudgetRow]:
    spent = analysis.by_month_category.get(month, {})
    prev = [m for m in complete_months(analysis) if m < month][-3:]
    cats = sorted(set(budgets) | set(spent), key=lambda c: (-(budgets.get(c) or 0), -spent.get(c, 0), c))
    rows = []
    for c in cats:
        b = float(budgets.get(c) or 0)
        s = spent.get(c, 0.0)
        typ = statistics.median(analysis.by_month_category.get(m, {}).get(c, 0.0) for m in prev) if prev else 0.0
        rows.append(BudgetRow(c, b, s, typ, b - s, s / b if b else 0.0))
    return rows


def left_to_spend(rows: list[BudgetRow], month: str, today: date):
    """(left, per_day, days_left) for the current calendar month; None for other months."""
    y, m = int(month[:4]), int(month[5:])
    if (today.year, today.month) != (y, m):
        return None
    left = sum(r.remaining for r in rows if r.budget > 0)
    days = calendar.monthrange(y, m)[1] - today.day + 1
    return left, max(left, 0) / days, days


def over_budget(analysis, budgets: dict, month: str) -> list[BudgetRow]:
    return [r for r in budget_rows(analysis, budgets, month) if r.budget > 0 and r.spent > r.budget + 0.005]


# ------------------------------------------------------------------ tags

def apply_tags(transactions, rules: list[dict]) -> None:
    """rules: {"by": "company"|"contains"|"tx", "value": ..., "tag": ...}. Sets t.tags (sorted list)."""
    for t in transactions:
        tags = set()
        d = t.description.upper()
        for r in rules:
            by, v, tag = r.get("by"), str(r.get("value", "")), r.get("tag", "").strip()
            if not tag or not v:
                continue
            if (by == "company" and t.merchant == v) or (by == "contains" and v.upper() in d) or \
                    (by == "tx" and t.uid == v):
                tags.add(tag)
        t.tags = sorted(tags)


def spending_by_tag(analysis, transactions) -> list[dict]:
    """Per tag: total spent (refunds with the tag subtract), per month over the analysis span, count."""
    from .categorize import NON_SPENDING
    by = {}
    for t in transactions:
        if t.excluded or t.duplicate or not getattr(t, "tags", None):
            continue
        if t.category in NON_SPENDING:
            continue
        for tag in t.tags:
            row = by.setdefault(tag, {"tag": tag, "total": 0.0, "count": 0, "months": set()})
            row["total"] += -t.amount if t.is_credit else t.amount
            row["count"] += 1
            row["months"].add((t.date.year, t.date.month))
    out = []
    for r in by.values():
        r["per_month"] = r["total"] / max(analysis.months, 1)
        r["months"] = len(r["months"])
        out.append(r)
    return sorted(out, key=lambda r: -r["total"])


# ------------------------------------------------------------------ debt payoff

@dataclass
class Debt:
    name: str
    balance: float
    apr: float = 0.0
    minimum: float = 0.0
    source: str = "you"          # "statement" | "you"
    note: str = ""
    include: bool = True
    key: str = ""                # stable id (account key or your own name)


def debts_from_statements(file_results) -> list[Debt]:
    """One debt per card account: the newest statement's balance, APR and minimum payment.
    A card paid in full every month costs no interest; it's listed but left out of the plan."""
    latest = {}
    for r in file_results:
        i = r.info
        if i.kind != "card" or not i.account_key or i.closing_balance is None or not r.transactions:
            continue
        end = i.period_end or max(t.date for t in r.transactions)
        if i.account_key not in latest or end > latest[i.account_key][0]:
            latest[i.account_key] = (end, r)
    debts = []
    for key, (end, r) in latest.items():
        i = r.info
        paid = sum(t.amount for t in r.transactions if t.is_credit and t.category == "Transfers & Payments")
        in_full = i.opening_balance is not None and i.opening_balance > 0 and paid >= i.opening_balance - 0.01
        note = f"statement ending {end:%b %d, %Y}"
        if in_full:
            note += " - paid in full last month, so no interest"
        debts.append(Debt(name=key, balance=round(max(i.closing_balance, 0), 2), apr=i.apr or 0.0,
                          minimum=i.min_payment or 0.0, source="statement", note=note,
                          include=not in_full and i.closing_balance > 0, key=key))
    return sorted(debts, key=lambda d: -d.balance)


@dataclass
class Plan:
    months: int                      # months until debt-free (0 if nothing to pay)
    interest: float
    done: dict = field(default_factory=dict)        # key -> months until paid off
    never: list = field(default_factory=list)       # keys whose payment doesn't cover the interest
    order: list = field(default_factory=list)       # payoff order


def simulate(debts: list[Debt], extra: float = 0.0, strategy: str = "avalanche", rollover: bool = True,
             max_months: int = 600) -> Plan:
    """Month by month: interest is added, every minimum is paid, then the extra (plus minimums freed by debts
    already paid off, when rollover is on) goes to one debt at a time: highest APR first (avalanche) or
    smallest balance first (snowball)."""
    ds = [dict(key=d.key or d.name, bal=float(d.balance), apr=float(d.apr), min=float(d.minimum))
          for d in debts if d.include and d.balance > 0.005]
    plan = Plan(months=0, interest=0.0)
    if not ds:
        return plan
    freed = 0.0
    n = 0
    while any(d["bal"] > 0.005 for d in ds) and n < max_months:
        n += 1
        pool = extra + (freed if rollover else 0.0)
        for d in ds:
            if d["bal"] <= 0.005:
                continue
            i = d["bal"] * d["apr"] / 1200
            d["bal"] += i
            plan.interest += i
            pay = min(d["bal"], d["min"])
            d["bal"] -= pay
            if rollover:
                pool += d["min"] - pay     # a minimum bigger than what's left spills over
        live = [d for d in ds if d["bal"] > 0.005]
        live.sort(key=(lambda d: (d["bal"], -d["apr"])) if strategy == "snowball" else (lambda d: (-d["apr"], d["bal"])))
        for d in live:
            if pool <= 0.005:
                break
            pay = min(pool, d["bal"])
            d["bal"] -= pay
            pool -= pay
        for d in ds:
            if d["bal"] <= 0.005 and d["key"] not in plan.done:
                plan.done[d["key"]] = n
                plan.order.append(d["key"])
                freed += d["min"]
    plan.months = n if all(d["bal"] <= 0.005 for d in ds) else max_months
    plan.never = [d["key"] for d in ds if d["key"] not in plan.done]   # payment never outruns the interest
    plan.interest = round(plan.interest, 2)
    return plan


def month_label(today: date, months_ahead: int) -> str:
    i = today.year * 12 + today.month - 1 + months_ahead
    return f"{calendar.month_abbr[i % 12 + 1]} {i // 12}"
