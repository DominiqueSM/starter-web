"""Spending analysis: totals, recurring charges (grouped by company) and cut-back suggestions."""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .categorize import DISCRETIONARY, NON_SPENDING

SUBSCRIPTION_CATS = {"Streaming & Subscriptions", "Gaming", "Gym & Fitness"}
BILL_CATS = {"Housing", "Utilities", "Insurance", "Phone & Internet", "Loans & Debt", "Education",
             "Auto & Transport", "Kids & Pets"}
FOOD_CATS = ["Dining Out", "Fast Food", "Food Delivery", "Coffee Shops", "Bars & Alcohol"]
CARD_ISSUER_RE = re.compile(r"\b(CHASE|AMEX|AMERICAN EXPRESS|CITI|DISCOVER|CAPITAL ONE|CAP ONE|BARCLAY|SYNCHRONY"
                            r"|WELLS FARGO CARD|BK OF AMER|BANK OF AMERICA|APPLE ?CARD|GS BANK|US BANK|USAA)\b", re.I)
GENERIC_FIRST = {"PAYMENT", "ONLINE", "MOBILE", "CHECK", "THE", "POS", "DEBIT", "ACH", "CARD", "PURCHASE",
                 "AMERICAN", "FIRST", "CITY", "NEW", "SAN", "NORTH", "SOUTH", "EAST", "WEST", "BANK", "TRANSFER"}


@dataclass
class Recurring:
    merchant: str
    category: str
    typical_amount: float
    count: int
    months: int
    last_date: date
    frequency: str            # Monthly | Weekly | Every 2 weeks | Quarterly | Yearly
    monthly_cost: float
    kind: str = "Regular"     # Subscription | Bill / loan | Regular
    price_change: tuple | None = None   # (old, new)
    aliases: list = field(default_factory=list)


@dataclass
class Suggestion:
    title: str
    detail: str
    monthly_savings: float = 0.0
    priority: int = 2        # 1 = high, 2 = medium, 3 = info
    items: list = field(default_factory=list)
    confidence: str = "medium"   # high | medium | low
    kind: str = "save"           # save | warn | info


@dataclass
class Analysis:
    spending: list
    total_spent: float
    total_in: float
    income: float
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
    data_quality: float = 1.0   # share of transactions from statements that passed a self-check
    money_in: float = 0.0       # all real money in to bank accounts (pay, other deposits, money from people)
    refunds: float = 0.0        # refunds/returns, subtracted from spending
    cashflow: list = field(default_factory=list)   # one dict per month
    compare: dict | None = None                    # spending vs money in over months covered by bank statements


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _months_span(first: date, last: date) -> float:
    # Statements cover whole calendar months, so count the months from first to last
    return float((last.year - first.year) * 12 + last.month - first.month + 1)


def money(x: float) -> str:
    return f"${x:,.2f}"


# ------------------------------------------------------------------ recurring

def _merge_similar_merchants(groups: dict) -> dict:
    """Merge names that are clearly the same company, e.g. 'NTTA' and 'NTTA Autocharge'."""
    names = sorted(groups, key=len)
    parent = {n: n for n in names}

    def first_tok(n):
        return n.split()[0].upper() if n.split() else ""

    def med(n):
        return statistics.median(t.amount for t in groups[n])

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if parent[b] != b:
                continue
            fa, fb = first_tok(a), first_tok(b)
            prefix = b.upper().startswith(a.upper() + " ") or b.upper() == a.upper()
            same_first = (fa == fb and len(fa) >= 4 and fa not in GENERIC_FIRST
                          and abs(med(a) - med(b)) <= max(1.0, 0.1 * med(a)))
            if prefix or same_first:
                parent[b] = parent[a]
    merged = defaultdict(list)
    aliases = defaultdict(set)
    for n, txs in groups.items():
        merged[parent[n]].extend(txs)
        aliases[parent[n]].add(n)
    return {k: (v, sorted(aliases[k] - {k})) for k, v in merged.items()}


def _kind(category: str, monthly_cost: float, freq: str) -> str:
    if category in SUBSCRIPTION_CATS:
        return "Subscription"
    if category in BILL_CATS:
        return "Bill / loan"
    if category in ("Other", "Shopping", "Entertainment", "Hobbies") and freq in ("Monthly", "Yearly", "Quarterly"):
        return "Subscription" if monthly_cost <= 100 else "Bill / loan"
    return "Regular"


