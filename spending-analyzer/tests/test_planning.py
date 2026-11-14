"""Budgets, tags and debt payoff."""
import json
import math
import os
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app")
sys.path[:0] = [os.path.join(APP, "vendor"), APP]

from spending_analyzer.categorize import Categorizer  # noqa: E402
from spending_analyzer.extract import process_folder  # noqa: E402
from spending_analyzer.insights import analyze  # noqa: E402
from spending_analyzer.linking import link  # noqa: E402
from spending_analyzer.parser import Transaction, _card_terms  # noqa: E402
from spending_analyzer.planning import (Debt, apply_tags, budget_rows, debts_from_statements,  # noqa: E402
                                        left_to_spend, over_budget, simulate, spending_by_tag, suggest_budgets)


def tx(d, desc, amt, credit=False, kind="card"):
    return Transaction(date=date.fromisoformat(d), description=desc, amount=amt, is_credit=credit,
                       source_file=f"{kind}-{d[:7]}.pdf", kind=kind, account=kind)


def spending():
    rows = []
    for m, dining in (("01", 300), ("02", 250), ("03", 410), ("04", 120)):
        rows += [tx(f"2026-{m}-05", "TST* PINK DOOR", dining), tx(f"2026-{m}-07", "KROGER #622", 400),
                 tx(f"2026-{m}-28", "NETFLIX.COM", 21.64)]
    rows.append(tx("2026-04-10", "BOOTH PURCHASE ETSY", 60))
    Categorizer(tempfile.mkdtemp()).apply(rows)
    for i, t in enumerate(rows):
        t.uid = f"u{i}"
    return rows


class Budgets(unittest.TestCase):
    def test_suggested_budgets_use_median_of_recent_complete_months(self):
        a = analyze(spending())                 # card-only: April (last month) counts as incomplete
        b = suggest_budgets(a)
        self.assertEqual(b["Dining Out"], 300.0)        # median(300, 250, 410) = 300
        self.assertEqual(b["Groceries"], 400.0)
        self.assertEqual(b["Streaming & Subscriptions"], 30.0)   # 21.64 rounded up to the next $10

    def test_budget_rows_and_over_budget(self):
        a = analyze(spending())
        rows = {r.category: r for r in budget_rows(a, {"Dining Out": 300, "Groceries": 350}, "2026-03")}
        self.assertAlmostEqual(rows["Dining Out"].spent, 410)
        self.assertAlmostEqual(rows["Dining Out"].remaining, -110)
        self.assertAlmostEqual(rows["Dining Out"].typical, 275)  # median of Jan, Feb
        over = {r.category for r in over_budget(a, {"Dining Out": 300, "Groceries": 450}, "2026-03")}
        self.assertEqual(over, {"Dining Out"})
        a2 = analyze(spending(), budgets={"Dining Out": 300})
        self.assertEqual(a2.suggestions[0].title, "Over budget in 2026-03")

    def test_left_to_spend_only_for_current_month(self):
        a = analyze(spending())
        rows = budget_rows(a, {"Dining Out": 300, "Groceries": 500}, "2026-04")
        left, per_day, days = left_to_spend(rows, "2026-04", date(2026, 4, 21))
        self.assertAlmostEqual(left, (300 - 120) + (500 - 400))
        self.assertEqual(days, 10)
        self.assertAlmostEqual(per_day, 28.0)
        self.assertIsNone(left_to_spend(rows, "2026-04", date(2026, 5, 2)))


class Tags(unittest.TestCase):
    def test_tag_rules(self):
        rows = spending()
        apply_tags(rows, [{"by": "company", "value": "Pink Door", "tag": "date night"},
                          {"by": "contains", "value": "etsy", "tag": "gifts"},
                          {"by": "tx", "value": "u1", "tag": "gifts"}])
        a = analyze(rows)
        tags = {r["tag"]: r for r in spending_by_tag(a, rows)}
        self.assertAlmostEqual(tags["date night"]["total"], 300 + 250 + 410 + 120)
        self.assertEqual(tags["date night"]["count"], 4)
        self.assertAlmostEqual(tags["gifts"]["total"], 60 + 400)   # Etsy + the one Kroger row tagged by hand


