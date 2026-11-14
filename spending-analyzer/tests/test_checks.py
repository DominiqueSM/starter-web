"""Needs review, missing statements, savings rate."""
import os
import sys
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace as NS

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app")
sys.path[:0] = [os.path.join(APP, "vendor"), APP]

from spending_analyzer.categorize import Categorizer, infer_rent  # noqa: E402
from spending_analyzer.checks import missing_statements, needs_review  # noqa: E402
from spending_analyzer.insights import analyze  # noqa: E402
from spending_analyzer.parser import StatementInfo, Transaction  # noqa: E402


def tx(d, desc, amt, credit=False, kind="bank", src="chk.pdf"):
    return Transaction(date=date.fromisoformat(d), description=desc, amount=amt, is_credit=credit,
                       source_file=src, kind=kind, account=kind)


def fr(name, start, end, kind="card", last4="1234", method="positioned"):
    info = StatementInfo(kind=kind, bank="Chase", last4=last4,
                         period_start=date.fromisoformat(start) if start else None, period_end=date.fromisoformat(end))
    return NS(path=name, status="ok", method=method, group="", info=info,
              transactions=[tx(end, "X", 1.0, kind=kind, src=name)])


class NeedsReview(unittest.TestCase):
    def test_grouped_by_company_with_reasons(self):
        c = Categorizer(tempfile.mkdtemp())
        txs = [tx(f"2026-0{m}-0{d}", "SQUIRREL DEN 4411", 12.5, kind="card", src=f"c{m}.pdf")
               for m in (1, 2) for d in (3, 5)]                                    # unknown company x4
        txs += [tx(f"2026-0{m}-01", "OPENHOUSETEXAS 7YR06G", 2490, src=f"k{m}.pdf") for m in (1, 2, 3)]
        txs += [tx("2026-01-20", "CHASE EPAY 0012", 650.0, src="k1.pdf"),        # card company, unmatched
                tx("2026-01-21", "SHOP N SAVE", 40.0, kind="card", src="c1.pdf"),   # broad word
                tx("2026-01-22", "NETFLIX.COM", 15.49, kind="card", src="c1.pdf")]  # sure: not listed
        c.apply(txs)
        infer_rent(txs)
        items = {(i.merchant, i.reason): i for i in needs_review(txs)}
        self.assertEqual(items[("Squirrel Den", "No category")].count, 4)
        self.assertEqual(items[("Openhousetexas", "Looks like rent or a mortgage")].proposed, "Housing")
        self.assertEqual(items[("Chase", "Possible card payment counted as spending")].proposed,
                         "Transfers & Payments")
        self.assertIn(("Shop N", "Guessed from a broad word"), items)
        self.assertFalse(any(m == "Netflix" for m, _ in items))
        # approving = remembering the company's category -> it leaves the queue
        c.set_override("Openhousetexas", "Housing")
        c.apply(txs)
        self.assertFalse(any(i.merchant == "Openhousetexas" for i in needs_review(txs)))


class MissingStatements(unittest.TestCase):
    def test_gap_between_periods(self):
        gaps = missing_statements([fr("jan.pdf", "2025-12-14", "2026-01-13"), fr("feb.pdf", "2026-01-14", "2026-02-13"),
                                   fr("apr.pdf", "2026-03-14", "2026-04-13")])
        self.assertEqual(len(gaps), 1)
        g = gaps[0]
        self.assertEqual((g.start, g.end, g.months), (date(2026, 2, 14), date(2026, 3, 13), 1))
        self.assertEqual((g.before, g.after), ("feb.pdf", "apr.pdf"))

    def test_only_closing_dates(self):
        gaps = missing_statements([fr("a.pdf", None, "2026-01-28"), fr("b.pdf", None, "2026-02-28"),
                                   fr("c.pdf", None, "2026-05-28")])
        self.assertEqual([g.months for g in gaps], [2])

    def test_no_gap_and_accounts_kept_apart(self):
        self.assertEqual(missing_statements([fr("a.pdf", "2026-01-01", "2026-01-31"),
                                             fr("b.pdf", "2026-02-01", "2026-02-28"),
                                             fr("c.pdf", "2026-04-01", "2026-04-30", last4="9999")]), [])

    def test_fixture_folder_has_no_gaps(self):
        from spending_analyzer.extract import process_folder
        self.assertEqual(missing_statements(process_folder(os.path.join(HERE, "fixtures"))), [])


