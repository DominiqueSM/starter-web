"""Cross-statement checks that stop money being counted twice.

1. Overlapping statements of the same account (e.g. a monthly statement plus a custom date-range
   download): a transaction that appears in both is kept once.
2. Card payments: paying a credit card from checking is not spending - the purchases on the card are.
   A checking withdrawal that matches a payment received on a card statement (same amount, within a
   few days) is marked as a transfer. Moves between your own bank accounts are matched the same way.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

# Words that mark a move between your own accounts. Zelle/Venmo are deliberately not here: money from a
# person (e.g. a partner's share of the bills) must not be mistaken for your own transfer.
TRANSFER_WORDS = re.compile(r"TRANSFER|XFER|TFR|SAVINGS|CHECKING|\bSAV\b|\bCHK\b|\bSHARE\b", re.I)
P2P_WORDS = re.compile(r"ZELLE|VENMO|CASH ?APP", re.I)


def _same_account(a, b) -> bool:
    ka, kb = a.info.account_key, b.info.account_key
    if ka and kb:
        return ka == kb
    return a.group == b.group and a.info.kind == b.info.kind and a.info.kind != "unknown"


def _span(fr):
    ds = [t.date for t in fr.transactions]
    if not ds:
        return None
    lo, hi = min(ds), max(ds)
    if fr.info.period_start:
        lo = min(lo, fr.info.period_start)
    if fr.info.period_end:
        hi = max(hi, fr.info.period_end)
    return lo, hi


def remove_overlap_duplicates(results) -> int:
    files = [r for r in results if r.transactions]
    removed = 0
    for i, a in enumerate(files):
        sa = _span(a)
        for b in files[i + 1:]:
            if not _same_account(a, b):
                continue
            sb = _span(b)
            if not sa or not sb or sb[0] > sa[1] or sa[0] > sb[1]:
                continue   # periods don't overlap
            pool = defaultdict(int)
            for t in a.transactions:
                if not t.duplicate:
                    pool[(t.date, t.amount, t.is_credit)] += 1
            for t in b.transactions:
                k = (t.date, t.amount, t.is_credit)
                if not t.duplicate and pool[k] > 0:
                    pool[k] -= 1
                    t.duplicate = True
                    t.note = "Also in " + os.path.basename(a.path) + " (counted once)"
                    b.duplicates_removed += 1
                    removed += 1
    return removed


def match_transfers(results, window_before=3, window_after=8) -> int:
    """Pair money leaving one account with money arriving in another."""
    txs = [t for r in results for t in r.transactions if not t.duplicate and not t.excluded]
    outs = [t for t in txs if not t.is_credit and t.kind != "card" and t.category_source != "learned"]
    ins = [t for t in txs if t.is_credit and t.category_source != "learned"]
    by_amount = defaultdict(list)
    for t in ins:
        by_amount[t.amount].append(t)
    matched = 0
    used = set()
    for o in sorted(outs, key=lambda t: t.date):
        best, best_gap = None, None
        for i in by_amount.get(o.amount, []):
            if id(i) in used or i.account == o.account and o.account:
                continue
            if i.source_file == o.source_file:
                continue
            gap = (i.date - o.date).days
            if not (-window_before <= gap <= window_after):
                continue
            if i.kind == "card":
                ok = i.category == "Transfers & Payments" or re.search(r"PAYMENT|PMT|THANK", i.description, re.I)
            else:   # bank to bank: needs transfer wording on BOTH sides, and never money from a person
                ok = (bool(TRANSFER_WORDS.search(o.description) and TRANSFER_WORDS.search(i.description))
                      and not P2P_WORDS.search(i.description))
            if ok and (best is None or abs(gap) < best_gap):
                best, best_gap = i, abs(gap)
        if best is not None:
            used.add(id(best))
            where = best.account or os.path.basename(os.path.dirname(best.source_file)) or "another account"
            o.category, o.category_source, o.transfer_match = "Transfers & Payments", "matched", True
            o.note = ("Paid to card " if best.kind == "card" else "Moved to ") + where + f" on {best.date}"
            best.category, best.category_source, best.transfer_match = "Transfers & Payments", "matched", True
            best.note = "Received from " + (o.account or "your bank account") + f" on {o.date}"
            matched += 1
    return matched


def link(results) -> dict:
    return {"duplicates": remove_overlap_duplicates(results), "transfers": match_transfers(results)}
