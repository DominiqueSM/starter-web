"""Spending analysis: totals, recurring charges, and cut-back suggestions."""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .categorize import DISCRETIONARY, NON_SPENDING


@dataclass
class Recurring:
    merchant: str
    category: str
    typical_amount: float
    count: int
    months: int
    last_date: date
    frequency: str            # Monthly | Weekly | Yearly | Irregular
    monthly_cost: float
    price_change: tuple | None = None   # (old, new)


@dataclass
class Suggestion:
    title: str
    detail: str
    monthly_savings: float = 0.0
    priority: int = 2        # 1 = high, 2 = medium, 3 = info
    items: list = field(default_factory=list)


@dataclass
class Analysis:
    spending: list
    total_spent: float
    total_in: float
    months: float
    first_date: date | None
    last_date: date | None
    by_category: list           # [(cat, total)] desc
    by_month: list              # [("YYYY-MM", total)]
    by_month_category: dict     # {"YYYY-MM": {cat: total}}
    top_merchants: list         # [(merchant, total, count)]
    recurring: list
    suggestions: list
    potential_monthly_savings: float


BILL_CATEGORIES = {"Utilities", "Phone & Internet", "Insurance", "Housing"}


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _months_span(first: date, last: date) -> float:
    # Statements cover whole calendar months, so count the months from first to last
    return float((last.year - first.year) * 12 + last.month - first.month + 1)


def money(x: float) -> str:
    return f"${x:,.2f}"


def find_recurring(spending) -> list[Recurring]:
    groups = defaultdict(list)
    for t in spending:
        groups[t.merchant].append(t)
    out = []
    for merchant, txs in groups.items():
        if len(txs) < 2:
            continue
        txs = sorted(txs, key=lambda t: t.date)
        months = {_ym(t.date) for t in txs}
        amounts = [t.amount for t in txs]
        med = statistics.median(amounts)
        cat = txs[-1].category
        if cat in ("Fees & Interest", "Cash & ATM"):
            continue
        # Amount consistency: subscriptions repeat (almost) the same amount; bills may vary more
        tol = 0.25 if cat in BILL_CATEGORIES else 0.05
        consistent = [a for a in amounts if abs(a - med) <= max(1.0, med * tol)]
        distinct = {round(x, 2) for x in amounts}
        few_price_levels = len(distinct) <= 3 and len(amounts) > len(distinct)  # e.g. a price increase
        if len(consistent) < max(2, int(len(amounts) * 0.7)) and not few_price_levels:
            continue
        gaps = [(b.date - a.date).days for a, b in zip(txs, txs[1:])]
        gaps = [g for g in gaps if g > 0] or [0]
        gap = statistics.median(gaps)
        if 25 <= gap <= 35 and len(months) >= 2:
            freq, per_month = "Monthly", med
        elif 5 <= gap <= 9 and len(txs) >= 4:
            freq, per_month = "Weekly", med * 4.33
        elif 12 <= gap <= 17 and len(txs) >= 3:
            freq, per_month = "Every 2 weeks", med * 2.17
        elif 80 <= gap <= 100:
            freq, per_month = "Quarterly", med / 3
        elif 350 <= gap <= 380:
            freq, per_month = "Yearly", med / 12
        else:
            continue
        price_change = None
        first_amt, last_amt = txs[0].amount, txs[-1].amount
        if (len(distinct) <= 3 and last_amt == max(amounts) and amounts.count(first_amt) >= 1
                and amounts.count(last_amt) >= 1 and last_amt > first_amt * 1.03 and last_amt - first_amt >= 0.5):
            price_change = (first_amt, last_amt)
            per_month *= last_amt / med   # cost going forward is the new price
            med = last_amt
        out.append(Recurring(
            merchant=merchant, category=txs[-1].category, typical_amount=round(med, 2), count=len(txs),
            months=len(months), last_date=txs[-1].date, frequency=freq, monthly_cost=round(per_month, 2),
            price_change=price_change,
        ))
    out.sort(key=lambda r: -r.monthly_cost)
    return out


