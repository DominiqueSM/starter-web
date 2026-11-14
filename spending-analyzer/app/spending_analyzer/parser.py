"""Statement parsing: transactions, statement facts, and self-checks.

Pipeline for one PDF:
  1. Identify the statement: credit card or bank account, which bank, account last 4 digits,
     statement period, opening/closing balance, and date order (MM/DD vs DD/MM).
  2. Walk the lines. Table headers ("Date  Description  Debit  Credit  Balance") define column
     positions; section titles ("Payments and Credits", "Withdrawals") give direction; rows that start
     with a date become transactions; indented lines right after a row extend its description.
  3. Decide money in vs. out for each row from the strongest evidence available:
     column > running balance > section > sign convention > keywords.
  4. Reconcile: opening balance +/- parsed transactions must equal the closing balance.
Every line gets a diagnostic status so the app can show exactly what was read and what was skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .pdftext import Line

PARSER_VERSION = 4

# ---------------------------------------------------------------- data classes


@dataclass
class Transaction:
    date: date
    description: str
    amount: float          # always positive
    is_credit: bool        # True = money in (refund, payment received, deposit)
    source_file: str
    category: str = "Other"
    merchant: str = ""
    excluded: bool = False
    year_guessed: bool = False
    uid: str = ""
    group: str = ""          # top-level subfolder the PDF came from
    account: str = ""        # e.g. "Chase card ...1234"
    kind: str = ""           # "card" | "bank" | "unknown"
    evidence: str = ""       # how money in/out was decided
    balance: float | None = None
    page: int = 0
    note: str = ""           # e.g. "Matched card payment", "Duplicate of ..."
    category_source: str = ""  # learned | merchant | keyword | guess | none
    duplicate: bool = False
    transfer_match: bool = False
    parsed_credit: bool | None = None   # direction as read from the PDF (before user corrections)

    @property
    def is_spending(self) -> bool:
        return not self.is_credit and not self.excluded and not self.duplicate


@dataclass
class StatementInfo:
    kind: str = "unknown"
    bank: str = ""
    last4: str = ""
    period_start: date | None = None
    period_end: date | None = None
    opening_balance: float | None = None
    closing_balance: float | None = None
    date_order: str = "MDY"
    recon_status: str = "unverified"   # reconciled | balance-verified | mismatch | unverified
    recon_detail: str = ""
    balance_checks: int = 0
    balance_fails: int = 0

    @property
    def account_key(self) -> str:
        if not self.last4:
            return ""
        kind = "card" if self.kind == "card" else "account"
        return (f"{self.bank} {kind} \u2026{self.last4}" if self.bank else f"{kind.title()} \u2026{self.last4}")


@dataclass
class LineDiag:
    page: int
    text: str
    status: str      # transaction | continuation | header | section | summary | skipped | info
    reason: str = ""


# ---------------------------------------------------------------- patterns

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
          "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
MON_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"

DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})(?![\d.])"), "nny"),   # 01/31/2024, 31.01.24
    (re.compile(r"(\d{1,2})[/\-](\d{1,2})(?![/\-.]?\d)"), "nn"),                   # 01/31 (no year)
    (re.compile(r"(" + MON_RE + r")\s+(\d{1,2})(?:,?\s+(\d{4}))?\b", re.I), "mdy_name"),
    (re.compile(r"(\d{1,2})[\s\-](" + MON_RE + r")(?:[,\s\-]+(\d{2,4}))?\b", re.I), "dmy_name"),
]
ANY_DATE_RE = re.compile(
    r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|" + MON_RE + r"\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+"
    + MON_RE + r",?\s+\d{4}", re.I)

AMOUNT_TOKEN = re.compile(r"^\(?[-+]?\$?[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?-?$")
AMOUNT_IN_TEXT = re.compile(
    r"(?<![\w.,/])(\(?[-+]?\$?\s?[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?-?)(\s?(?:CR|DR)\b)?(?![\w.,/%])", re.I)

SKIP_DESC_RE = re.compile(
    r"\b(beginning|ending|opening|closing|previous|new|daily|average|available|statement|starting|current)"
    r"\s+(ledger\s+)?balance\b|balance\s+(forward|brought|carried|last statement|this statement)|^total\b|\btotals?\s*:|"
    r"\bsubtotal\b|minimum payment|payment due|credit limit|credit line|cash access|^page \d|year[- ]to[- ]date"
    r"|\bytd\b|annual percentage|^balance\b",
    re.I)

OPENING_RE = re.compile(r"\b(beginning|opening|previous|starting)\s+(ledger\s+)?balance\b|balance\s+(forward|last statement)", re.I)
CLOSING_RE = re.compile(r"\b(ending|closing|new)\s+(ledger\s+)?balance\b|balance\s+this statement", re.I)

SECTION_IN = re.compile(
    r"^(deposits?( and (other )?(additions|credits))?|credits?|(other )?credits|payments?(,| and| &)? (other )?credits?"
    r"|electronic deposits|additions|money in|paid in|refunds?( and credits)?|payments)\b", re.I)
SECTION_OUT = re.compile(
    r"^(withdrawals?( and (other )?(subtractions|debits))?|debits?|purchases?|(atm|card)( &| and)? debit card withdrawals"
    r"|atm & debit|checks?( paid)?|electronic withdrawals|other (debits|withdrawals|subtractions)|fees( charged)?"
    r"|interest charged?|cash advances?|money out|paid out|card purchases|purchases and adjustments|service fees?"
    r"|subtractions|transactions)\b", re.I)
SECTION_IGNORE = re.compile(r"^(daily (ending )?balances?|daily ledger|balance summary|interest charge calculation"
                            r"|year[- ]to[- ]date|totals for|checks? (paid )?summary)", re.I)

CREDIT_KEYWORDS = re.compile(
    r"\b(payroll|direct dep|dir dep|deposit|salary|refund|return|reversal|cash ?back|interest paid|interest earned"
    r"|payment[\s,-]*thank|thank you for your payment|payment received|credit adjustment|statement credit"
    r"|zelle (payment )?from|transfer from|venmo cashout|tax refund|dividend|rebate|reimbursement|ach credit|ach cr"
    r"|direct credit|mobile deposit|remote deposit|edeposit|paycheck|wages|treas 310|ssa treas)\b", re.I)

CARD_WORDS = ["credit limit", "minimum payment", "payment due date", "new balance", "available credit",
              "cash advance", "annual percentage rate", "credit card", "cardmember", "card member", "purchases",
              "previous balance", "late payment warning", "rewards"]
BANK_WORDS = ["checking", "savings", "deposits", "withdrawals", "beginning balance", "ending balance",
              "daily balance", "checks paid", "direct deposit", "available balance", "money market",
              "deposits and additions", "overdraft"]

BANKS = [
    ("Chase", r"\bCHASE\b|JPMORGAN", ""), ("Bank of America", r"BANK OF AMERICA", ""),
    ("Wells Fargo", r"WELLS FARGO", ""), ("Citi", r"\bCITI(BANK|CARDS?|GROUP)?\b", ""),
    ("Capital One", r"CAPITAL ONE", ""), ("American Express", r"AMERICAN EXPRESS|\bAMEX\b", "card"),
    ("Discover", r"\bDISCOVER\b", "card"), ("U.S. Bank", r"U\.S\. BANK|\bUS BANK\b", ""),
    ("PNC", r"\bPNC\b", ""), ("TD Bank", r"\bTD BANK\b", ""), ("USAA", r"\bUSAA\b", ""),
    ("Navy Federal", r"NAVY FEDERAL", ""), ("Ally", r"\bALLY BANK\b", "bank"), ("Apple Card", r"APPLE CARD", "card"),
    ("Synchrony", r"SYNCHRONY", "card"), ("Barclays", r"BARCLAY", "card"), ("Truist", r"TRUIST", ""),
    ("Citizens", r"CITIZENS BANK", ""), ("Fifth Third", r"FIFTH THIRD", ""), ("Regions", r"REGIONS BANK", ""),
    ("Huntington", r"HUNTINGTON", ""), ("SoFi", r"\bSOFI\b", ""), ("Chime", r"\bCHIME\b", "bank"),
    ("Schwab", r"SCHWAB", ""), ("Fidelity", r"FIDELITY", ""), ("Varo", r"\bVARO\b", "bank"),
]

LAST4_RES = [
    re.compile(r"(?:account|acct|card)\s*(?:number|no\.?|#)?\s*(?:ending|ends)\s*(?:in|with)?\s*[:#]?\s*(\d{4})\b", re.I),
    re.compile(r"\bending\s+in\s+(\d{4})\b", re.I),
    re.compile(r"(?:account|acct|card)\s*(?:number|no\.?|#)\s*:?\s*[X*•x\-\s\d]*?(\d{4})\b", re.I),
    re.compile(r"[X*•]{4}[\s\-]?[X*•]{4}[\s\-]?[X*•]{4}[\s\-]?(\d{4})\b"),
]

PERIOD_RANGE_RE = re.compile(
    r"(?:statement period|period|statement dates?|opening/closing date|billing (?:period|cycle)|for the period"
    r"|period covered|statement from)?\s*:?\s*(?:from\s+)?(?P<a>" + ANY_DATE_RE.pattern + r")\s*(?:-|–|—|to|through|thru)\s*"
    r"(?P<b>" + ANY_DATE_RE.pattern + r")", re.I)
CLOSING_DATE_RE = re.compile(
    r"(?:closing date|statement (?:closing )?date|period ending|ending date|statement ending|as of)\s*:?\s*(?P<a>"
    + ANY_DATE_RE.pattern + r")", re.I)

HEADER_ROLES = [
    ("date", re.compile(r"^(trans(action)?\.?|post(ing|ed)?|tran|date|value)$", re.I)),
    ("desc", re.compile(r"^(description|details|merchant|payee|transactions?|narrative|particulars|memo)$", re.I)),
    ("debit", re.compile(r"^(debits?|withdrawals?|charges?|subtractions|out|payments?\(?-?\)?)$", re.I)),
    ("credit", re.compile(r"^(credits?|deposits?|additions|in|receipts)$", re.I)),
    ("amount", re.compile(r"^(amount|\$?amount\(?\$?\)?|\$)$", re.I)),
    ("balance", re.compile(r"^(balance|bal\.?)$", re.I)),
]

# ---------------------------------------------------------------- helpers


def _year(y: str | None) -> int | None:
    if not y:
        return None
    v = int(y)
    if v < 100:
        v += 2000
    return v if 1990 <= v <= 2100 else None


def match_date_at(text: str, pos: int, order: str = "MDY"):
    """Match a date starting exactly at pos. Returns (month, day, year|None, end) or None."""
    for rx, kind in DATE_PATTERNS:
        m = rx.match(text, pos)
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind in ("nny", "nn"):
                a, b = int(m.group(1)), int(m.group(2))
                y = _year(m.group(3)) if kind == "nny" else None
                if kind == "nny" and y is None:
                    continue
                if kind == "nn" and "." in m.group(0):
                    continue
                mo, d = (b, a) if order == "DMY" else (a, b)
                if mo > 12 and d <= 12:
                    mo, d = d, mo
            elif kind == "mdy_name":
                mo, d, y = MONTHS[m.group(1).lower()[:3]], int(m.group(2)), _year(m.group(3))
            else:
                mo, d, y = MONTHS[m.group(2).lower()[:3]], int(m.group(1)), _year(m.group(3))
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            if y:
                date(y, mo, d)
            return mo, d, y, m.end()
        except (KeyError, ValueError):
            continue
    return None


def parse_full_date(s: str, order: str) -> date | None:
    r = match_date_at(s.strip(), 0, order)
    if r and r[2]:
        try:
            return date(r[2], r[0], r[1])
        except ValueError:
            return None
    return None


def parse_amount(raw: str, suffix: str | None = None) -> tuple[float, bool, bool]:
    """Return (absolute value, is_negative, had_explicit_sign)."""
    s = raw.replace("$", "").replace(",", "").replace(" ", "").replace("+", "")
    neg = "(" in s or ")" in s or s.startswith("-") or s.endswith("-")
    explicit = neg or raw.strip().startswith("+")
    if suffix:
        sx = suffix.strip().upper()
        if sx == "CR":
            neg, explicit = True, True
        elif sx == "DR":
            explicit = True
    return float(s.strip("()-")), neg, explicit


def detect_date_order(text: str, preference: str) -> str:
    if preference in ("MDY", "DMY"):
        return preference
    mdy = dmy = 0
    for m in re.finditer(r"(?<![\d.])(\d{1,2})[/\-.](\d{1,2})(?:[/\-.]\d{2,4})?(?![\d])", text):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            dmy += 1
        elif b > 12 and a <= 12:
            mdy += 1
    return "DMY" if dmy > mdy else "MDY"


def _find_labeled_amount(lines_text: list[str], label_re: re.Pattern) -> float | None:
    for t in lines_text:
        m = label_re.search(t)
        if not m:
            continue
        rest = t[m.end():m.end() + 60]
        a = AMOUNT_IN_TEXT.search(rest)
        if a:
            v, neg, _ = parse_amount(a.group(1), a.group(2))
            return -v if neg else v
    return None


def _statement_info(lines: list[Line], order_pref: str) -> StatementInfo:
    texts = [l.text for l in lines]
    full = "\n".join(texts)
    low = full.lower()
    info = StatementInfo()
    info.date_order = detect_date_order(full, order_pref)

    # Header area: early lines that are not transaction rows (so a "Payment to Chase card" row
    # in another bank's statement doesn't make it a Chase statement)
    head = "\n".join(t for t in texts[:25] if not match_date_at(t.strip(), 0, info.date_order)).upper()
    for name, rx, hint in BANKS:
        if re.search(rx, head):
            info.bank = name
            break
    card = sum(low.count(w) > 0 for w in CARD_WORDS)
    bank = sum(low.count(w) > 0 for w in BANK_WORDS)
    hint = next((h for n, _, h in BANKS if n == info.bank), "")
    if re.search(r"credit card|card ?member|visa|mastercard", head, re.I):
        card += 2
    if re.search(r"checking|savings|money market", head, re.I):
        bank += 2
    if hint == "card":
        card += 1
    elif hint == "bank":
        bank += 1
    info.kind = "card" if card > bank else ("bank" if bank > card else "unknown")

    for t in texts[:80]:
        for rx in LAST4_RES:
            m = rx.search(t)
            if m:
                info.last4 = m.group(1)
                break
        if info.last4:
            break

    # Statement period: labelled range first, then a labelled closing date
    for t in texts[:120]:
        m = PERIOD_RANGE_RE.search(t)
        if m:
            a, b = parse_full_date(m.group("a"), info.date_order), parse_full_date(m.group("b"), info.date_order)
            if a and b and a <= b and (b - a).days <= 400:
                info.period_start, info.period_end = a, b
                break
    if not info.period_end:
        for t in texts[:120]:
            m = CLOSING_DATE_RE.search(t)
            if m:
                d = parse_full_date(m.group("a"), info.date_order)
                if d:
                    info.period_end = d
                    break
    if not info.period_end:   # fall back: a high percentile of all full dates in the document
        found = sorted(d for d in (parse_full_date(m.group(0), info.date_order) for m in ANY_DATE_RE.finditer(full))
                       if d and date(1995, 1, 1) <= d <= date.today() + timedelta(days=60))
        if found:
            info.period_end = found[min(len(found) - 1, int(len(found) * 0.9))]

    info.opening_balance = _find_labeled_amount(texts, OPENING_RE)
    info.closing_balance = _find_labeled_amount(texts, CLOSING_RE)
    return info


@dataclass
class _Col:
    role: str
    x0: float
    x1: float

    @property
    def center(self):
        return (self.x0 + self.x1) / 2


def _detect_header(line: Line) -> list[_Col] | None:
    if not line.has_positions or len(line.words) < 2:
        return None
    cols = []
    for w in line.words:
        word = w.text.strip(":")
        for role, rx in HEADER_ROLES:
            if rx.match(word):
                if cols and cols[-1].role == role and w.x0 - cols[-1].x1 < 15:
                    cols[-1].x1 = w.x1   # "Trans Date", "Posting Date"
                elif role == "date" and cols and cols[-1].role == "date" and word.lower() == "date":
                    cols[-1].x1 = w.x1
                else:
                    cols.append(_Col(role, w.x0, w.x1))
                break
        else:
            if word.lower() == "date" and cols and cols[-1].role == "date":
                cols[-1].x1 = w.x1
    roles = {c.role for c in cols}
    numeric = roles & {"debit", "credit", "amount", "balance"}
    if numeric and (("desc" in roles) or ("date" in roles)) and len(cols) >= 2 and len(line.words) <= 14:
        # "Amount" alone after a long sentence is not a header
        if len(numeric) == 1 and "desc" not in roles and len(line.words) > 6:
            return None
        return cols
    return None


def _assign_column(cols: list[_Col], x0: float, x1: float) -> str | None:
    numeric = [c for c in cols if c.role in ("debit", "credit", "amount", "balance")]
    if not numeric:
        return None
    center = (x0 + x1) / 2

    def dist(c):
        return min(abs(x1 - c.x1), abs(center - c.center))
    best = min(numeric, key=dist)
    return best.role


def _section_of(text: str):
    t = re.sub(r"\(continued\)|continued|\s{2,}", " ", text, flags=re.I).strip(" :-")
    if len(t) > 60 or AMOUNT_IN_TEXT.search(t) or match_date_at(t, 0):
        return None
    if SECTION_IGNORE.match(t):
        return "ignore"
    if SECTION_IN.match(t):
        return "in"
    if SECTION_OUT.match(t):
        return "out"
    return None


def _words_and_amounts(line: Line):
    """Split a line into word list with positions, and the trailing amount tokens."""
    if line.has_positions:
        words = [(w.text, w.x0, w.x1) for w in line.words]
    else:
        words = [(t, None, None) for t in line.raw.split()]
    return words


def _join(words, a, b):
    return " ".join(w[0] for w in words[a:b])


# ---------------------------------------------------------------- main entry

def parse_statement(lines: list[Line], source_file: str, fallback_year: int, order_pref: str = "auto"):
    info = _statement_info(lines, order_pref)
    order = info.date_order
    diags: list[LineDiag] = []
    rows = []         # dicts, in statement order
    cols: list[_Col] | None = None
    section = None
    last_row = None
    last_line = None
    cont_count = 0

    for li, line in enumerate(lines):
        text = line.text.strip()
        if not text:
            continue
        hdr = _detect_header(line)
        if hdr:
            cols = hdr
            diags.append(LineDiag(line.page, text, "header", "column headings: " + ", ".join(c.role for c in hdr)))
            last_row = None
            continue
        sec = _section_of(text)
        if sec:
            section = sec
            diags.append(LineDiag(line.page, text, "section", {"in": "money in section", "out": "money out section",
                                                                 "ignore": "summary table (ignored)"}[sec]))
            last_row = None
            continue

        words = _words_and_amounts(line)
        joined = " ".join(w[0] for w in words)
        d1 = match_date_at(joined, 0, order)
        if not d1:
            # Continuation of the previous row's description?
            if (last_row is not None and line.has_positions and last_line is not None and cont_count < 2
                    and line.page == last_line.page and 0 < last_line.y - line.y < line.size * 2.6
                    and not AMOUNT_IN_TEXT.search(text) and re.search(r"[A-Za-z]{2,}", text)
                    and not SKIP_DESC_RE.search(text) and len(text) < 90
                    and line.words[0].x0 >= last_row["desc_x0"] - 2):
                last_row["desc"] += " " + re.sub(r"\s+", " ", text)
                cont_count += 1
                last_line = line
                diags.append(LineDiag(line.page, text, "continuation", "added to the description above"))
                continue
            if OPENING_RE.search(text) or CLOSING_RE.search(text) or SKIP_DESC_RE.search(text):
                diags.append(LineDiag(line.page, text, "summary"))
            else:
                diags.append(LineDiag(line.page, text, "info"))
            last_row = None
            continue

        mo, dd, yy, end = d1
        # map character offset back to word index
        pos, wi = 0, 0
        while wi < len(words) and pos < end:
            pos += len(words[wi][0]) + 1
            wi += 1
        rest_text = _join(words, wi, len(words))
        d2 = match_date_at(rest_text, 0, order)
        if d2:
            p2, wj = 0, wi
            while wj < len(words) and p2 < d2[3]:
                p2 += len(words[wj][0]) + 1
                wj += 1
            wi = wj

        # trailing amount tokens (scan from the right)
        amts = []
        j = len(words) - 1
        while j >= wi:
            tok = words[j][0]
            if tok.upper() in ("CR", "DR") and j - 1 >= wi and AMOUNT_TOKEN.match(words[j - 1][0]):
                v, neg, exp = parse_amount(words[j - 1][0], tok)
                amts.insert(0, (v, neg, exp, words[j - 1][1], words[j][2]))
                j -= 2
                continue
            if AMOUNT_TOKEN.match(tok):
                v, neg, exp = parse_amount(tok)
                x0 = words[j][1]
                if j - 1 >= wi and words[j - 1][0] in ("$", "-", "-$", "+", "$-"):
                    neg = neg or "-" in words[j - 1][0]
                    exp = exp or words[j - 1][0] in ("-", "-$", "+", "$-")
                    x0 = words[j - 1][1]
                    j -= 1
                amts.insert(0, (v, neg, exp, x0, words[j if words[j][0] not in ("$", "-", "-$", "+", "$-") else j + 1][2]))
                j -= 1
                continue
            if tok in ("$",):
                j -= 1
                continue
            break
        desc_words = words[wi:j + 1]
        if not amts:
            # amount somewhere in the middle (e.g. followed by a reference number)
            m = AMOUNT_IN_TEXT.search(rest_text)
            if m:
                v, neg, exp = parse_amount(m.group(1), m.group(2))
                amts = [(v, neg, exp, None, None)]
                desc_words = [(t, None, None) for t in rest_text[:m.start()].split()]
        desc = re.sub(r"\s+", " ", " ".join(w[0] for w in desc_words)).strip(" -*")

        if section == "ignore":
            diags.append(LineDiag(line.page, text, "skipped", "inside a balance summary table"))
            continue
        if not amts:
            diags.append(LineDiag(line.page, text, "skipped", "starts with a date but has no amount"))
            continue
        if OPENING_RE.search(desc) or CLOSING_RE.search(desc):
            v, neg, _, _, _ = amts[-1]
            val = -v if neg else v
            if OPENING_RE.search(desc) and info.opening_balance is None:
                info.opening_balance = val
            if CLOSING_RE.search(desc) and info.closing_balance is None:
                info.closing_balance = val
            diags.append(LineDiag(line.page, text, "summary", "balance line"))
            continue
        if not re.search(r"[A-Za-z]{2,}", desc):
            diags.append(LineDiag(line.page, text, "skipped", "no description"))
            continue
        if SKIP_DESC_RE.search(desc):
            diags.append(LineDiag(line.page, text, "summary", "total/balance line"))
            continue

        # classify amounts into columns
        amount = balance = None
        col_dir = None
        sign_neg = sign_explicit = False
        if cols and line.has_positions and all(a[3] is not None for a in amts):
            for v, neg, exp, x0, x1 in amts:
                role = _assign_column(cols, x0, x1)
                if role == "balance":
                    balance = -v if neg else v
                elif amount is None:
                    amount, sign_neg, sign_explicit = v, neg, exp
                    if role == "debit":
                        col_dir = "out"
                    elif role == "credit":
                        col_dir = "in"
            if amount is None and balance is not None and len(amts) == 1:
                diags.append(LineDiag(line.page, text, "skipped", "only a balance, no transaction amount"))
                continue
        if amount is None:
            v, neg, exp = amts[0][:3]
            amount, sign_neg, sign_explicit = v, neg, exp
            if len(amts) >= 2:
                bv, bneg = amts[-1][0], amts[-1][1]
                balance = -bv if bneg else bv
        if amount == 0 or amount > 5_000_000:
            diags.append(LineDiag(line.page, text, "skipped", "amount is zero or implausible"))
            continue
        row = dict(mo=mo, d=dd, y=yy, desc=desc, amount=round(amount, 2), neg=sign_neg, explicit=sign_explicit,
                   col_dir=col_dir, balance=balance, section=section if section in ("in", "out") else None,
                   page=line.page, diag=len(diags),
                   desc_x0=(desc_words[0][1] if desc_words and desc_words[0][1] is not None else 0))
        rows.append(row)
        diags.append(LineDiag(line.page, text, "transaction", ""))
        last_row, last_line, cont_count = row, line, 0

    txs = _resolve(rows, info, source_file, fallback_year, diags)
    return txs, info, diags


def _resolve(rows, info: StatementInfo, source_file, fallback_year, diags):
    if not rows:
        return []
    kind = info.kind
    # Sign convention for rows without stronger evidence
    signed = [r for r in rows if r["explicit"] and not r["col_dir"] and not r["section"]]
    neg_share = (sum(r["neg"] for r in signed) / len(signed)) if signed else 0
    if kind == "card":
        neg_means_in = True
    elif kind == "bank":
        neg_means_in = False if signed else True
    else:
        neg_means_in = neg_share <= 0.5

    # Running balance: decide direction where the balance moves by exactly the amount
    prev = info.opening_balance
    for r in rows:
        r["dir"], r["ev"] = None, None
        if r["col_dir"]:
            r["dir"], r["ev"] = r["col_dir"], "column"
        if r["balance"] is not None and prev is not None:
            up = abs(prev + r["amount"] - r["balance"]) < 0.011
            down = abs(prev - r["amount"] - r["balance"]) < 0.011
            if up != down:
                bal_dir = ("out" if up else "in") if kind == "card" else ("in" if up else "out")
                info.balance_checks += 1
                if r["dir"] and r["dir"] != bal_dir:
                    info.balance_fails += 1
                if not r["dir"]:
                    r["dir"], r["ev"] = bal_dir, "balance"
            else:
                info.balance_fails += 1
        if not r["dir"] and r["section"]:
            r["dir"], r["ev"] = r["section"], "section"
        if not r["dir"] and r["explicit"]:
            r["dir"] = ("in" if r["neg"] else "out") if neg_means_in else ("out" if r["neg"] else "in")
            r["ev"] = "sign"
        if not r["dir"]:
            if kind == "card":
                r["dir"], r["ev"] = "out", "sign"      # unsigned card rows are charges
            else:
                r["dir"], r["ev"] = ("in" if CREDIT_KEYWORDS.search(r["desc"]) else "out"), "keyword"
        if r["ev"] in ("sign", "keyword") and CREDIT_KEYWORDS.search(r["desc"]):
            r["dir"] = "in"
        if r["balance"] is not None:
            prev = r["balance"]
        elif prev is not None and r["dir"]:
            prev = prev + (r["amount"] if (r["dir"] == "in") != (kind == "card") else -r["amount"])

    _reconcile(rows, info)

    # Dates and years
    end, start = info.period_end, info.period_start
    txs = []
    for r in rows:
        guessed = False
        y = r["y"]
        if y is None:
            if end:
                y = end.year
                cand = []
                for yy in (end.year, end.year - 1, end.year + 1):
                    try:
                        cand.append(date(yy, r["mo"], r["d"]))
                    except ValueError:
                        pass
                lo = (start or end - timedelta(days=45)) - timedelta(days=10)
                hi = end + timedelta(days=10)
                inside = [c for c in cand if lo <= c <= hi]
                pick = inside[0] if inside else min(cand, key=lambda c: abs((c - end).days), default=None)
                if pick is None:
                    continue
                y = pick.year
            else:
                y, guessed = fallback_year, True
        try:
            dt = date(y, r["mo"], r["d"])
        except ValueError:
            continue
        diags[r["diag"]].reason = f"{'money in' if r['dir'] == 'in' else 'money out'} ({r['ev']})"
        txs.append(Transaction(
            date=dt, description=r["desc"], amount=r["amount"], is_credit=(r["dir"] == "in"),
            source_file=source_file, year_guessed=guessed, account=info.account_key, kind=info.kind,
            evidence=r["ev"], balance=r["balance"], page=r["page"]))
    return txs


def _net(rows, kind):
    s = 0.0
    for r in rows:
        signed = r["amount"] if r["dir"] == "in" else -r["amount"]
        s += -signed if kind == "card" else signed
    return round(s, 2)


def _flip_subset(rows, weak, ob, cb, kinds, max_rows=3):
    """Find up to max_rows weakly-decided rows whose direction, flipped, makes the statement add up."""
    from itertools import combinations
    cand = weak[:60]
    for k in kinds:
        diff = round(cb - ob - _net(rows, k), 2)
        for n in range(1, max_rows + 1):
            if n == 3 and len(cand) > 40:
                break
            for combo in combinations(cand, n):
                # flipping a row changes the net by 2*amount, sign depends on its current direction
                delta = 0.0
                for r in combo:
                    signed = r["amount"] if r["dir"] == "in" else -r["amount"]
                    delta += -2 * (-signed if k == "card" else signed)
                if abs(round(delta - diff, 2)) < 0.015:
                    for r in combo:
                        r["dir"] = "in" if r["dir"] == "out" else "out"
                        r["ev"] = "reconciled"
                    return k, list(combo)
    return None


def _reconcile(rows, info: StatementInfo):
    """Check opening +/- transactions == closing. Try flipping weak (sign-based) evidence if it doesn't match."""
    ob, cb = info.opening_balance, info.closing_balance
    if ob is not None and cb is not None:
        kinds = [info.kind] if info.kind != "unknown" else ["bank", "card"]
        for k in kinds:
            diff = round(cb - ob - _net(rows, k), 2)
            if abs(diff) < 0.015:
                info.kind = k
                info.recon_status, info.recon_detail = "reconciled", "Transactions add up to the statement balances."
                return
        # Weak evidence may be backwards: try inverting sign-decided rows
        weak = [r for r in rows if r["ev"] in ("sign", "keyword")]
        if weak:
            for r in weak:
                r["dir"] = "in" if r["dir"] == "out" else "out"
            for k in kinds:
                if abs(round(cb - ob - _net(rows, k), 2)) < 0.015:
                    info.kind = k
                    info.recon_status = "reconciled"
                    info.recon_detail = "Reconciled after correcting the +/- convention for this statement."
                    return
            for r in weak:
                r["dir"] = "in" if r["dir"] == "out" else "out"
            # Or just a few rows read backwards: each one is off by twice its amount
            fixed = _flip_subset(rows, weak, ob, cb, kinds)
            if fixed:
                info.kind = fixed[0]
                info.recon_status = "reconciled"
                info.recon_detail = (f"Reconciled after correcting money in/out on {len(fixed[1])} row(s): "
                                     + "; ".join(f"{r['desc'][:30]} {r['amount']:,.2f}" for r in fixed[1]))
                return
        k = kinds[0]
        diff = round(cb - ob - _net(rows, k), 2)
        info.recon_status = "mismatch"
        info.recon_detail = (f"Off by {abs(diff):,.2f}: opening {ob:,.2f}, closing {cb:,.2f}. "
                             "Some transactions may be missing or misread; check this file's line preview.")
        return
    if info.balance_checks >= 3 and info.balance_fails <= info.balance_checks * 0.1:
        info.recon_status = "balance-verified"
        info.recon_detail = f"{info.balance_checks} rows checked against the running balance."
        return
    info.recon_status = "unverified"
    info.recon_detail = "No opening/closing balance found to check against."
