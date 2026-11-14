"""Bank downloads in CSV/TSV and OFX/QFX (Quicken) format.

These are usually more reliable than PDF statements. Every row becomes a transaction or a diagnostic line
saying why it was skipped; nothing is dropped silently.

CSV columns are found from the header (or, without a header, from the data):
  date (transaction date preferred over posting date), description, amount OR separate debit/credit columns,
  running balance, a type column (DEBIT/CREDIT, Sale/Payment/Return) and a status column (Pending rows skipped).
Money in vs out, strongest evidence first: debit/credit column > type column > running balance > sign convention
(the sign most rows use is "money out": purchases outnumber payments).
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import date

from .parser import BANKS, LineDiag, StatementInfo, Transaction, detect_date_order, match_date_at

TABULAR_EXTS = (".csv", ".tsv", ".ofx", ".qfx")

H = {
    "date": re.compile(r"\bdate\b|^dt$|^posted$|^trans\.?$", re.I),
    "desc": re.compile(r"desc|payee|merchant|^name$|narrative|particulars|^memo$|^details?$|transaction$", re.I),
    "amount": re.compile(r"^(transaction )?amount( \(.*\))?$|^amt$|^value$|^amount \w+$", re.I),
    "debit": re.compile(r"debit|withdraw|money out|paid out|^charges?$|^out$", re.I),
    "credit": re.compile(r"^credits?$|credit amount|deposit|money in|paid in|^in$|payments?( and credits)?$", re.I),
    "balance": re.compile(r"balance|running bal", re.I),
    "type": re.compile(r"^(transaction )?type$|^details$|^trans(action)? type$|^debit/credit$|^dr/cr$", re.I),
    "status": re.compile(r"^status$", re.I),
    "acct": re.compile(r"card ?(no|number|#)|account ?(no|number|#)|^account$|card member|last ?4", re.I),
}
OUT_TYPES = re.compile(r"\b(debit|dr|sale|purchase|withdrawal|fee|charge|check|atm)\b", re.I)
IN_TYPES = re.compile(r"\b(credit|cr|payment|return|refund|deposit|dividend|interest)\b", re.I)


def _type_direction(r, cols):
    """A short cell like DEBIT / CREDIT / Sale / Payment / DEBIT_CARD / MISC_CREDIT says which way money went."""
    skip = {cols.get("desc"), cols.get("date")}
    order = [cols["type"]] if "type" in cols else []
    order += [i for i in range(len(r)) if i not in skip and i not in order]
    for i in order:
        c = r[i].strip().replace("_", " ") if i < len(r) else ""
        if not c or len(c) > 20 or re.search(r"\d", c):
            continue
        o, n = bool(OUT_TYPES.search(c)), bool(IN_TYPES.search(c))
        if o != n:
            return "out" if o else "in"
    return None
CARD_HINT = re.compile(r"card|visa|mastercard|amex|american express|discover|freedom|sapphire|quicksilver|venture|"
                       r"savor|citi|apple ?card", re.I)
BANK_HINT = re.compile(r"checking|chequing|savings|\bchk\b|\bsav\b|money market|current account", re.I)


def _num(s: str):
    """Amount from a cell: '$1,234.56', '(12.00)', '12.00-', '-5', '12.00 CR'. None if not a number."""
    s = (s or "").strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.endswith("-")
    if re.search(r"\bCR\b", s, re.I):
        neg = True
    t = re.sub(r"[^0-9.]", "", s.replace(",", ""))
    if not t or t.count(".") > 1 or not re.search(r"\d", t):
        return None
    if re.search(r"[A-Za-z]{3,}", s) and not re.search(r"\b(CR|DR|USD)\b", s, re.I):
        return None
    v = float(t)
    return -v if neg else v


def _date(s: str, order: str):
    s = (s or "").strip()
    r = match_date_at(s, 0, order)
    if r and r[2]:
        try:
            return date(r[2], r[0], r[1])
        except ValueError:
            return None
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", s)   # 20260131
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _file_facts(path: str, header_text: str):
    """Bank, last 4 digits, card/bank hints from the file name and header."""
    name = os.path.basename(path)
    spaced = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", name)   # "Chase1234_..." -> "Chase 1234 ..."
    blob = re.sub(r"[_\-.]+", " ", spaced) + " " + header_text
    bank = next((n for n, rx, _ in BANKS if re.search(rx, blob.upper())), "")
    last4 = ""
    m = re.search(r"(?:^|[^0-9])(\d{4})(?=[^0-9]|$)", re.sub(r"\d{5,}", " ", name))
    if m:
        last4 = m.group(1)
    kind = "card" if CARD_HINT.search(blob) else ("bank" if BANK_HINT.search(blob) else "unknown")
    acct_type = "savings" if re.search(r"savings|\bsav\b|money market", blob, re.I) else (
        "checking" if re.search(r"checking|chequing|\bchk\b", blob, re.I) else "")
    return bank, last4, kind, acct_type


# ------------------------------------------------------------------ CSV

def _read_rows(text: str):
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delim = dialect.delimiter
    except csv.Error:
        delim = max(",\t;", key=lambda d: sample.count(d))
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _find_header(rows):
    for i, r in enumerate(rows[:25]):
        cells = [c.strip() for c in r]
        if sum(1 for c in cells if c) < 2:
            continue
        roles = {k for c in cells for k, rx in H.items() if c and rx.search(c)}
        if ("date" in roles and len(roles) >= 2 and not any(_date(c, "MDY") for c in cells)
                and ({"amount", "debit", "credit"} & roles)):
            return i
    return None


def _map_columns(head):
    cols = {}
    lower = [h.strip().lower() for h in head]

    def pick(role, prefer=None, avoid=None):
        hits = [i for i, h in enumerate(lower) if h and H[role].search(h) and i not in cols.values()]
        if avoid:
            hits = [i for i in hits if not re.search(avoid, lower[i])] or hits
        if prefer:
            best = [i for i in hits if re.search(prefer, lower[i])]
            if best:
                return best[0]
        return hits[0] if hits else None

    for role, prefer, avoid in [
        ("balance", None, None), ("status", None, None), ("acct", None, None),
        ("type", r"type", None),
        ("date", r"trans", r"post"),
        ("debit", None, None), ("credit", None, r"card"),
        ("amount", None, r"balance"),
        ("desc", r"^description$|^transaction description$|payee|merchant", r"^details$|^type$"),
    ]:
        i = pick(role, prefer, avoid)
        if i is not None:
            cols[role] = i
    if "date" not in cols:
        i = pick("date")
        if i is not None:
            cols["date"] = i
    return cols


def _infer_columns(rows, order):
    """No header: date = mostly dates, amount = first numeric column, description = longest text."""
    body = rows[:30]
    n = max(len(r) for r in body)
    cols = {}

    def share(i, fn):
        vals = [r[i] for r in body if i < len(r) and r[i].strip()]
        return sum(1 for v in vals if fn(v)) / len(vals) if vals else 0
    for i in range(n):
        if "date" not in cols and share(i, lambda v: _date(v, order)) >= 0.6:
            cols["date"] = i
    for i in range(n):
        if i != cols.get("date") and share(i, lambda v: _num(v) is not None and "." in v) >= 0.6:
            cols["amount"] = i
            break
    best, length = None, 0
    for i in range(n):
        if i in cols.values():
            continue
        L = sum(len(r[i]) for r in body if i < len(r) and re.search(r"[A-Za-z]", r[i]))
        if L > length:
            best, length = i, L
    if best is not None:
        cols["desc"] = best
    return cols


def parse_csv(path: str, text: str):
    rows = [r for r in _read_rows(text) if any(c.strip() for c in r)]
    diags = []
    info = StatementInfo()
    if not rows:
        return [], info, diags
    hi = _find_header(rows)
    head = rows[hi] if hi is not None else []
    order = detect_date_order("\n".join(",".join(r) for r in rows[(hi or 0):][:200]), "auto")
    cols = _map_columns(head) if hi is not None else _infer_columns(rows, order)
    bank, last4, kind, acct_type = _file_facts(path, " ".join(head))
    for i, r in enumerate(rows[:hi] if hi else []):
        diags.append(LineDiag(0, ", ".join(c for c in r if c), "info", "before the column headings"))
    if hi is not None:
        diags.append(LineDiag(0, ", ".join(head), "header",
                              "columns: " + ", ".join(f"{k}={head[v]}" for k, v in sorted(cols.items(), key=lambda x: x[1]))))
    body = rows[hi + 1:] if hi is not None else rows
    if "date" not in cols or not ({"amount", "debit", "credit"} & cols.keys()):
        for r in body[:50]:
            diags.append(LineDiag(0, ", ".join(r), "skipped", "couldn't find the date and amount columns"))
        info.recon_detail = "Couldn't tell which columns hold the date and the amount."
        return [], info, diags

    def cell(r, k):
        i = cols.get(k)
        return r[i].strip() if i is not None and i < len(r) else ""

    # account number column (e.g. "Card No.": 1234)
    acct_cols = [i for i, h in enumerate(head) if H["acct"].search(h.strip())] or (
        [cols["acct"]] if "acct" in cols else [])
    acct_vals = set()
    for i in acct_cols:   # e.g. Amex has "Card Member" (a name) and "Account #" (digits): use the one with digits
        vals = {re.sub(r"\D", "", r[i])[-4:] for r in body if i < len(r) and re.search(r"\d{4}", r[i])}
        if vals:
            acct_vals = vals
            break
    if len(acct_vals) == 1:
        last4 = acct_vals.pop()
    tvals = [cell(r, "type") for r in body if cell(r, "type")]
    if kind == "unknown":
        if any(re.match(r"^(sale|return)$", v, re.I) for v in tvals) or ("acct" in cols and re.search(
                r"card", head[cols["acct"]] if head else "", re.I)):
            kind = "card"
        elif "balance" in cols:
            kind = "bank"
    info.kind, info.bank, info.last4, info.account_type, info.date_order = kind, bank, last4, acct_type, order

    raw = []
    for r in body:
        line = ", ".join(r)
        if re.match(r"pending", cell(r, "status"), re.I):
            diags.append(LineDiag(0, line, "skipped", "pending (import it once it posts)"))
            continue
        d = _date(cell(r, "date"), order)
        desc = re.sub(r"\s+", " ", cell(r, "desc")).strip()
        if not d:
            diags.append(LineDiag(0, line, "skipped" if any(_num(c) for c in r) else "info",
                                  "no date" if any(_num(c) for c in r) else "not a transaction row"))
            continue
        amt = direction = None
        if "debit" in cols or "credit" in cols:
            dv, cv = _num(cell(r, "debit")), _num(cell(r, "credit"))
            if dv:
                amt, direction = abs(dv), "out"
            elif cv:
                amt, direction = abs(cv), "in"
        if amt is None and "amount" in cols:
            v = _num(cell(r, "amount"))
            if v:
                amt = v
        if amt is None or amt == 0:
            diags.append(LineDiag(0, line, "skipped", "no amount"))
            continue
        if not re.search(r"[A-Za-z]{2,}", desc):
            desc = desc or cell(r, "type") or "(no description)"
        tdir = _type_direction(r, cols)
        raw.append(dict(d=d, desc=desc, amt=amt, dir=direction, tdir=tdir, bal=_num(cell(r, "balance")),
                        diag=len(diags)))
        diags.append(LineDiag(0, line, "transaction", ""))

    # sign convention for the amount column: the sign most rows use is money out
    signed = [x for x in raw if x["dir"] is None]
    neg = sum(1 for x in signed if x["amt"] < 0)
    neg_is_out = neg >= len(signed) - neg
    # running balance: check in file order and reversed (downloads are often newest first)
    bal_dir = {}
    with_bal = [x for x in raw if x["bal"] is not None]
    for seq in (with_bal, list(reversed(with_bal))):
        got = {}
        for a, b in zip(seq, seq[1:]):
            delta = round(b["bal"] - a["bal"], 2)
            mag = abs(b["amt"])
            if abs(abs(delta) - mag) < 0.011:
                up = delta > 0
                got[id(b)] = ("out" if up else "in") if kind == "card" else ("in" if up else "out")
        if len(got) > len(bal_dir):
            bal_dir = got
    checks = len(bal_dir)

    txs = []
    for x in raw:
        if x["dir"]:
            dirn, ev = x["dir"], "column"
        elif x["tdir"]:
            dirn, ev = x["tdir"], "type"
        elif id(x) in bal_dir:
            dirn, ev = bal_dir[id(x)], "balance"
        else:
            dirn = ("out" if x["amt"] < 0 else "in") if neg_is_out else ("out" if x["amt"] > 0 else "in")
            ev = "sign"
        diags[x["diag"]].reason = f"{'money in' if dirn == 'in' else 'money out'} ({ev})"
        txs.append(Transaction(date=x["d"], description=x["desc"], amount=round(abs(x["amt"]), 2),
                               is_credit=dirn == "in", source_file=path, kind=kind, evidence=ev,
                               balance=x["bal"], account_type=acct_type))
    if txs:
        ds = [t.date for t in txs]
        info.period_start, info.period_end = min(ds), max(ds)
    for t in txs:
        t.account = info.account_key
    if checks >= 3 and checks >= 0.8 * (len(with_bal) - 1):
        info.recon_status, info.recon_detail = "balance-verified", f"{checks} rows checked against the balance column."
    else:
        info.recon_status = "unverified"
        info.recon_detail = "CSV download: no statement balances to check against."
    return txs, info, diags


# ------------------------------------------------------------------ OFX / QFX

def _tag(block: str, tag: str):
    m = re.search(rf"<{tag}>\s*([^<\r\n]*)", block, re.I)
    return m.group(1).strip() if m else ""


def parse_ofx(path: str, text: str):
    info = StatementInfo()
    diags = []
    bank, last4, kind, acct_type = _file_facts(path, "")
    if re.search(r"<CCSTMTRS>|<CCACCTFROM>", text, re.I):
        kind = "card"
    elif re.search(r"<BANKACCTFROM>|<STMTRS>", text, re.I):
        kind = "bank"
        at = _tag(text, "ACCTTYPE").upper()
        acct_type = "savings" if at in ("SAVINGS", "MONEYMRKT") else ("checking" if at == "CHECKING" else acct_type)
    acct = _tag(text, "ACCTID")
    if re.search(r"\d{4}", acct):
        last4 = re.sub(r"\D", "", acct)[-4:]
    org = _tag(text, "ORG")
    if org:
        bank = next((n for n, rx, _ in BANKS if re.search(rx, org.upper())), bank or org.title())
    info.kind, info.bank, info.last4, info.account_type = kind, bank, last4, acct_type
    s, e = _date(_tag(text, "DTSTART")[:8], "MDY"), _date(_tag(text, "DTEND")[:8], "MDY")
    led = re.search(r"<LEDGERBAL>(.*?)(</LEDGERBAL>|<AVAILBAL>|$)", text, re.I | re.S)
    if led:
        v = _num(_tag(led.group(1), "BALAMT"))
        if v is not None:
            info.closing_balance = abs(v) if kind == "card" else v
    seen = set()
    txs = []
    for blk in re.findall(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)", text, re.I | re.S):
        fitid = _tag(blk, "FITID")
        d = _date(_tag(blk, "DTPOSTED")[:8], "MDY")
        amt = _num(_tag(blk, "TRNAMT"))
        name, memo = _tag(blk, "NAME"), _tag(blk, "MEMO")
        desc = name if name and not re.fullmatch(r"(POS|ACH|DEBIT|CREDIT|CHECK)( \w+)?", name, re.I) else \
            " ".join(x for x in (name, memo) if x)
        line = f"{_tag(blk, 'DTPOSTED')[:8]}  {desc}  {_tag(blk, 'TRNAMT')}"
        if fitid and fitid in seen:
            diags.append(LineDiag(0, line, "skipped", "same bank transaction ID listed twice"))
            continue
        seen.add(fitid)
        if not d or not amt:
            diags.append(LineDiag(0, line, "skipped", "no date or amount"))
            continue
        # OFX amounts are signed from your side: negative = money out (purchases on a card too)
        is_in = amt > 0
        diags.append(LineDiag(0, line, "transaction", f"{'money in' if is_in else 'money out'} (OFX sign)"))
        txs.append(Transaction(date=d, description=desc or "(no description)", amount=round(abs(amt), 2),
                               is_credit=is_in, source_file=path, kind=kind, evidence="column",
                               account_type=acct_type))
    if txs:
        ds = [t.date for t in txs]
        info.period_start, info.period_end = s or min(ds), e or max(ds)
    for t in txs:
        t.account = info.account_key
    info.recon_status = "unverified"
    info.recon_detail = "Bank download (OFX): amounts come with their sign from the bank."
    return txs, info, diags


def parse_tabular(path: str):
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if path.lower().endswith((".ofx", ".qfx")) or re.search(r"<OFX>|OFXHEADER", text[:2000], re.I):
        return (*parse_ofx(path, text), "ofx")
    return (*parse_csv(path, text), "csv")
