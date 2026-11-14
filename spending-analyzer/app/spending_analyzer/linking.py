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


# How each bank appears in other banks' transaction descriptions
BANK_ALIASES = {
    "Chase": r"CHASE|JPMORGAN|JPM CHASE|JP MORGAN",
    "Capital One": r"CAPITAL ONE|CAPITALONE|CAP ONE|CAPONE",
    "Bank of America": r"BANK OF AMERICA|BK OF AMER|BOFA",
    "Wells Fargo": r"WELLS FARGO",
    "Citi": r"\bCITI\b|CITIBANK",
    "Ally": r"\bALLY\b",
    "Discover": r"DISCOVER BANK|DISCOVER SAV|\bDISCOVER\b",
    "American Express": r"AMEX|AMERICAN EXPRESS",
    "U.S. Bank": r"U\.?S\.? BANK",
    "PNC": r"\bPNC\b", "TD Bank": r"\bTD BANK\b", "USAA": r"\bUSAA\b", "Navy Federal": r"NAVY FED",
    "SoFi": r"\bSOFI\b", "Chime": r"\bCHIME\b", "Schwab": r"SCHWAB", "Fidelity": r"FIDELITY",
    "Marcus": r"MARCUS|GOLDMAN SACHS|GS BANK", "Varo": r"\bVARO\b", "Truist": r"TRUIST",
    "Citizens": r"CITIZENS", "Synchrony": r"SYNCHRONY|SYNCB", "Barclays": r"BARCLAY",
}
ANY_BANK = re.compile("|".join(f"(?:{v})" for v in BANK_ALIASES.values()), re.I)
# Payments to a bank that ARE spending: loans, insurance, fees, cash
REAL_SPENDING = re.compile(r"AUTO|CARPAY|CAR PAY|LOAN|MORTGAGE|\bMTG\b|LEASE|INSUR|\bINS\b|\bATM\b|\bFEE\b|"
                           r"INTEREST|FINANCE CHG|OVERDRAFT|PAYROLL|DIR DEP|DIRECT DEP|SALARY|ZELLE|VENMO", re.I)
SAVINGS_HINT = re.compile(r"SAVINGS|\bSAV\b|\b360\b|MONEY MARKET|\bMMA\b|HIGH YIELD|HYSA|BROKERAGE|INVEST", re.I)


def bank_of(account: str) -> str:
    return next((b for b in BANK_ALIASES if account.startswith(b + " ")), "")


def classify_bank_moves(results) -> int:
    """Money moving between a bank account and another bank is your own money moving, not spending or income
    (savings at Capital One, paying a card, moving money back). Loans, insurance, fees and cash are excluded."""
    n = 0
    for r in results:
        if r.info.kind == "card":
            continue
        own = bank_of(r.info.account_key) or r.info.bank
        for t in r.transactions:
            if t.category_source in ("learned", "merchant", "matched"):
                continue
            if t.category_source == "keyword" and t.category not in ("Transfers & Payments", "Income", "Other"):
                continue
            d = t.description
            # "Online Transfer to Sav ...5678" out of checking: that's saving, even without the savings statement
            if (not t.is_credit and t.category == "Transfers & Payments" and r.info.account_type != "savings"
                    and SAVINGS_HINT.search(d) and not t.transfer_match):
                t.category = "Savings & Investments"
                continue
            m = ANY_BANK.search(d)
            if not m or REAL_SPENDING.search(d):
                continue
            # a deposit at Chase that just says "Chase" isn't a transfer from another bank
            if own and re.search(BANK_ALIASES.get(own, "^$"), m.group(0), re.I) and not SAVINGS_HINT.search(d):
                continue
            if not t.is_credit and SAVINGS_HINT.search(d) and r.info.account_type != "savings":
                t.category = "Savings & Investments"
            else:
                t.category = "Transfers & Payments"
            t.category_source = "guess"
            t.note = ("Moved to " if not t.is_credit else "Moved from ") + "another bank - not counted"
            n += 1
    return n


def _same_account(a, b) -> bool:
    """Same account across formats: a PDF statement says "Chase card ...1234", its CSV download may only say
    "...1234". Last 4 digits decide when both have them; otherwise the same folder and the same kind."""
    ia, ib = a.info, b.info
    if ia.last4 and ib.last4:
        if ia.last4 != ib.last4:
            return False
        if "unknown" not in (ia.kind, ib.kind) and ia.kind != ib.kind:
            return False
        return not (ia.bank and ib.bank and ia.bank != ib.bank)
    if a.group != b.group:
        return False
    return ia.kind == ib.kind and ia.kind != "unknown" or (ia.kind == "unknown") != (ib.kind == "unknown")


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


def _mark_dup(t, orig, a, b, used):
    used.add(id(orig))
    t.duplicate = True
    t.note = "Also in " + os.path.basename(a.path) + " (counted once)"
    b.duplicates_removed += 1


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
            pool = [t for t in a.transactions if not t.duplicate]
            used = set()
            exact = defaultdict(list)
            for t in pool:
                exact[(t.date, t.amount, t.is_credit)].append(t)
            later = []
            for t in b.transactions:
                if t.duplicate or t.not_duplicate:
                    continue
                cands = [c for c in exact.get((t.date, t.amount, t.is_credit), []) if id(c) not in used]
                if cands:
                    _mark_dup(t, cands[0], a, b, used)
                    removed += 1
                else:
                    later.append(t)
            # A CSV may use the posting date where the statement uses the transaction date:
            # same amount and direction, same company, within 3 days.
            for t in later:
                cands = [c for c in pool if id(c) not in used and c.amount == t.amount and c.is_credit == t.is_credit
                         and abs((c.date - t.date).days) <= 3 and c.merchant and c.merchant == t.merchant]
                if cands:
                    _mark_dup(t, min(cands, key=lambda c: abs((c.date - t.date).days)), a, b, used)
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
            else:   # bank to bank, never money from a person
                names_other = False
                bo, bi = bank_of(o.account), bank_of(i.account)
                if bi and re.search(BANK_ALIASES[bi], o.description, re.I):
                    names_other = True   # Chase line says "CAPITAL ONE ...", money arrives at Capital One
                if bo and re.search(BANK_ALIASES[bo], i.description, re.I):
                    names_other = True   # Capital One line says "Deposit from JPMorgan Chase"
                both_words = bool(TRANSFER_WORDS.search(o.description) and TRANSFER_WORDS.search(i.description))
                ok = (names_other or both_words) and not P2P_WORDS.search(i.description)
            if ok and (best is None or abs(gap) < best_gap):
                best, best_gap = i, abs(gap)
        if best is not None:
            used.add(id(best))
            where = best.account or os.path.basename(os.path.dirname(best.source_file)) or "another account"
            # Money is "saved" once: moving it on from one savings account to another isn't saving it again
            saved = o.account_type != "savings" and (o.category == "Savings & Investments" or (
                best.kind != "card" and (best.account_type == "savings"
                                         or SAVINGS_HINT.search(best.description + " " + o.description))))
            o.category = "Savings & Investments" if saved else "Transfers & Payments"
            o.category_source, o.transfer_match = "matched", True
            o.note = ("Paid to card " if best.kind == "card" else "Moved to ") + where + f" on {best.date}"
            best.category, best.category_source, best.transfer_match = "Transfers & Payments", "matched", True
            best.note = "Received from " + (o.account or "your bank account") + f" on {o.date}"
            matched += 1
    return matched


def link(results) -> dict:
    return {"duplicates": remove_overlap_duplicates(results), "transfers": match_transfers(results),
            "bank_moves": classify_bank_moves(results)}
