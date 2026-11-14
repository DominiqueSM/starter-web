"""Generate test statement PDFs that mimic real-world layouts, plus expected results.

Developer tool (needs reportlab: pip install reportlab). The generated PDFs are committed, so the
tests themselves only need the app's bundled code.

    python tests/make_fixtures.py
"""
import json
import os
import random
from datetime import date, timedelta

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")
random.seed(42)
F, B = "Helvetica", "Helvetica-Bold"

expected = {"spending_total": 0.0, "card_payments": 0, "files": {}}


def money(v):
    return f"{v:,.2f}"


class Page:
    def __init__(self, path, password=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        kw = {}
        if password:
            from reportlab.lib import pdfencrypt
            kw["encrypt"] = pdfencrypt.StandardEncryption(password, canPrint=1)
        self.c = canvas.Canvas(path, pagesize=letter, **kw)
        self.y = 750

    def text(self, x, s, font=F, size=9, right=False):
        self.c.setFont(font, size)
        (self.c.drawRightString if right else self.c.drawString)(x, self.y, s)

    def glued(self, x, parts):
        """Draw fragments touching each other (how many statements produce glued text)."""
        self.c.setFont(F, 9)
        for p in parts:
            self.c.drawString(x, self.y, p)
            x += self.c.stringWidth(p, F, 9)

    def nl(self, dy=13):
        self.y -= dy
        if self.y < 60:
            self.c.showPage()
            self.y = 750

    def save(self):
        self.c.save()


# ----------------------------------------------------------------------------- Chase-style credit card
CARD_PAYMENTS = []   # (date, amount) paid from checking


def card_month(y, m, prev_balance, netflix_style, hulu_style):
    close = date(y, m, 13)
    opened = (close.replace(day=1) - timedelta(days=1)).replace(day=14)
    rows = []

    def add(d, parts, amt):
        rows.append((d, parts, amt))

    def d_(day):  # dates inside the period (Dec 14 .. Jan 13 etc)
        return opened + timedelta(days=day)
    add(d_(2), {"glued": netflix_style}, 21.64)
    add(d_(5), {"glued": hulu_style}, 35.71)
    add(d_(7), {"glued": ["CLAUDE.AI SUBSCRIPTION", "ANTHROPIC.COM", "CA"]}, 21.32)
    add(d_(9), {"text": "NTTA AUTOCHARGE" if m % 2 else "NTTA"}, 50.00)
    add(d_(11), {"text": "SPOTIFY USA"}, 11.99)
    for k in range(6):
        add(d_(random.randint(0, 29)), {"text": random.choice(["DOORDASH*CHIPOTLE", "UBER   *EATS PENDING",
                                                                "TST* PINK DOOR DALLAS TX"])},
            round(random.uniform(22, 60), 2))
    for k in range(5):
        add(d_(random.randint(0, 29)), {"text": random.choice(["STARBUCKS STORE 08812", "AMZN Mktp US*2K3LM9",
                                                                "TOM THUMB #2512", "SHELL OIL 57444"])},
            round(random.uniform(5, 95), 2))
    add(d_(20), {"text": "PATILLA BARBERSHOP DALLAS TX"}, 62.00)
    rows.sort(key=lambda r: r[0])
    purchases = round(sum(r[2] for r in rows), 2)
    payment = round(prev_balance, 2)
    pay_date = d_(16)
    CARD_PAYMENTS.append((pay_date, payment))
    new_balance = round(prev_balance - payment + purchases, 2)

    path = os.path.join(OUT, "Chase Freedom", f"{close:%Y%m%d}-statements-1234.pdf")
    p = Page(path)
    p.text(40, "CHASE FREEDOM UNLIMITED", B, 13); p.nl(16)
    p.text(40, "Manage your account online: www.chase.com/cardhelp"); p.nl()
    p.text(40, f"Opening/Closing Date {opened:%m/%d/%y} - {close:%m/%d/%y}"); p.nl()
    p.text(40, "Account Number: XXXX XXXX XXXX 1234"); p.nl(20)
    p.text(40, "ACCOUNT SUMMARY", B, 10); p.nl()
    for label, v in [("Previous Balance", f"${money(prev_balance)}"), ("Payment, Credits", f"-${money(payment)}"),
                     ("Purchases", f"+${money(purchases)}"), ("Cash Advances", "$0.00"),
                     ("Fees Charged", "$0.00"), ("Interest Charged", "$0.00"), ("New Balance", f"${money(new_balance)}")]:
        p.text(40, label); p.text(260, v, right=True); p.nl()
    p.text(40, f"Payment Due Date: {(close + timedelta(days=25)):%m/%d/%y}"); p.nl()
    p.text(40, "Minimum Payment Due: $40.00"); p.nl(20)
    p.text(40, "ACCOUNT ACTIVITY", B, 10); p.nl(15)
    p.text(40, "Date of", B); p.nl(10)
    p.text(40, "Transaction", B); p.text(110, "Merchant Name or Transaction Description", B); p.text(560, "$ Amount", B, right=True); p.nl()
    p.text(40, "PAYMENTS AND OTHER CREDITS", B); p.nl()
    p.text(40, f"{pay_date:%m/%d}"); p.text(110, "Payment Thank You-Mobile"); p.text(560, f"-{money(payment)}", right=True); p.nl()
    p.text(40, "PURCHASE", B); p.nl()
    for d, parts, amt in rows:
        p.text(40, f"{d:%m/%d}")
        if "glued" in parts:
            p.glued(110, parts["glued"])
        else:
            p.text(110, parts["text"])
        p.text(560, money(amt), right=True); p.nl()
    p.text(40, "Total fees charged in 2026 $0.00"); p.nl()
    p.save()
    expected["spending_total"] += purchases
    expected["files"][os.path.relpath(path, OUT)] = {"count": len(rows) + 1, "recon": "reconciled", "kind": "card",
                                                     "last4": "1234"}
    return new_balance, rows


# ----------------------------------------------------------------------------- Chase-style checking
def checking_month(y, m, begin, all_rows_out):
    start = date(y, m, 1)
    end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    rows = []
    rows.append((date(y, m, 1), "Online Payment 4432178 To Open House", -2490.00, None))
    rows.append((date(y, m, 1), "Acme Corp Payroll PPD ID: 9911223", 3250.00, None))
    rows.append((date(y, m, 15), "Acme Corp Payroll PPD ID: 9911223", 3250.00, None))
    rows.append((date(y, m, 3), "American Worth TX Loan Pmt", -204.00, None))
    rows.append((date(y, m, 17), "American Worth TX Loan Pmt", -204.00, None))
    rows.append((date(y, m, 6), "DEPT EDUCATION STUDENT LN PPD ID: 4440", -150.00, None))
    rows.append((date(y, m, 9), "Zelle Payment To John Smith Jpm99abcd", -40.00, "Memo: pizza night"))
    rows.append((date(y, m, 12), "Card Purchase 12/11 Kroger #622 Dallas TX Card 5678", -86.25, None))
    for pd, amt in CARD_PAYMENTS:
        if start <= pd <= end:
            rows.append((pd, "Payment To Chase Card Ending IN 1234", -amt, None))
    rows.sort(key=lambda r: r[0])
    bal = begin
    path = os.path.join(OUT, "Chase Checking", f"{end:%Y%m%d}-statements-9876.pdf")
    p = Page(path)
    p.text(40, "JPMorgan Chase Bank, N.A.", B, 11); p.nl(15)
    p.text(40, f"{start:%B %d, %Y} through {end:%B %d, %Y}"); p.nl()
    p.text(40, "Account Number: 000000555559876"); p.nl(20)
    p.text(40, "CHASE TOTAL CHECKING", B, 11); p.nl(15)
    ins = sum(r[2] for r in rows if r[2] > 0)
    outs = -sum(r[2] for r in rows if r[2] < 0)
    ending = round(begin + ins - outs, 2)
    p.text(40, "CHECKING SUMMARY", B); p.nl()
    for label, v in [("Beginning Balance", f"${money(begin)}"), ("Deposits and Additions", money(ins)),
                     ("Electronic Withdrawals", f"-{money(outs)}"), ("Ending Balance", f"${money(ending)}")]:
        p.text(40, label); p.text(300, v, right=True); p.nl()
    p.nl(8)
    p.text(40, "TRANSACTION DETAIL", B); p.nl(15)
    p.text(40, "DATE", B); p.text(90, "DESCRIPTION", B); p.text(470, "AMOUNT", B, right=True); p.text(560, "BALANCE", B, right=True); p.nl()
    p.text(90, "Beginning Balance"); p.text(560, f"${money(begin)}", right=True); p.nl()
    for d, desc, amt, cont in rows:
        bal = round(bal + amt, 2)
        p.text(40, f"{d:%m/%d}"); p.text(90, desc)
        p.text(470, money(amt) if amt > 0 else f"-{money(-amt)}", right=True); p.text(560, money(bal), right=True); p.nl(11)
        if cont:
            p.text(100, cont); p.nl(11)
        p.nl(2)
        all_rows_out.append((d, desc, amt))
    p.text(90, "Ending Balance"); p.text(560, f"${money(bal)}", right=True); p.nl()
    p.save()
    real_spend = -sum(a for _, desc, a, _c in rows if a < 0 and "Chase Card" not in desc)
    expected["spending_total"] += real_spend
    expected["card_payments"] += sum(1 for r in rows if "Chase Card" in r[1])
    expected["files"][os.path.relpath(path, OUT)] = {"count": len(rows), "recon": "reconciled", "kind": "bank",
                                                     "last4": "9876"}
    return ending, rows


def overlap_download(rows):
    """A 'custom date range' download of the same checking account that overlaps two statements."""
    sel = [r for r in rows if date(2025, 12, 15) <= r[0] <= date(2026, 1, 15)]
    path = os.path.join(OUT, "Chase Checking", "activity-download-dec15-jan15.pdf")
    p = Page(path)
    p.text(40, "Chase Account Activity", B, 11); p.nl(15)
    p.text(40, "Account ending in 9876   Checking"); p.nl()
    p.text(40, "Date range: 12/15/2025 - 01/15/2026"); p.nl(18)
    p.text(40, "Posting Date", B); p.text(130, "Description", B); p.text(470, "Amount", B, right=True); p.nl()
    for d, desc, amt in sel:
        p.text(40, f"{d:%m/%d/%Y}"); p.text(130, desc); p.text(470, money(amt) if amt > 0 else f"-{money(-amt)}", right=True); p.nl()
    p.save()
    expected["overlap_duplicates"] = len(sel)
    expected["files"][os.path.relpath(path, OUT)] = {"count": len(sel), "recon": "unverified", "kind": "bank",
                                                     "last4": "9876"}


# ----------------------------------------------------------------------------- debit/credit columns
def debit_credit_columns():
    path = os.path.join(OUT, "Credit Union", "statement-2026-01.pdf")
    p = Page(path)
    p.text(40, "LONE STAR COMMUNITY CREDIT UNION", B, 12); p.nl(16)
    p.text(40, "Share Savings   Account # ****4411"); p.nl()
    p.text(40, "Statement Period: 01/01/2026 to 01/31/2026"); p.nl(18)
    p.text(40, "Date", B); p.text(100, "Description", B); p.text(400, "Debits", B, right=True)
    p.text(480, "Credits", B, right=True); p.text(560, "Balance", B, right=True); p.nl()
    bal = 1200.00
    p.text(40, "01/01/2026"); p.text(100, "Previous Balance"); p.text(560, money(bal), right=True); p.nl()
    rows = [("01/04/2026", "WALMART SUPERCENTER #1123", 64.10, 0), ("01/09/2026", "DIVIDEND", 0, 1.25),
            ("01/14/2026", "CVS/PHARMACY #0442 2.99 OFF COUPON", 18.40, 0), ("01/20/2026", "REFUND AMAZON", 0, 25.00),
            ("01/25/2026", "PLANET FITNESS CLUB FEES", 24.99, 0)]
    for d, desc, dr, cr in rows:
        bal = round(bal - dr + cr, 2)
        p.text(40, d); p.text(100, desc)
        if dr:
            p.text(400, money(dr), right=True)
        if cr:
            p.text(480, money(cr), right=True)
        p.text(560, money(bal), right=True); p.nl()
    p.text(100, "Ending Balance"); p.text(560, money(bal), right=True); p.nl()
    p.save()
    expected["spending_total"] += 64.10 + 18.40 + 24.99 - 25.00   # the Amazon refund is netted off spending
    expected["files"][os.path.relpath(path, OUT)] = {"count": len(rows), "recon": "reconciled", "kind": "bank",
                                                     "last4": "4411"}


# ----------------------------------------------------------------------------- DD/MM/YYYY statement
def dmy_statement():
    path = os.path.join(OUT, "UK Account", "estatement-feb-2026.pdf")
    p = Page(path)
    p.text(40, "Current Account Statement", B, 12); p.nl(16)
    p.text(40, "Sort code 12-34-56   Account number 87654321"); p.nl()
    p.text(40, "Period: 01/02/2026 - 28/02/2026"); p.nl(18)
    p.text(40, "Date", B); p.text(110, "Description", B); p.text(400, "Money Out", B, right=True)
    p.text(480, "Money In", B, right=True); p.text(560, "Balance", B, right=True); p.nl()
    bal = 800.00
    p.text(40, "01/02/2026"); p.text(110, "Opening Balance"); p.text(560, money(bal), right=True); p.nl()
    rows = [("03/02/2026", "TESCO STORES 3021", 45.20, 0), ("13/02/2026", "COSTA COFFEE", 3.40, 0),
            ("25/02/2026", "SALARY ACME LTD", 0, 2100.00), ("27/02/2026", "NETFLIX.COM", 10.99, 0)]
    for d, desc, out, inn in rows:
        bal = round(bal - out + inn, 2)
        p.text(40, d); p.text(110, desc)
        if out:
            p.text(400, money(out), right=True)
        if inn:
            p.text(480, money(inn), right=True)
        p.text(560, money(bal), right=True); p.nl()
    p.text(110, "Closing Balance"); p.text(560, money(bal), right=True); p.nl()
    p.save()
    expected["spending_total"] += 45.20 + 3.40 + 10.99
    expected["files"][os.path.relpath(path, OUT)] = {"count": len(rows), "recon": "reconciled", "kind": "bank",
                                                     "last4": "4321", "dates": ["2026-02-03", "2026-02-13",
                                                                                 "2026-02-25", "2026-02-27"]}


def locked():
    path = os.path.join(OUT, "locked-statement.pdf")
    p = Page(path, password="secret")
    p.text(40, "Statement Period: 03/01/2026 to 03/31/2026"); p.nl()
    p.text(40, "Date", B); p.text(100, "Description", B); p.text(560, "Amount", B, right=True); p.nl()
    p.text(40, "03/05/2026"); p.text(100, "TARGET 00012345"); p.text(560, "42.00", right=True); p.nl()
    p.save()
    expected["spending_total"] += 42.00
    expected["locked"] = {"file": os.path.relpath(path, OUT), "password": "secret", "count": 1}


def main():
    import shutil
    shutil.rmtree(OUT, ignore_errors=True)
    prev = 812.40
    netflix = [["NETFLIX.COM", " NETFLIX.COM", " CA"], ["NETFLIX.COM", "NETFLIX.COM", "CA"], ["NETFLIX.COM"]]
    hulu = [["HLU*HULUPLUS"], ["HULU 877-8244858", " CA"], ["HULU 877-8244858", " CA"]]
    card_rows = []
    for i, (y, m) in enumerate([(2025, 12), (2026, 1), (2026, 2)]):
        prev, rows = card_month(y, m, prev, netflix[i], hulu[i])
        card_rows.extend(rows)
    expected["year_crossing"] = sorted({r[0].isoformat() for r in card_rows if r[0].year == 2025})[:3]
    begin = 4100.00
    chk_rows = []
    for y, m in [(2025, 12), (2026, 1), (2026, 2)]:
        begin, _ = checking_month(y, m, begin, chk_rows)
    overlap_download(chk_rows)
    debit_credit_columns()
    dmy_statement()
    locked()
    expected["spending_total"] = round(expected["spending_total"], 2)
    with open(os.path.join(HERE, "expected.json"), "w") as f:
        json.dump(expected, f, indent=2)
    print("wrote fixtures; expected spending", expected["spending_total"])


if __name__ == "__main__":
    main()