def find_recurring(spending) -> list[Recurring]:
    groups = defaultdict(list)
    for t in spending:
        groups[t.merchant].append(t)
    out = []
    for merchant, (txs, aliases) in _merge_similar_merchants(groups).items():
        # the same charge listed twice (e.g. two descriptions of one payment) counts once
        seen, uniq = set(), []
        for t in sorted(txs, key=lambda t: t.date):
            k = (t.date, t.amount)
            if k not in seen:
                seen.add(k)
                uniq.append(t)
        txs = uniq
        if len(txs) < 2:
            continue
        cat = max({t.category for t in txs}, key=lambda c: sum(1 for t in txs if t.category == c))
        if cat in ("Fees & Interest", "Cash & ATM"):
            continue
        months = {_ym(t.date) for t in txs}
        amounts = [t.amount for t in txs]
        med = statistics.median(amounts)
        tol = 0.25 if cat in BILL_CATS else 0.05
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
        if (len(distinct) <= 3 and last_amt == max(amounts) and last_amt > first_amt * 1.03
                and last_amt - first_amt >= 0.5):
            price_change = (first_amt, last_amt)
            per_month *= last_amt / med   # cost going forward is the new price
            med = last_amt
        out.append(Recurring(
            merchant=merchant, category=cat, typical_amount=round(med, 2), count=len(txs),
            months=len(months), last_date=txs[-1].date, frequency=freq, monthly_cost=round(per_month, 2),
            kind=_kind(cat, per_month, freq), price_change=price_change, aliases=aliases,
        ))
    out.sort(key=lambda r: -r.monthly_cost)
    return out


# ------------------------------------------------------------------ main

REFUND_RE = re.compile(r"\b(REFUND|RETURN|REVERSAL|REVERSED|CREDIT ADJ|ADJUSTMENT|CHARGEBACK|DISPUTE|RETURNED)\b", re.I)
NOT_MONEY_IN = {"Transfers & Payments", "Savings & Investments"}


def _is_refund(t) -> bool:
    """A credit that gives back money you spent (rather than new money coming in)."""
    if t.category in NOT_MONEY_IN or t.category == "Income":
        return False
    if t.kind == "card":
        return True                    # on a card, any credit that isn't a payment is a refund/credit
    return bool(REFUND_RE.search(t.description)) or t.category_source == "merchant"


def _month_days(ym: str):
    import calendar
    y, m = int(ym[:4]), int(ym[5:])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _covered(ym: str, spans) -> bool:
    """True if the statement periods in spans cover at least 90% of the month's days."""
    lo, hi = _month_days(ym)
    days = set()
    for s, e in spans:
        a, b = max(s, lo), min(e, hi)
        if a <= b:
            days.update(range(a.toordinal(), b.toordinal() + 1))
    return len(days) >= 0.9 * ((hi - lo).days + 1)


