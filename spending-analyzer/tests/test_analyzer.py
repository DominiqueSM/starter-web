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
from spending_analyzer.parser import match_date_at, parse_amount  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
