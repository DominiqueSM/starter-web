"""PDF text extraction and transaction parsing.

Everything here runs locally. No network access is used anywhere in this app.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from pypdf import PdfReader


@dataclass
class Transaction:
    date: date
    description: str
    amount: float          # always positive
    is_credit: bool        # True = money in (refund, payment, deposit)
    source_file: str
    category: str = "Other"
    merchant: str = ""
    excluded: bool = False
    year_guessed: bool = False
    uid: str = ""
    group: str = ""          # top-level subfolder the PDF came from

    @property
    def is_spending(self) -> bool:
        return not self.is_credit and not self.excluded


@dataclass
class FileResult:
    path: str
    status: str = "ok"     # ok | no-text | no-transactions | error | duplicate
    pages: int = 0
    transactions: list = field(default_factory=list)
    note: str = ""
    group: str = ""


MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
MON_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"

# Dates that may begin a transaction line
DATE_PATTERNS = [
    # 2024-01-31
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    # 01/31/2024, 1-31-24, 01/31
    (re.compile(r"(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?\b"), "mdy"),
    # Jan 31, 2024 / Jan 31
    (re.compile(r"(" + MON_RE + r")\s+(\d{1,2})(?:,?\s+(\d{4}))?\b", re.I), "mon_d_y"),
    # 31 Jan 2024 / 31 Jan
    (re.compile(r"(\d{1,2})\s+(" + MON_RE + r")(?:,?\s+(\d{4}))?\b", re.I), "d_mon_y"),
]

AMOUNT_RE = re.compile(
    r"(?<![\w.,/])"
    r"(\(?-?\s?\$?\s?-?\(?\d{1,3}(?:,\d{3})*\.\d{2}\)?|\(?-?\$?-?\d+\.\d{2}\)?)"
    r"(\s?(?:CR|DR|-))?"
    r"(?![\w.,/%])",
    re.I,
)

SKIP_DESC_RE = re.compile(
    r"\b(beginning|ending|opening|closing|previous|new|daily|average|available)\s+balance\b"
    r"|balance\s+(forward|brought|carried)|^total\b|\bsubtotal\b|minimum payment|payment due"
    r"|credit limit|statement (period|date|closing)|^page \d",
    re.I,
)

CREDIT_SECTION_RE = re.compile(
    r"^\s*(deposits?( and (other )?(additions|credits))?|credits?|payments?(,| and)? (other )?credits?"
    r"|payments and credits|other credits|electronic deposits|additions)\s*:?\s*$",
    re.I,
)
DEBIT_SECTION_RE = re.compile(
    r"^\s*(withdrawals?( and (other )?(subtractions|debits))?|debits?|purchases?( and (other )?(charges|debits|adjustments))?"
    r"|checks?( paid)?|electronic withdrawals|atm (&|and) debit card withdrawals|fees( charged)?|interest charged"
    r"|purchases and adjustments|other (debits|withdrawals|subtractions)|card purchases|transactions)\s*:?\s*$",
    re.I,
)

CREDIT_KEYWORDS = re.compile(
    r"\b(payroll|direct dep|dir dep|deposit|salary|refund|return|reversal|cashback|cash back reward"
    r"|interest paid|interest earned|payment[\s,-]*thank|thank you for your payment|autopay payment"
    r"|online payment|payment received|mobile payment|credit adjustment|statement credit|zelle from|transfer from"
    r"|venmo cashout|tax refund|dividend)\b",
    re.I,
)


def file_hash(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text(path: str) -> tuple[str, int]:
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("PDF is password-protected")
    pages = []
    for page in reader.pages:
        txt = ""
        try:
            txt = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            pass
        if not txt.strip():
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
        pages.append(txt)
    return "\n".join(pages), len(reader.pages)


def _to_year(y: str | None) -> int | None:
    if not y:
        return None
    yi = int(y)
    if yi < 100:
        yi += 2000
    return yi if 1990 <= yi <= 2100 else None


def _match_date_at(text: str, pos: int):
    """Try to match a date at exactly `pos`. Returns (month, day, year|None, end) or None."""
    for rx, kind in DATE_PATTERNS:
        m = rx.match(text, pos)
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "mdy":
                mo, d, y = int(m.group(1)), int(m.group(2)), _to_year(m.group(3))
                if m.group(3) and y is None:
                    continue
                # Disambiguate DD/MM when first part > 12
                if mo > 12 and d <= 12:
                    mo, d = d, mo
            elif kind == "mon_d_y":
                mo = MONTHS[m.group(1).lower()[:3]]
                d, y = int(m.group(2)), _to_year(m.group(3))
            else:
                mo = MONTHS[m.group(2).lower()[:3]]
                d, y = int(m.group(1)), _to_year(m.group(3))
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            return mo, d, y, m.end()
        except (KeyError, ValueError):
            continue
    return None


def find_statement_end_date(text: str) -> date | None:
    """Guess the statement closing date: the latest full date mentioned in the document."""
    found = []
    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            r = _match_date_at(text, m.start())
            if r and r[2]:
                mo, d, y, _ = r
                try:
                    dt = date(y, mo, d)
                except ValueError:
                    continue
                if date(1995, 1, 1) <= dt <= date.today().replace(year=date.today().year + 1):
                    found.append(dt)
    if not found:
        return None
    found.sort()
    # Use a high percentile instead of the max so a stray future date (e.g. "valid through 2030") doesn't win
    return found[min(len(found) - 1, int(len(found) * 0.95))]


def parse_amount(raw: str, suffix: str | None) -> tuple[float, bool]:
    """Return (absolute amount, negative_flag)."""
    s = raw.replace("$", "").replace(",", "").replace(" ", "")
    neg = False
    if "(" in s or ")" in s:
        neg = True
    s = s.strip("()")
    if s.startswith("-"):
        neg = True
        s = s.lstrip("-")
    if suffix:
        sfx = suffix.strip().upper()
        if sfx in ("CR", "-"):
            neg = True
    return float(s), neg


def parse_transactions(text: str, source_file: str, fallback_year: int) -> list[Transaction]:
    end_date = find_statement_end_date(text)
    raw_rows = []   # (month, day, year, desc, amount, negflag, section)
    section = None  # 'credit' | 'debit' | None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Section headers (no amounts on the line)
        if not AMOUNT_RE.search(stripped) and len(stripped) < 60:
            if CREDIT_SECTION_RE.match(stripped):
                section = "credit"
                continue
            if DEBIT_SECTION_RE.match(stripped):
                section = "debit"
                continue

        d1 = _match_date_at(stripped, 0)
        if not d1:
            continue
        mo, d, y, pos = d1
        rest = stripped[pos:].lstrip()
        # Optional second date (posting date)
        d2 = _match_date_at(rest, 0)
        if d2:
            rest = rest[d2[3]:].lstrip()

        amounts = list(AMOUNT_RE.finditer(rest))
        if not amounts:
            continue
        first = amounts[0]
        desc = rest[:first.start()].strip(" -*\t")
        desc = re.sub(r"\s{2,}", "  ", desc)
        if not re.search(r"[A-Za-z]{2,}", desc):
            continue
        if SKIP_DESC_RE.search(desc):
            continue
        try:
            amt, neg = parse_amount(first.group(1), first.group(2))
        except ValueError:
            continue
        if amt == 0 or amt > 1_000_000:
            continue
        raw_rows.append((mo, d, y, desc, amt, neg, section))

    if not raw_rows:
        return []

    # Decide what "negative" means in this document. Bank statements often show
    # withdrawals as negative; credit-card statements show purchases as positive.
    non_section = [r for r in raw_rows if r[6] is None]
    neg_count = sum(1 for r in non_section if r[5])
    negatives_are_spending = len(non_section) > 0 and neg_count > len(non_section) / 2

    txs = []
    for mo, d, y, desc, amt, neg, section in raw_rows:
        guessed = False
        if y is None:
            if end_date:
                y = end_date.year
                if mo > end_date.month + 1:  # e.g. December charges on a January statement
                    y -= 1
            else:
                y = fallback_year
                guessed = True
        try:
            dt = date(y, mo, d)
        except ValueError:
            continue

        if section == "credit":
            is_credit = True
        elif section == "debit":
            is_credit = False
        else:
            is_credit = (not neg) if negatives_are_spending else neg
        if CREDIT_KEYWORDS.search(desc):
            is_credit = True

        txs.append(Transaction(
            date=dt, description=desc, amount=round(amt, 2), is_credit=is_credit,
            source_file=source_file, year_guessed=guessed,
        ))
    return txs


def find_pdfs(folder: str) -> list[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.lower().endswith(".pdf") and not fn.startswith("."):
                out.append(os.path.join(root, fn))
    return sorted(out)


def process_folder(folder: str, progress=None) -> list[FileResult]:
    results = []
    seen_hashes = {}
    pdfs = find_pdfs(folder)
    for i, path in enumerate(pdfs):
        if progress:
            progress(i, len(pdfs), os.path.basename(path))
        fr = FileResult(path=path)
        try:
            h = file_hash(path)
            if h in seen_hashes:
                fr.status = "duplicate"
                fr.note = "Identical to " + os.path.basename(seen_hashes[h]) + " (skipped)"
                results.append(fr)
                continue
            seen_hashes[h] = path
            text, fr.pages = extract_text(path)
            if len(text.strip()) < 20:
                fr.status = "no-text"
                fr.note = "No selectable text (probably a scanned image). Download a text-based PDF from your bank instead."
            else:
                fallback_year = datetime.fromtimestamp(os.path.getmtime(path)).year
                fr.transactions = parse_transactions(text, path, fallback_year)
                if not fr.transactions:
                    fr.status = "no-transactions"
                    fr.note = "Text found, but no lines that look like 'date  description  amount'."
                elif any(t.year_guessed for t in fr.transactions):
                    fr.note = "Year not found in document; used file date year."
        except Exception as e:  # keep going on bad files
            fr.status = "error"
            fr.note = str(e)[:200]
        results.append(fr)
    if progress:
        progress(len(pdfs), len(pdfs), "")
    return results