def analyze(transactions, data_quality: float = 1.0, coverage=None) -> Analysis:
    """coverage: optional list of (kind, start_date, end_date), one per statement, used to compare only
    months that the statements cover completely."""
    live = [t for t in transactions if not t.excluded and not t.duplicate]
    spending = [t for t in live if not t.is_credit and t.category not in NON_SPENDING]
    credits = [t for t in live if t.is_credit and t.category not in NOT_MONEY_IN]
    refunds = [t for t in credits if _is_refund(t)]
    money_in_txs = [t for t in credits if not _is_refund(t) and t.kind != "card"]
    income = sum(t.amount for t in money_in_txs if t.category == "Income")

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
    refund_total = 0.0
    for t in refunds:   # net refunds against the category they came from (never below zero)
        c = t.category if cat.get(t.category, 0) > 0 else max(cat, key=cat.get, default=None)
        if c is None:
            continue
        take = min(t.amount, cat[c])
        cat[c] -= take
        ym = _ym(t.date)
        mon[ym] = max(0.0, mon.get(ym, 0.0) - take)
        mon_cat[ym][c] = max(0.0, mon_cat[ym].get(c, 0.0) - take)
        refund_total += take
    cat = {c: v for c, v in cat.items() if v > 0.005}
    total_spent = sum(cat.values())

    if spending:
        first = min(t.date for t in spending)
        last = max(t.date for t in spending)
        months = _months_span(first, last)
    else:
        first = last = None
        months = 1.0

    # ---- cash flow, month by month
    rows = defaultdict(lambda: defaultdict(float))
    bank_months = set()
    for t in live:
        ym = _ym(t.date)
        if t.kind != "card":
            bank_months.add(ym)
        if t.is_credit:
            if t in money_in_txs:
                rows[ym]["income" if t.category == "Income" else "other_in"] += t.amount
            elif t in refunds:
                rows[ym]["refunds"] += t.amount
        else:
            if t.category in NON_SPENDING:
                key = {"Savings & Investments": "saved"}.get(t.category,
                                                             "card_payments" if t.transfer_match or "CARD" in
                                                             t.description.upper() or "CRD" in t.description.upper()
                                                             else "transfers")
                rows[ym][key] += t.amount
            else:
                rows[ym]["spent_card" if t.kind == "card" else "spent_bank"] += t.amount
    cashflow = []
    for ym in sorted(set(rows) | set(mon)):
        r = rows[ym]
        cashflow.append({"month": ym, "income": r["income"], "other_in": r["other_in"],
                         "money_in": r["income"] + r["other_in"], "spent": mon.get(ym, 0.0),
                         "spent_card": r["spent_card"], "spent_bank": r["spent_bank"], "refunds": r["refunds"],
                         "card_payments": r["card_payments"], "transfers": r["transfers"], "saved": r["saved"],
                         "has_bank": ym in bank_months, "partial": False})
    if coverage:
        bank_spans = [(s_, e_) for k, s_, e_ in coverage if k != "card"]
        card_spans = [(s_, e_) for k, s_, e_ in coverage if k == "card"]
        card_lo = min((s_ for s_, _ in card_spans), default=None)
        card_hi = max((e_ for _, e_ in card_spans), default=None)
        for c in cashflow:
            full_bank = _covered(c["month"], bank_spans)
            lo, hi = _month_days(c["month"])
            in_card_range = card_lo is not None and hi >= card_lo and lo <= card_hi
            full_card = not in_card_range or _covered(c["month"], card_spans)
            c["has_bank"] = c["has_bank"] and full_bank and full_card
            c["partial"] = not full_bank and c["month"] in bank_months or (full_bank and not full_card)
    compare = None
    cmp_rows = [c for c in cashflow if c["has_bank"] and (c["spent"] > 0 or c["money_in"] > 0)]
    if cmp_rows:
        compare = {"months": [c["month"] for c in cmp_rows],
                   "money_in": sum(c["money_in"] for c in cmp_rows),
                   "spent": sum(c["spent"] for c in cmp_rows),
                   "left_out": [c["month"] for c in cashflow if not c["has_bank"] and (c["spent"] > 0 or c["money_in"] > 0)]}

    a = Analysis(
        spending=spending, total_spent=total_spent, total_in=sum(t.amount for t in money_in_txs), income=income,
        months=months, first_date=first, last_date=last, by_category=sorted(cat.items(), key=lambda kv: -kv[1]),
        by_month=sorted(mon.items()), by_month_category={k: dict(v) for k, v in mon_cat.items()},
        top_merchants=sorted(((m, v[0], v[1]) for m, v in merch.items()), key=lambda x: -x[1])[:25],
        recurring=find_recurring(spending), suggestions=[], potential_monthly_savings=0.0,
        data_quality=data_quality, money_in=sum(t.amount for t in money_in_txs), refunds=refund_total,
        cashflow=cashflow, compare=compare,
    )
    a.suggestions = build_suggestions(a, transactions)
    a.potential_monthly_savings = sum(s.monthly_savings for s in a.suggestions)
    return a


def _confidence(a: Analysis, base: str = "high") -> str:
    order = ["low", "medium", "high"]
    lvl = order.index(base)
    if a.months < 2:
        lvl = min(lvl, 0)
    elif a.months < 3:
        lvl = min(lvl, 1)
    if a.data_quality < 0.6:
        lvl = min(lvl, 1)
    return order[lvl]