class SavingsRate(unittest.TestCase):
    def test_last_three_full_months(self):
        txs = []
        for m, spent in (("01", 3000), ("02", 3500), ("03", 4000), ("04", 2000)):
            txs += [tx(f"2026-{m}-01", "ACME PAYROLL", 5000, credit=True, src=f"{m}.pdf"),
                    tx(f"2026-{m}-05", "KROGER", spent, src=f"{m}.pdf")]
        Categorizer(tempfile.mkdtemp()).apply(txs)
        a = analyze(txs)
        self.assertEqual(a.savings["months"], ["2026-02", "2026-03", "2026-04"])
        self.assertAlmostEqual(a.savings["rate"], (15000 - 9500) / 15000)
        self.assertAlmostEqual(next(r for r in a.cashflow if r["month"] == "2026-01")["rate"], 0.4)


class Coverage(unittest.TestCase):
    def test_month_missing_one_accounts_statement_is_not_compared(self):
        txs = []
        for m in ("01", "02", "03"):
            if m != "02":   # checking statement for February is missing
                txs.append(tx(f"2026-{m}-01", "ACME PAYROLL", 5000, credit=True, src=f"chk{m}.pdf"))
            txs.append(tx(f"2026-{m}-09", "DIVIDEND", 2, credit=True, src=f"sav{m}.pdf"))
            txs.append(tx(f"2026-{m}-05", "KROGER", 3000, src=f"chk{m}.pdf" if m != "02" else "sav02.pdf"))
        Categorizer(tempfile.mkdtemp()).apply(txs)
        cov = [("bank", date(2026, 1, 1), date(2026, 1, 31), "chk"), ("bank", date(2026, 3, 1), date(2026, 3, 31), "chk")]
        cov += [("bank", date(2026, m, 1), date(2026, m, 28), "sav") for m in (1, 2, 3)]
        a = analyze(txs, coverage=cov)
        self.assertEqual(a.compare["months"], ["2026-01", "2026-03"])


class OwnAccounts(unittest.TestCase):
    """Checking -> Chase savings twice a month on payday, then Chase savings -> Capital One savings."""

    def build(self, with_c1=True):
        from spending_analyzer.insights import summarize_groups
        from spending_analyzer.linking import link

        def acct(group, bank, last4, atype, rows):
            info = StatementInfo(kind="bank", bank=bank, last4=last4, account_type=atype,
                                 period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
            txs = []
            for d, desc, amt, credit in rows:
                t = tx(d, desc, amt, credit=credit, src=f"{group}.pdf")
                t.account, t.account_type, t.group = info.account_key, atype, group
                txs.append(t)
            return NS(path=f"{group}.pdf", status="ok", method="positioned", group=group, info=info,
                      transactions=txs, duplicates_removed=0)
        res = [acct("chase_checking", "Chase", "1234", "checking", [
                   ("2026-01-01", "ACME CORP PAYROLL PPD", 3000, True), ("2026-01-15", "ACME CORP PAYROLL PPD", 3000, True),
                   ("2026-01-01", "Online Transfer To Sav ...5678 Transaction#: 111", 500, False),
                   ("2026-01-15", "Online Transfer To Sav ...5678 Transaction#: 222", 500, False),
                   ("2026-01-09", "KROGER #622", 200, False)]),
               acct("chase_savings", "Chase", "5678", "savings", [
                   ("2026-01-01", "Online Transfer From Chk ...1234 Transaction#: 111", 500, True),
                   ("2026-01-15", "Online Transfer From Chk ...1234 Transaction#: 222", 500, True),
                   ("2026-01-20", "CAPITAL ONE DES:TRANSFER ID:999", 300, False)])]
        if with_c1:
            res.append(acct("c1_savings", "Capital One", "4444", "savings", [
                ("2026-01-21", "Deposit from JPMorgan Chase Bank, N.A.", 300, True),
                ("2026-01-31", "Monthly Interest Paid", 2.0, True)]))
        txs = [t for r in res for t in r.transactions]
        Categorizer(tempfile.mkdtemp()).apply(txs)
        link(res)
        return analyze(txs), {g["name"]: g for g in summarize_groups(txs, res)}

    def test_savings_folder_shows_money_moved_in(self):
        a, groups = self.build()
        self.assertAlmostEqual(groups["chase_savings"]["moved_in"], 1000)
        self.assertAlmostEqual(groups["chase_savings"]["moved_out"], 300)
        self.assertAlmostEqual(groups["c1_savings"]["moved_in"], 300)
        self.assertAlmostEqual(groups["chase_checking"]["moved_out"], 1000)

    def test_overall_totals_and_saving_counted_once(self):
        a, _ = self.build()
        self.assertAlmostEqual(a.total_spent, 200)
        self.assertAlmostEqual(a.money_in, 6002)                         # pay + interest, no transfers
        self.assertAlmostEqual(sum(r["saved"] for r in a.cashflow), 1000)  # not 1300

    def test_checking_only_still_counts_as_saved(self):
        a, _ = self.build(with_c1=False)
        self.assertAlmostEqual(sum(r["saved"] for r in a.cashflow), 1000)


if __name__ == "__main__":
    unittest.main()