class DebtPayoff(unittest.TestCase):
    def test_single_debt_matches_the_loan_formula(self):
        B, apr, P = 5000.0, 24.0, 200.0
        r = apr / 1200
        expected = math.ceil(-math.log(1 - r * B / P) / math.log(1 + r))
        plan = simulate([Debt("Card", B, apr, P)])
        self.assertEqual(plan.months, expected)
        self.assertGreater(plan.interest, 0)

    def test_zero_interest(self):
        plan = simulate([Debt("Loan", 1000, 0, 100)])
        self.assertEqual((plan.months, plan.interest), (10, 0))

    def test_extra_payment_saves_time_and_interest(self):
        debts = [Debt("A", 3000, 26.99, 90, key="A"), Debt("B", 1200, 18.0, 40, key="B"),
                 Debt("Car", 9000, 6.5, 300, key="Car")]
        base = simulate(debts)
        plan = simulate(debts, extra=250)
        self.assertLess(plan.months, base.months)
        self.assertLess(plan.interest, base.interest)

    def test_avalanche_vs_snowball_order(self):
        debts = [Debt("Big high", 4000, 29.0, 100, key="hi"), Debt("Small low", 500, 9.0, 25, key="lo")]
        self.assertEqual(simulate(debts, 300, "avalanche").order[0], "hi")
        self.assertEqual(simulate(debts, 300, "snowball").order[0], "lo")
        self.assertLessEqual(simulate(debts, 300, "avalanche").interest, simulate(debts, 300, "snowball").interest)

    def test_payment_below_interest_never_pays_off(self):
        plan = simulate([Debt("Bad", 10000, 30.0, 200, key="bad")], max_months=120)
        self.assertEqual(plan.never, ["bad"])

    def test_card_terms_and_debts_from_statements(self):
        self.assertEqual(_card_terms(["Annual Percentage Rate (APR)", "Purchases   24.99%(v)(d)",
                                      "Minimum Payment Due: $40.00"]), (24.99, 40.0))
        res = process_folder(os.path.join(HERE, "fixtures"))
        txs = [t for r in res for t in r.transactions]
        Categorizer(tempfile.mkdtemp()).apply(txs)
        link(res)
        debts = debts_from_statements(res)
        self.assertEqual([d.name for d in debts], ["Chase card …1234"])
        d = debts[0]
        self.assertEqual((d.minimum, d.source), (40.0, "statement"))
        self.assertFalse(d.include)          # the fixture card is paid in full every month
        self.assertIn("paid in full", d.note)


class Backup(unittest.TestCase):
    def test_round_trip(self):
        from spending_analyzer import backup
        a, b = Categorizer(tempfile.mkdtemp()), Categorizer(tempfile.mkdtemp())
        a.set_override("Pink Door", "Date Night")
        a.add_rule("OPENHOUSETEXAS", "Housing")
        settings = {"budgets": {"Dining Out": 300}, "tag_rules": [{"by": "contains", "value": "ETSY", "tag": "gifts"}],
                    "debts": {"you:Car": {"user": True, "name": "Car", "balance": 9000}}, "geometry": "1x1",
                    "folder": "/x"}
        data = json.loads(json.dumps(backup.make_backup(settings, a)))
        self.assertIsNone(backup.validate(data))
        self.assertNotIn("folder", data["settings"])
        mine = {"geometry": "2x2", "folder": "/mine", "budgets": {"Groceries": 1}}
        backup.restore(data, mine, b)
        self.assertEqual(mine["budgets"], {"Dining Out": 300})
        self.assertEqual(mine["folder"], "/mine")
        self.assertEqual(b.overrides, {"Pink Door": "Date Night"})
        self.assertEqual(Categorizer(b.data_dir).user_rules[0]["contains"], "OPENHOUSETEXAS")
        self.assertIsNotNone(backup.validate({"app": "other"}))


if __name__ == "__main__":
    unittest.main()
