"""Regression tests. Run from the spending-analyzer folder:

    python -m unittest discover -s tests -v

The fixture PDFs in tests/fixtures mimic real statement layouts (see make_fixtures.py) and
tests/expected.json holds the true answers they were generated from.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app")
sys.path[:0] = [os.path.join(APP, "vendor"), APP]

from spending_analyzer.categorize import Categorizer, infer_rent  # noqa: E402
from spending_analyzer.extract import file_hash, parse_file, process_folder  # noqa: E402
from spending_analyzer.insights import analyze  # noqa: E402
from spending_analyzer.linking import link  # noqa: E402
from spending_analyzer.merchants import canonical  # noqa: E402
from spending_analyzer.parser import Transaction, match_date_at, parse_amount, parse_statement  # noqa: E402
from spending_analyzer.pdftext import Line  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
with open(os.path.join(HERE, "expected.json")) as f:
    EXPECTED = json.load(f)


def rel(p):
    return os.path.relpath(p, FIX)


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        res = process_folder(FIX)
        locked = EXPECTED["locked"]
        cls.locked_before = next(r for r in res if rel(r.path) == locked["file"])
        unlocked = parse_file(cls.locked_before.path, file_hash(cls.locked_before.path), password=locked["password"])
        cls.results = [unlocked if r is cls.locked_before else r for r in res]
        for r in cls.results:
            r.group = rel(r.path).split(os.sep)[0] if os.sep in rel(r.path) else ""
            for t in r.transactions:
                t.group = r.group
        cls.txs = [t for r in cls.results for t in r.transactions]
        Categorizer(cls.tmp).apply(cls.txs)
        cls.link_stats = link(cls.results)
        infer_rent(cls.txs)
        cls.analysis = analyze(cls.txs)
        cls.by_file = {rel(r.path): r for r in cls.results}

    def test_every_file_parsed_with_expected_counts(self):
        for name, exp in EXPECTED["files"].items():
            with self.subTest(file=name):
                r = self.by_file[name]
                self.assertEqual(r.status, "ok", r.note)
                self.assertEqual(len(r.transactions), exp["count"])
                self.assertEqual(r.info.kind, exp["kind"])
                self.assertEqual(r.info.last4, exp["last4"])

    def test_statements_reconcile_to_printed_balances(self):
        for name, exp in EXPECTED["files"].items():
            with self.subTest(file=name):
                self.assertEqual(self.by_file[name].info.recon_status, exp["recon"],
                                 self.by_file[name].info.recon_detail)

    def test_total_spending_has_no_double_counting(self):
        self.assertAlmostEqual(self.analysis.total_spent, EXPECTED["spending_total"], places=2)

    def test_card_payments_from_checking_are_transfers(self):
        pays = [t for t in self.txs if "Chase Card" in t.description and not t.duplicate]
        self.assertEqual(len(pays), EXPECTED["card_payments"])
        for t in pays:
            self.assertEqual(t.category, "Transfers & Payments")
            self.assertFalse(any(t is s for s in self.analysis.spending))

    def test_overlapping_download_counted_once(self):
        self.assertEqual(self.link_stats["duplicates"], EXPECTED["overlap_duplicates"])

    def test_recurring_grouped_by_company(self):
        rec = {r.merchant: r for r in self.analysis.recurring}
        for name, amt in [("Netflix", 21.64), ("Hulu", 35.71), ("Anthropic (Claude)", 21.32), ("NTTA (tolls)", 50.0)]:
            with self.subTest(merchant=name):
                self.assertIn(name, rec)
                self.assertAlmostEqual(rec[name].typical_amount, amt)
                self.assertEqual(rec[name].frequency, "Monthly")
        self.assertEqual(sum(1 for m in rec if "netflix" in m.lower()), 1)
        self.assertEqual(rec["Netflix"].kind, "Subscription")
        self.assertEqual(rec["Open House"].kind, "Bill / loan")

    def test_rent_paid_by_bill_pay_is_guessed_as_housing(self):
        rent = [t for t in self.txs if t.merchant == "Open House" and not t.duplicate]
        self.assertTrue(rent)
        self.assertTrue(all(t.category == "Housing" and t.category_source == "guess" for t in rent))

    def test_year_crossing(self):
        card_dates = {t.date.isoformat() for t in self.txs if t.kind == "card"}
        for d in EXPECTED["year_crossing"]:
            self.assertIn(d, card_dates)
        self.assertFalse(any(t.date > date(2026, 2, 28) for t in self.txs if t.kind == "card"))

    def test_multiline_description(self):
        z = [t for t in self.txs if "Zelle" in t.description and not t.duplicate]
        self.assertTrue(z and all("Memo: pizza night" in t.description for t in z))
        self.assertEqual(z[0].category, "Zelle / Venmo / Cash App")

    def test_debit_credit_columns_and_number_in_description(self):
        r = self.by_file["Credit Union/statement-2026-01.pdf"]
        got = {(t.description.split()[0], t.amount, t.is_credit) for t in r.transactions}
        self.assertIn(("CVS/PHARMACY", 18.40, False), got)
        self.assertIn(("REFUND", 25.00, True), got)
        self.assertIn(("DIVIDEND", 1.25, True), got)
        self.assertTrue(all(t.evidence == "column" for t in r.transactions))

    def test_day_month_dates(self):
        name = "UK Account/estatement-feb-2026.pdf"
        got = sorted(t.date.isoformat() for t in self.by_file[name].transactions)
        self.assertEqual(got, EXPECTED["files"][name]["dates"])
        self.assertEqual(self.by_file[name].info.date_order, "DMY")

    def test_password_protected(self):
        self.assertEqual(self.locked_before.status, "password")
        self.assertEqual(len(self.by_file[EXPECTED["locked"]["file"]].transactions), EXPECTED["locked"]["count"])


class Units(unittest.TestCase):
    def test_canonical_merchants(self):
        for raw, want in [("NETFLIX.COMNETFLIX.COMCA", "Netflix"), ("NETFLIX.COM NETFLIX.COM CA", "Netflix"),
                          ("HLU*HULUPLUS", "Hulu"), ("HULU 877-8244858 CA", "Hulu"),
                          ("CLAUDE.AI SUBSCRIPTIONANTHROPIC.COMCA", "Anthropic (Claude)"),
                          ("ANTHROPIC CLAUDE", "Anthropic (Claude)"), ("NTTA AUTOCHARGE", "NTTA (tolls)"),
                          ("Online Payment 1234 To Open House", "Open House"), ("UBER EATS PENDING", "Uber Eats"),
                          ("UBER *TRIP HELP.UBER.COM", "Uber"), ("AMAZON PRIME*AB12C", "Amazon Prime"),
                          ("AMZN Mktp US*2K3", "Amazon")]:
            with self.subTest(raw=raw):
                self.assertEqual(canonical(raw)[0], want)

    def test_amounts(self):
        self.assertEqual(parse_amount("(1,234.56)")[:2], (1234.56, True))
        self.assertEqual(parse_amount("45.00-")[:2], (45.0, True))
        self.assertEqual(parse_amount("-$12.00")[:2], (12.0, True))
        self.assertEqual(parse_amount("12.00", "CR")[:2], (12.0, True))
        self.assertEqual(parse_amount("$3,000.10")[:2], (3000.10, False))

    def test_dates(self):
        self.assertEqual(match_date_at("01/31 X", 0)[:3], (1, 31, None))
        self.assertEqual(match_date_at("31/01/2026 X", 0, "DMY")[:3], (1, 31, 2026))
        self.assertEqual(match_date_at("2026-01-31", 0)[:3], (1, 31, 2026))
        self.assertEqual(match_date_at("Jan 5, 2026", 0)[:3], (1, 5, 2026))
        self.assertEqual(match_date_at("05 Jan 2026", 0)[:3], (1, 5, 2026))
        self.assertIsNone(match_date_at("10.25% APR", 0))

    def test_generic_payment_words_depend_on_direction(self):
        c = Categorizer(tempfile.mkdtemp())
        name, brand = canonical("Online Payment 1234 To Open House")
        self.assertNotEqual(c.categorize("Online Payment 1234 To Open House", name, brand, False)[0],
                            "Transfers & Payments")
        self.assertEqual(c.categorize("PAYMENT THANK YOU-MOBILE", "x", None, True)[0], "Transfers & Payments")
        self.assertEqual(c.categorize("Payment To Chase Card Ending IN 1234", "x", None, False)[0],
                         "Transfers & Payments")


def tx(d, desc, amt, credit=False, kind="bank", account="Chk"):
    return Transaction(date=date.fromisoformat(d), description=desc, amount=amt, is_credit=credit,
                       source_file=account + ".pdf", kind=kind, account=account)


class MoneyInVsOut(unittest.TestCase):
    """Things that made 'you spend more than comes in' wrong."""

    def run_analysis(self, txs):
        Categorizer(tempfile.mkdtemp()).apply(txs)
        return analyze(txs)

    def test_unrecognised_deposits_still_count_as_money_in(self):
        a = self.run_analysis([
            tx("2026-01-02", "ACME CORP ACH CREDIT", 3000, credit=True),
            tx("2026-01-15", "ZELLE FROM JANE DOE", 500, credit=True),     # side job paid by Zelle
            tx("2026-01-20", "STRIPE TRANSFER ST-ABC123", 400, credit=True),  # unknown deposit
            tx("2026-01-05", "KROGER #123", 200)])
        self.assertAlmostEqual(a.compare["money_in"], 3900)
        self.assertAlmostEqual(a.income, 3000)

    def test_card_only_months_are_left_out_of_the_comparison(self):
        txs = [tx("2026-03-01", "ACME PAYROLL", 2000, credit=True), tx("2026-03-03", "KROGER", 500)]
        for m in ("2025-10", "2025-11", "2025-12", "2026-01", "2026-02"):   # card statements only
            txs.append(tx(m + "-10", "AMAZON.COM", 900, kind="card", account="Card"))
        txs.append(tx("2026-03-10", "AMAZON.COM", 900, kind="card", account="Card"))
        a = self.run_analysis(txs)
        self.assertEqual(a.compare["months"], ["2026-03"])
        self.assertAlmostEqual(a.compare["spent"], 1400)
        self.assertEqual(len(a.compare["left_out"]), 5)
        self.assertFalse(any(s.title == "You spent more than came in" for s in a.suggestions))

    def test_zelle_from_a_person_is_money_in(self):
        a = self.run_analysis([
            tx("2026-01-01", "ACME PAYROLL", 3000, credit=True),
            tx("2026-01-05", "Zelle Payment From Jane Doe 21345", 600, credit=True),
            tx("2026-01-06", "Zelle Transfer Conf# a1b2; Doe, Jane", 50, credit=True),
            tx("2026-01-03", "Online Payment 4432178 To Open House", 1200),
            tx("2026-01-04", "Online Transfer to SAV ...1234", 600)])   # same amount, own account: not her
        self.assertAlmostEqual(a.compare["money_in"], 3650)
        self.assertAlmostEqual(a.total_spent, 1200)

    def test_shared_bills_paid_back_lower_spending(self):
        tmp = tempfile.mkdtemp()
        c = Categorizer(tmp)
        c.set_override("Jane Doe", "Shared bills (paid back)")
        txs = [tx("2026-01-01", "ACME PAYROLL", 3000, credit=True),
               tx("2026-01-03", "Online Payment 4432178 To Open House", 1200),
               tx("2026-01-08", "TXU ENERGY", 150),
               tx("2026-01-05", "Zelle Payment From Jane Doe", 675, credit=True),
               tx("2026-01-09", "Zelle Payment To Jane Doe", 40)]   # money sent to her is still yours
        c.apply(txs)
        from spending_analyzer.categorize import infer_rent
        infer_rent(txs)
        a = analyze(txs)
        self.assertAlmostEqual(a.total_spent, 1200 + 150 + 40 - 675)
        self.assertAlmostEqual(a.compare["money_in"], 3000)
        self.assertEqual(next(t for t in txs if "To Jane" in t.description).category, "Zelle / Venmo / Cash App")

    def _linked(self, files):
        """files: list of (account_key, kind, [tx...]). Runs categorise + link like the app does."""
        from types import SimpleNamespace as NS
        from spending_analyzer.linking import link
        from spending_analyzer.parser import StatementInfo
        results = []
        for acct, kind, txs in files:
            bank = acct.split(" account")[0].split(" card")[0]
            info = StatementInfo(kind=kind, bank=bank, last4=acct[-4:])
            for t in txs:
                t.account, t.kind, t.source_file = info.account_key, kind, acct + ".pdf"
            results.append(NS(path=acct + ".pdf", info=info, transactions=txs, group="", duplicates_removed=0))
        all_txs = [t for r in results for t in r.transactions]
        Categorizer(tempfile.mkdtemp()).apply(all_txs)
        link(results)
        return analyze(all_txs)

    def test_savings_transfer_chase_to_capital_one_is_not_spending(self):
        chase = [tx("2026-01-01", "ACME CORP PAYROLL PPD", 4000, credit=True),
                 tx("2026-01-05", "CAPITAL ONE DES:TRANSFER ID:XXXXX4821 INDN:SMITH CO ID:9279744991 PPD", 1000),
                 tx("2026-01-20", "CAPITAL ONE DES:TRANSFER ID:XXXXX4821 INDN:SMITH", 300, credit=True),  # moved back
                 tx("2026-01-08", "CAPITAL ONE AUTO CARPAY", 350),                                     # real loan
                 tx("2026-01-09", "KROGER #622", 120)]
        a = self._linked([("Chase account \u20269876", "bank", chase)])
        self.assertAlmostEqual(a.total_spent, 470)            # loan + groceries only
        self.assertAlmostEqual(a.compare["money_in"], 4000)   # money moved back isn't new money

    def test_matched_when_both_banks_statements_are_present(self):
        chase = [tx("2026-01-01", "ACME CORP PAYROLL PPD", 4000, credit=True),
                 tx("2026-01-05", "CAPITAL ONE N.A. DES:CAPITALONE ID:123 PPD", 1000)]
        c1 = [tx("2026-01-06", "Deposit from JPMorgan Chase Bank, N.A.", 1000, credit=True),
              tx("2026-01-31", "Monthly Interest Paid", 3.10, credit=True)]
        for t in c1:
            t.account_type = "savings"   # read from the statement header ("360 Performance Savings")
        a = self._linked([("Chase account \u20269876", "bank", chase),
                          ("Capital One account \u20265555", "bank", c1)])
        self.assertAlmostEqual(a.total_spent, 0)
        self.assertAlmostEqual(a.compare["money_in"], 4003.10)
        self.assertAlmostEqual(sum(r["saved"] for r in a.cashflow), 1000)

    def test_partial_months_are_left_out(self):
        # checking statement ends Jan 15 (one paycheck), card statement covers all of January
        txs = [tx("2026-01-01", "ACME PAYROLL", 2000, credit=True), tx("2026-01-03", "KROGER", 100),
               tx("2026-01-15", "ACME PAYROLL", 2000, credit=True), tx("2026-01-20", "AMAZON", 300, kind="card"),
               tx("2026-02-01", "ACME PAYROLL", 2000, credit=True)]
        Categorizer(tempfile.mkdtemp()).apply(txs)
        cov = [("bank", date(2025, 12, 16), date(2026, 1, 15)), ("bank", date(2026, 1, 16), date(2026, 2, 15)),
               ("card", date(2026, 1, 1), date(2026, 1, 31))]
        a = analyze(txs, coverage=cov)
        self.assertEqual(a.compare["months"], ["2026-01"])
        cov_short = [("bank", date(2025, 12, 16), date(2026, 1, 15)), ("card", date(2026, 1, 1), date(2026, 1, 31))]
        a2 = analyze(txs, coverage=cov_short)
        self.assertNotIn("2026-01", (a2.compare or {}).get("months", []))

    def test_refunds_reduce_spending_instead_of_counting_as_money_in(self):
        a = self.run_analysis([
            tx("2026-01-03", "AMAZON.COM", 120, kind="card", account="Card"),
            tx("2026-01-09", "AMAZON.COM RETURN", 120, credit=True, kind="card", account="Card"),
            tx("2026-01-10", "TARGET", 50, kind="card", account="Card")])
        self.assertAlmostEqual(a.total_spent, 50)
        self.assertAlmostEqual(a.refunds, 120)

    def test_savings_and_investments_are_not_spending(self):
        a = self.run_analysis([tx("2026-01-02", "ROBINHOOD DES:FUNDS", 500), tx("2026-01-03", "KROGER", 80),
                               tx("2026-01-01", "PAYROLL", 2000, credit=True)])
        self.assertAlmostEqual(a.total_spent, 80)
        self.assertAlmostEqual(a.cashflow[0]["saved"], 500)

    def test_withdrawal_is_never_turned_into_income(self):
        t = tx("2026-01-02", "SECURITY DEPOSIT TO LANDLORD", 1500)
        self.run_analysis([t])
        self.assertFalse(t.is_credit)
        self.assertNotEqual(t.category, "Income")

    def test_misread_deposit_is_fixed_by_reconciliation(self):
        # unsigned amounts, no sections, no balance column: the deposit can only be told apart by
        # the statement's opening/closing balances
        raw = ["Checking Account Statement", "Beginning Balance $1,000.00",
               "01/02  ACME CORP 9912        3,000.00", "01/05  KROGER #123          200.00",
               "01/09  SHELL OIL            40.00", "Ending Balance $3,760.00"]
        lines = [Line(page=0, y=-i, raw=r) for i, r in enumerate(raw)]
        txs, info, _ = parse_statement(lines, "x.pdf", 2026)
        self.assertEqual(info.recon_status, "reconciled", info.recon_detail)
        acme = next(t for t in txs if "ACME" in t.description)
        self.assertTrue(acme.is_credit)


if __name__ == "__main__":
    unittest.main()
