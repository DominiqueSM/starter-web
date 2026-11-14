"""Things that need you: transactions the app wasn't sure about, and statements that seem to be missing."""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .categorize import NON_SPENDING
from .insights import CARD_ISSUER_RE

# ------------------------------------------------------------------ needs review


@dataclass
class ReviewItem:
    merchant: str
    reason: str
    proposed: str           # the category Approve will confirm
    money_in: bool
    txs: list = field(default_factory=list)

    @property
    def count(self):
        return len(self.txs)

    @property
    def total(self):
        return sum(t.amount for t in self.txs)

    @property
    def example(self):
        return self.txs[0].description if self.txs else ""


def _reason(t):
    """(reason, proposed category) if the app wasn't sure about this transaction, else None."""
    if t.category_source in ("learned", "matched"):
        return None
    if (not t.is_credit and t.kind != "card" and t.amount >= 100 and CARD_ISSUER_RE.search(t.description)
            and t.category not in NON_SPENDING | {"Loans & Debt", "Housing", "Insurance"}):
        return "Possible card payment counted as spending", "Transfers & Payments"
    if t.category_source == "none" or t.category == "Other":
        return "No category", t.category
    if t.category_source == "guess":
        n = (t.note or "").lower()
        if "rent" in n:
            return "Looks like rent or a mortgage", t.category
        if "another bank" in n:
            return "Money moved to another bank?", t.category
        return "Guessed from a broad word", t.category
    return None


def needs_review(transactions) -> list[ReviewItem]:
    groups = {}
    for t in transactions:
        if t.excluded or t.duplicate:
            continue
        r = _reason(t)
        if not r:
            continue
        key = (t.merchant, r[0], r[1], t.is_credit)
        if key not in groups:
            groups[key] = ReviewItem(t.merchant, r[0], r[1], t.is_credit)
        groups[key].txs.append(t)
    order = {"Possible card payment counted as spending": 0, "Money moved to another bank?": 1,
             "Looks like rent or a mortgage": 2}
    return sorted(groups.values(), key=lambda g: (order.get(g.reason, 3), -g.total))


# ------------------------------------------------------------------ missing statements

@dataclass
class Gap:
    account: str
    start: date             # first day with no statement
    end: date               # last day with no statement
    months: int             # roughly how many monthly statements are missing
    before: str             # file before the gap
    after: str              # file after the gap


def _account_of(r) -> str:
    i = r.info
    if i.account_key:
        return i.account_key
    kind = {"card": "card", "bank": "account"}.get(i.kind, "statements")
    return f"{r.group or 'Folder'} {kind}".strip()


def missing_statements(file_results) -> list[Gap]:
    """Gaps between consecutive statements of the same account. When a statement has only a closing date,
    monthly closings more than ~40 days apart mean a statement is missing."""
    by_acct = defaultdict(list)
    for r in file_results:
        if r.status != "ok" or not r.transactions:
            continue
        ds = [t.date for t in r.transactions]
        start = r.info.period_start
        end = r.info.period_end or max(ds)
        loose = r.method in ("csv",)   # a CSV's period is just its first and last transaction
        by_acct[_account_of(r)].append((start, end, loose, os.path.basename(r.path)))
    gaps = []
    for acct, periods in by_acct.items():
        periods.sort(key=lambda p: p[1])
        for (s1, e1, l1, f1), (s2, e2, l2, f2) in zip(periods, periods[1:]):
            if s2:
                slack = 12 if (l1 or l2) else 4
                if (s2 - e1).days > slack:
                    gs, ge = e1 + timedelta(days=1), s2 - timedelta(days=1)
                    gaps.append(Gap(acct, gs, ge, max(1, round(((ge - gs).days + 1) / 30.44)), f1, f2))
            elif (e2 - e1).days > 40:
                n = round((e2 - e1).days / 30.44) - 1
                gs, ge = e1 + timedelta(days=1), e2 - timedelta(days=30)
                gaps.append(Gap(acct, gs, ge, max(1, n), f1, f2))
    return sorted(gaps, key=lambda g: (g.account, g.start))