def build_suggestions(a: Analysis, all_txs) -> list[Suggestion]:
    S = []
    if not a.spending:
        return S
    per_month = {c: v / a.months for c, v in a.by_category}
    total_pm = a.total_spent / a.months

    # 0. Possible double counting: payments to card issuers still counted as spending
    suspects = [t for t in a.spending if t.kind != "card" and t.amount >= 100 and CARD_ISSUER_RE.search(t.description)
                and t.category not in ("Loans & Debt", "Housing", "Insurance")]
    if suspects:
        S.append(Suggestion(
            "Check: possible credit-card payments counted as spending",
            "These payments from a bank account look like they go to a card company. If they pay off a credit "
            "card whose purchases are already included, they are counted twice. Select them in Transactions and "
            "use 'Set category' > 'Transfers & Payments' (the app remembers it), or add that card's statements "
            "so they're matched automatically.",
            priority=1, kind="warn", confidence="medium",
            items=[f"{t.date}  {t.description}  {money(t.amount)}" for t in sorted(suspects, key=lambda t: t.date)][:20],
        ))

    # 1. Spending vs money in (only months covered by a bank statement, so card-only months don't skew it)
    c = a.compare
    if c is None:
        S.append(Suggestion(
            "Add a checking statement to compare with money coming in",
            "Only card statements were found, so there's nothing to compare spending against.",
            priority=3, kind="info", confidence="high"))
    elif c["money_in"] > 0:
        n = len(c["months"])
        inn, out = c["money_in"] / n, c["spent"] / n
        ratio = out / inn
        left = (f" Months not fully covered by your statements ({', '.join(c['left_out'][:4])}"
                f"{'...' if len(c['left_out']) > 4 else ''}) are left out of this comparison."
                if c["left_out"] else "")
        over = [r for r in a.cashflow if r["month"] in c["months"] and r["spent"] > r["money_in"]]
        items = [f"{r['month']}: in {money(r['money_in'])}, spent {money(r['spent'])} "
                 f"(cards {money(r['spent_card'])}, bank {money(r['spent_bank'])})" for r in over]
        if ratio > 1.0:
            S.append(Suggestion(
                "You spent more than came in",
                f"Over {n} month(s) with bank statements, spending averaged {money(out)}/month against "
                f"{money(inn)}/month coming in ({ratio:.0%}).{left} Card payments, transfers between your accounts "
                "and money moved to savings are not counted as spending. If this looks wrong, open the Cash flow "
                "page: it shows exactly what was counted each month.",
                priority=1, kind="warn", confidence=_confidence(a, "medium"), items=items))
        else:
            S.append(Suggestion(
                "Spending vs. money coming in",
                f"You spend {ratio:.0%} of what comes in ({money(out)} of {money(inn)} a month over {n} month(s)), "
                f"leaving about {money(inn - out)}/month.{left} A common target is spending under 80%.",
                priority=3, kind="info", confidence=_confidence(a, "medium"), items=items))

    # 2. Fees & interest: fully avoidable
    fees = [t for t in a.spending if t.category == "Fees & Interest"]
    if fees:
        tot = sum(t.amount for t in fees)
        S.append(Suggestion(
            "Stop paying fees and interest",
            f"You paid {money(tot)} in fees/interest ({len(fees)} charges). These are usually avoidable: pay "
            "card balances in full, set low-balance alerts to prevent overdrafts, use in-network ATMs, and ask "
            "the bank to waive fees (it often works the first time).",
            monthly_savings=tot / a.months, priority=1, confidence=_confidence(a),
            items=[f"{t.date}  {t.description}  {money(t.amount)}" for t in sorted(fees, key=lambda t: t.date)],
        ))

    # 3. Subscriptions (one line per company)
    subs = [r for r in a.recurring if r.kind == "Subscription"]
    if subs:
        tot = sum(r.monthly_cost for r in subs)
        streaming = [r for r in subs if r.category == "Streaming & Subscriptions"]
        extra = (f" {len(streaming)} of them are streaming/online services; rotating them (one or two at a time) "
                 "typically halves that part.") if len(streaming) >= 3 else ""
        S.append(Suggestion(
            "Audit your subscriptions",
            f"{len(subs)} subscriptions and memberships cost about {money(tot)}/month ({money(tot * 12)}/year). "
            f"Cancel anything you haven't used in the last month.{extra} The estimate assumes you cut about a third.",
            monthly_savings=tot / 3, priority=1, confidence=_confidence(a),
            items=[f"{r.merchant}: {money(r.typical_amount)} {r.frequency.lower()}  (~{money(r.monthly_cost * 12)}/yr)"
                   for r in subs],
        ))

    # 4. Price increases on recurring charges
    hikes = [r for r in a.recurring if r.price_change]
    if hikes:
        S.append(Suggestion(
            "Recurring charges that went up in price",
            "Ask for a retention offer, downgrade the plan, or switch providers.",
            monthly_savings=sum(r.price_change[1] - r.price_change[0] for r in hikes), priority=2,
            confidence=_confidence(a),
            items=[f"{r.merchant}: {money(r.price_change[0])} -> {money(r.price_change[1])}" for r in hikes],
        ))

    # 5. Eating out
    food_pm = sum(per_month.get(c, 0) for c in FOOD_CATS)
    groc_pm = per_month.get("Groceries", 0)
    if food_pm > 50:
        parts = ", ".join(f"{c} {money(per_month[c])}" for c in FOOD_CATS if per_month.get(c, 0) > 0)
        ratio = f" That's {food_pm / groc_pm:.1f}x your grocery spending." if groc_pm > 0 else ""
        S.append(Suggestion(
            "Eat out less often",
            f"Food & drink away from home averages {money(food_pm)}/month ({parts}).{ratio} Cooking a few more "
            "meals a week and packing lunch could cut this by about 30%.",
            monthly_savings=food_pm * 0.30, priority=1 if food_pm / max(total_pm, 1) > 0.15 else 2,
            confidence=_confidence(a),
        ))

    deliv = per_month.get("Food Delivery", 0)
    if deliv > 30:
        n = sum(1 for t in a.spending if t.category == "Food Delivery")
        S.append(Suggestion(
            "Switch delivery orders to pickup",
            f"{n} delivery orders, about {money(deliv)}/month. Apps usually add 20-40% in fees, markups and tips; "
            "ordering pickup directly saves most of that.",
            monthly_savings=deliv * 0.25, priority=2, confidence=_confidence(a)))

    coffee = [t for t in a.spending if t.category == "Coffee Shops"]
    if len(coffee) >= 6:
        visits_pm = len(coffee) / a.months
        avg = sum(t.amount for t in coffee) / len(coffee)
        S.append(Suggestion(
            "Make coffee at home more often",
            f"About {visits_pm:.0f} coffee-shop visits a month at {money(avg)} each. Brewing at home on half of "
            "those days would save roughly this much.",
            monthly_savings=visits_pm * 0.5 * max(avg - 0.75, 0), priority=3, confidence=_confidence(a)))

    # 6. Frequent small purchases
    small = defaultdict(list)
    for t in a.spending:
        if t.amount < 20 and t.category not in ("Groceries", "Gas & Fuel", "Auto & Transport", "Coffee Shops"):
            small[t.merchant].append(t)
    small_hits = sorted(((m, ts) for m, ts in small.items() if len(ts) / a.months >= 4),
                        key=lambda x: -sum(t.amount for t in x[1]))
    if small_hits:
        S.append(Suggestion(
            "Small purchases add up",
            "Places you buy small things from several times a month:",
            monthly_savings=sum(sum(t.amount for t in ts) for _, ts in small_hits) / a.months * 0.4, priority=3,
            confidence=_confidence(a, "medium"),
            items=[f"{m}: {len(ts)} purchases, {money(sum(t.amount for t in ts))} total" for m, ts in small_hits[:10]]))

    shop = per_month.get("Shopping", 0)
    if shop > 100 and shop / max(total_pm, 1) > 0.12:
        S.append(Suggestion(
            "Cut back on shopping",
            f"Shopping is {money(shop)}/month ({shop / total_pm:.0%} of spending). Try a 48-hour rule for "
            "non-essentials, unsubscribe from store emails, and remove saved cards from shopping sites.",
            monthly_savings=shop * 0.2, priority=2, confidence=_confidence(a, "medium")))

    ride = per_month.get("Rideshare & Taxi", 0)
    if ride > 40:
        S.append(Suggestion(
            "Use fewer rideshares",
            f"Rideshare/taxi averages {money(ride)}/month. Transit, biking or batching trips could cut it.",
            monthly_savings=ride * 0.3, priority=2, confidence=_confidence(a, "medium")))

    # 7. Fixed bills: worth a yearly review
    bills = [r for r in a.recurring if r.kind == "Bill / loan"]
    if bills:
        shoppable = sum(r.monthly_cost for r in bills if r.category in ("Phone & Internet", "Insurance"))
        S.append(Suggestion(
            "Review your fixed bills and loans",
            f"Regular bills and loan payments total about {money(sum(r.monthly_cost for r in bills))}/month. "
            "They're hard to cut day to day, but once a year: get insurance quotes, ask your phone/internet "
            "provider for current promotions, and check whether loans can be refinanced. "
            "Savings shown assume 10% off phone, internet and insurance.",
            monthly_savings=shoppable * 0.10, priority=3, kind="info", confidence=_confidence(a, "medium"),
            items=[f"{r.merchant} ({r.category}): {money(r.typical_amount)} {r.frequency.lower()}" for r in bills]))

    # 8. Possible duplicate charges (same statement, same merchant & amount within a day)
    dups, seen = [], {}
    for t in sorted(a.spending, key=lambda t: t.date):
        k = (t.merchant, t.amount)
        if k in seen and (t.date - seen[k].date).days <= 1 and t.source_file == seen[k].source_file \
                and t.category not in ("Groceries", "Coffee Shops", "Fast Food", "Gas & Fuel", "Cash & ATM",
                                       "Auto & Transport", "Convenience Stores"):
            dups.append((seen[k], t))
        seen[k] = t
    if dups:
        S.append(Suggestion(
            "Possible duplicate charges",
            "The same merchant charged the same amount within a day. Check them and dispute any double charges.",
            priority=1, kind="warn", confidence="medium",
            items=[f"{b.date}  {b.description}  {money(b.amount)}  (also {a_.date})" for a_, b in dups[:15]]))

    # 9. Spikes in the latest month
    months_sorted = sorted(a.by_month_category)
    if len(months_sorted) >= 3:
        latest, prev = months_sorted[-1], months_sorted[:-1]
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
                "These categories were well above your usual level in the most recent month:",
                priority=2, kind="info", confidence=_confidence(a, "medium"),
                items=[f"{c}: {money(cur)} vs. usual {money(avg)}" for c, cur, avg in spikes]))

    disc = [(c, v) for c, v in per_month.items() if c in DISCRETIONARY]
    disc_total = sum(v for _, v in disc)
    if disc_total > 0:
        S.append(Suggestion(
            "Your discretionary spending",
            f"Non-essential categories add up to {money(disc_total)}/month ({disc_total / total_pm:.0%} of "
            "spending). Trimming each by 10% is often painless:",
            priority=3, kind="info", confidence=_confidence(a),
            items=[f"{c}: {money(v)}/month  (10% = {money(v * 0.1)})" for c, v in sorted(disc, key=lambda x: -x[1])]))

    unknown = sum(t.amount for t in a.spending if t.category == "Other")
    guessed = sum(1 for t in a.spending if t.category_source == "guess")
    if unknown / max(a.total_spent, 1) > 0.15 or guessed > 10:
        S.append(Suggestion(
            "Help the app categorise better",
            f"{money(unknown / a.months)}/month is uncategorised ('Other') and {guessed} transactions were "
            "categorised from a broad keyword. Double-click a transaction to set its category; the app "
            "remembers it for that merchant.",
            priority=3, kind="info", confidence="high"))

    if a.months < 2:
        S.append(Suggestion(
            "Add more statements for better suggestions",
            f"Only {a.months:.0f} month of data. Recurring charges, spikes and averages become reliable with "
            "3+ months.", priority=2, kind="info", confidence="high"))
    if a.data_quality < 0.8:
        S.append(Suggestion(
            "Some statements didn't pass the self-check",
            f"Only {a.data_quality:.0%} of transactions come from statements whose numbers add up to the printed "
            "balances. Open the Files page to see which ones and why.", priority=2, kind="warn", confidence="high"))

    S.sort(key=lambda s: (s.priority, {"warn": 0, "save": 1, "info": 2}[s.kind], -s.monthly_savings))
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