def analyze(transactions) -> Analysis:
    spending = [t for t in transactions if t.is_spending and t.category not in NON_SPENDING]
    credits = [t for t in transactions if t.is_credit and not t.excluded and t.category != "Transfers & Payments"]
    total_spent = sum(t.amount for t in spending)
    total_in = sum(t.amount for t in credits)

    if spending:
        first = min(t.date for t in spending)
        last = max(t.date for t in spending)
        months = _months_span(first, last)
    else:
        first = last = None
        months = 1.0

    cat = defaultdict(float)
    mon = defaultdict(float)
    mon_cat = defaultdict(lambda: defaultdict(float))
    merch = defaultdict(lambda: [0.0, 0])
    for t in spending:
        cat[t.category] += t.amount
        mon[_ym(t.date)] += t.amount
        mon_cat[_ym(t.date)][t.category] += t.amount
        merch[t.merchant][0] += t.amount
        merch[t.merchant][1] += 1

    by_category = sorted(cat.items(), key=lambda kv: -kv[1])
    by_month = sorted(mon.items())
    top_merchants = sorted(((m, v[0], v[1]) for m, v in merch.items()), key=lambda x: -x[1])[:25]
    recurring = find_recurring(spending)

    a = Analysis(
        spending=spending, total_spent=total_spent, total_in=total_in, months=months,
        first_date=first, last_date=last, by_category=by_category, by_month=by_month,
        by_month_category={k: dict(v) for k, v in mon_cat.items()}, top_merchants=top_merchants,
        recurring=recurring, suggestions=[], potential_monthly_savings=0.0,
    )
    a.suggestions = build_suggestions(a)
    a.potential_monthly_savings = sum(s.monthly_savings for s in a.suggestions)
    return a


def build_suggestions(a: Analysis) -> list[Suggestion]:
    S = []
    if not a.spending:
        return S
    per_month = {c: v / a.months for c, v in a.by_category}
    total_pm = a.total_spent / a.months

    # 1. Fees & interest: 100% avoidable
    fees = [t for t in a.spending if t.category == "Fees & Interest"]
    if fees:
        tot = sum(t.amount for t in fees)
        S.append(Suggestion(
            "Stop paying fees and interest",
            f"You paid {money(tot)} in fees/interest ({len(fees)} charges). These are usually fully avoidable: "
            "pay card balances in full, set up low-balance alerts to prevent overdrafts, use in-network ATMs, "
            "and ask your bank to waive or refund fees (it often works for a first request).",
            monthly_savings=tot / a.months, priority=1,
            items=[f"{t.date}  {t.description}  {money(t.amount)}" for t in sorted(fees, key=lambda t: t.date)],
        ))

    # 2. Subscriptions
    not_subs = {"Housing", "Utilities", "Insurance", "Phone & Internet", "Auto & Transport", "Education",
                "Fees & Interest", "Groceries", "Gas & Fuel", "Dining Out", "Fast Food", "Coffee Shops",
                "Food Delivery", "Bars & Alcohol", "Health & Medical", "Cash & ATM", "Rideshare & Taxi"}
    subs = [r for r in a.recurring if r.category not in not_subs]
    if subs:
        tot = sum(r.monthly_cost for r in subs)
        streaming = [r for r in subs if r.category == "Streaming & Subscriptions"]
        extra = ""
        if len(streaming) >= 3:
            extra = (f" You have {len(streaming)} streaming/subscription services; rotating them "
                     "(keep one or two at a time, switch monthly) typically halves this cost.")
        S.append(Suggestion(
            "Audit your recurring subscriptions",
            f"{len(subs)} recurring charges cost about {money(tot)}/month ({money(tot * 12)}/year). "
            f"Cancel anything you haven't used in the last month.{extra} Estimate assumes you cut about a third.",
            monthly_savings=tot / 3, priority=1,
            items=[f"{r.merchant}: {money(r.typical_amount)} {r.frequency.lower()}  (~{money(r.monthly_cost * 12)}/yr)"
                   for r in subs],
        ))

    # 3. Price increases on recurring charges
    hikes = [r for r in a.recurring if r.price_change]
    if hikes:
        S.append(Suggestion(
            "Recurring charges that went up in price",
            "These went up while you were paying for them. Call or chat to ask for a retention offer, "
            "downgrade the plan, or switch providers.",
            monthly_savings=sum(r.price_change[1] - r.price_change[0] for r in hikes), priority=2,
            items=[f"{r.merchant}: {money(r.price_change[0])} -> {money(r.price_change[1])}" for r in hikes],
        ))

    # 4. Eating out bundle
    food_cats = ["Dining Out", "Fast Food", "Food Delivery", "Coffee Shops", "Bars & Alcohol"]
    food_pm = sum(per_month.get(c, 0) for c in food_cats)
    groc_pm = per_month.get("Groceries", 0)
    if food_pm > 50:
        parts = ", ".join(f"{c} {money(per_month[c])}" for c in food_cats if per_month.get(c, 0) > 0)
        ratio = f" That's {food_pm / groc_pm:.1f}x what you spend on groceries." if groc_pm > 0 else ""
        S.append(Suggestion(
            "Eat out less often",
            f"Food & drink away from home averages {money(food_pm)}/month ({parts}).{ratio} "
            "Cooking a few more meals a week and packing lunch could cut this by about 30%.",
            monthly_savings=food_pm * 0.30, priority=1 if food_pm / max(total_pm, 1) > 0.15 else 2,
        ))

    # 5. Delivery specifically
    deliv = per_month.get("Food Delivery", 0)
    if deliv > 30:
        n = sum(1 for t in a.spending if t.category == "Food Delivery")
        S.append(Suggestion(
            "Switch delivery orders to pickup",
            f"{n} delivery orders, about {money(deliv)}/month. Delivery apps usually add 20-40% in fees, "
            "markups and tips; ordering pickup from the restaurant directly saves most of that.",
            monthly_savings=deliv * 0.25, priority=2,
        ))

    # 6. Coffee
    coffee = [t for t in a.spending if t.category == "Coffee Shops"]
    if len(coffee) >= 6:
        visits_pm = len(coffee) / a.months
        avg = sum(t.amount for t in coffee) / len(coffee)
        S.append(Suggestion(
            "Make coffee at home more often",
            f"About {visits_pm:.0f} coffee-shop visits a month at {money(avg)} each. Brewing at home on "
            "half of those days would save roughly this much.",
            monthly_savings=visits_pm * 0.5 * max(avg - 0.75, 0), priority=3,
        ))

    # 7. Frequent small purchases
    small = defaultdict(list)
    for t in a.spending:
        if t.amount < 20 and t.category not in ("Groceries", "Gas & Fuel", "Auto & Transport", "Coffee Shops"):
            small[t.merchant].append(t)
    small_hits = sorted(((m, ts) for m, ts in small.items() if len(ts) / a.months >= 4),
                        key=lambda x: -sum(t.amount for t in x[1]))
    if small_hits:
        S.append(Suggestion(
            "Small purchases add up",
            "Places you buy small things from several times a month. Individually cheap, together significant:",
            monthly_savings=sum(sum(t.amount for t in ts) for _, ts in small_hits) / a.months * 0.4, priority=3,
            items=[f"{m}: {len(ts)} purchases, {money(sum(t.amount for t in ts))} total" for m, ts in small_hits[:10]],
        ))

    # 8. Shopping share
    shop = per_month.get("Shopping", 0)
    if shop > 0 and shop / max(total_pm, 1) > 0.12 and shop > 100:
        S.append(Suggestion(
            "Cut back on shopping",
            f"Shopping is {money(shop)}/month ({shop / total_pm:.0%} of spending). Try a 48-hour rule before "
            "non-essential purchases, unsubscribe from store emails, and remove saved cards from shopping sites.",
            monthly_savings=shop * 0.2, priority=2,
        ))

    # 9. Rideshare
    ride = per_month.get("Rideshare & Taxi", 0)
    if ride > 40:
        S.append(Suggestion(
            "Use fewer rideshares",
            f"Rideshare/taxi averages {money(ride)}/month. Public transit, biking, or batching trips for "
            "some of these could cut it substantially.",
            monthly_savings=ride * 0.3, priority=2,
        ))

    # 10. Possible duplicate charges
    dups = []
    seen = {}
    for t in sorted(a.spending, key=lambda t: t.date):
        k = (t.merchant, t.amount)
        if k in seen and (t.date - seen[k].date).days <= 1 and t.source_file == seen[k].source_file \
                and t.category not in ("Groceries", "Coffee Shops", "Fast Food", "Gas & Fuel", "Cash & ATM"):
            dups.append((seen[k], t))
        seen[k] = t
    if dups:
        S.append(Suggestion(
            "Possible duplicate charges",
            "The same merchant charged the same amount within a day. These may be legitimate, but check "
            "them and dispute any double-charges with your bank.",
            monthly_savings=0, priority=1,
            items=[f"{b.date}  {b.description}  {money(b.amount)}  (also {a_.date})" for a_, b in dups[:15]],
        ))

    # 11. Category spikes (latest full month vs. average of the others)
    months_sorted = sorted(a.by_month_category)
    if len(months_sorted) >= 3:
        latest = months_sorted[-1]
        prev = months_sorted[:-1]
        spikes = []
        for c in {c for m in months_sorted for c in a.by_month_category[m]}:
            cur = a.by_month_category[latest].get(c, 0)
            avg = sum(a.by_month_category[m].get(c, 0) for m in prev) / len(prev)
            if cur > avg * 1.5 and cur - avg > 75:
                spikes.append((c, cur, avg))
        if spikes:
            spikes.sort(key=lambda x: -(x[1] - x[2]))
            S.append(Suggestion(
                f"Spending jumped in {latest}",
                "These categories were well above your usual monthly level in the most recent month:",
                monthly_savings=0, priority=2,
                items=[f"{c}: {money(cur)} vs. usual {money(avg)}" for c, cur, avg in spikes],
            ))

    # 12. Biggest discretionary categories overview
    disc = [(c, v) for c, v in per_month.items() if c in DISCRETIONARY]
    disc_total = sum(v for _, v in disc)
    if disc_total > 0:
        S.append(Suggestion(
            "Your discretionary spending",
            f"Non-essential categories add up to {money(disc_total)}/month ({disc_total / total_pm:.0%} of spending). "
            "Trimming each by 10% is often painless:",
            monthly_savings=0, priority=3,
            items=[f"{c}: {money(v)}/month  (10% = {money(v * 0.1)})" for c, v in sorted(disc, key=lambda x: -x[1])],
        ))

    other = per_month.get("Other", 0)
    if other / max(total_pm, 1) > 0.2:
        S.append(Suggestion(
            "Many transactions are uncategorised",
            f"{money(other)}/month is in 'Other'. In the Transactions tab, select transactions and use "
            "'Set category' to teach the app; it remembers the merchant for next time and improves these suggestions.",
            priority=3,
        ))

    S.sort(key=lambda s: (s.priority, -s.monthly_savings))
    return S


def summarize_groups(transactions, file_results, all_label="All folders") -> list[dict]:
    """Per-folder totals, plus an 'all' row at the top."""
    by_group = defaultdict(list)
    for t in transactions:
        by_group[t.group].append(t)
    files = defaultdict(int)
    for r in file_results:
        if r.status != "duplicate":
            files[getattr(r, "group", "")] += 1

    def row(name, txs, nfiles):
        a = analyze(txs)
        fees = sum(v for c, v in a.by_category if c == "Fees & Interest")
        return {"name": name, "files": nfiles, "transactions": len(txs), "spent": a.total_spent,
                "per_month": a.total_spent / a.months if a.spending else 0.0, "money_in": a.total_in,
                "fees": fees, "top_category": a.by_category[0][0] if a.by_category else "-",
                "first": a.first_date, "last": a.last_date}

    rows = [row(g, txs, files[g]) for g, txs in by_group.items()]
    rows.sort(key=lambda r: -r["spent"])
    return [row(all_label, transactions, sum(files.values()))] + rows
