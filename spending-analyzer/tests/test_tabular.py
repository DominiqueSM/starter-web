"""CSV / OFX bank downloads. Layouts follow what common US banks export; all data is synthetic."""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app")
sys.path[:0] = [os.path.join(APP, "vendor"), APP]

from spending_analyzer.categorize import Categorizer  # noqa: E402
from spending_analyzer.extract import process_folder  # noqa: E402
from spending_analyzer.insights import analyze  # noqa: E402
from spending_analyzer.linking import link  # noqa: E402
from spending_analyzer.tabular import parse_tabular  # noqa: E402


def write(folder, name, text):
    p = os.path.join(folder, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


def rows(txs):
    return [(t.date.isoformat(), t.description, t.amount, "in" if t.is_credit else "out") for t in txs]


class Formats(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def parse(self, name, text):
        txs, info, diags, method = parse_tabular(write(self.dir, name, text))
        return txs, info, diags

    def test_chase_card_purchases_negative(self):
        txs, info, _ = self.parse("Chase1234_Activity20260101_20260131_20260201.CSV",
                                  "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
                                  "01/28/2026,01/29/2026,NETFLIX.COM,Entertainment,Sale,-21.64,\n"
                                  "01/20/2026,01/20/2026,Payment Thank You-Mobile,,Payment,500.00,\n"
                                  "01/15/2026,01/16/2026,AMAZON MKTPL*AB12,Shopping,Return,12.99,\n"
                                  "01/05/2026,01/06/2026,TOM THUMB #2512,Groceries,Sale,-84.10,\n")
        self.assertEqual((info.kind, info.bank, info.last4), ("card", "Chase", "1234"))
        self.assertEqual(rows(txs), [("2026-01-28", "NETFLIX.COM", 21.64, "out"),
                                     ("2026-01-20", "Payment Thank You-Mobile", 500.0, "in"),
                                     ("2026-01-15", "AMAZON MKTPL*AB12", 12.99, "in"),
                                     ("2026-01-05", "TOM THUMB #2512", 84.10, "out")])

    def test_amex_purchases_positive(self):
        txs, info, _ = self.parse("activity.csv",
                                  "Date,Description,Card Member,Account #,Amount\n"
                                  "01/03/2026,UBER EATS,J SMITH,-41009,31.20\n"
                                  "01/09/2026,DELTA AIR LINES,J SMITH,-41009,412.80\n"
                                  "01/12/2026,AUTOPAY PAYMENT - THANK YOU,J SMITH,-41009,-300.00\n")
        self.assertEqual(info.kind, "card")
        self.assertEqual(info.last4, "1009")
        self.assertEqual([r[3] for r in rows(txs)], ["out", "out", "in"])

    def test_capital_one_debit_credit_columns(self):
        txs, info, _ = self.parse("2026-01-31_transaction_download.csv",
                                  "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit\n"
                                  "2026-01-30,2026-01-31,5555,SPOTIFY USA,Entertainment,11.99,\n"
                                  "2026-01-22,2026-01-22,5555,CAPITAL ONE MOBILE PYMT,Payment/Credit,,250.00\n")
        self.assertEqual((info.kind, info.last4), ("card", "5555"))
        self.assertEqual(rows(txs), [("2026-01-30", "SPOTIFY USA", 11.99, "out"),
                                     ("2026-01-22", "CAPITAL ONE MOBILE PYMT", 250.0, "in")])
        self.assertTrue(all(t.evidence == "column" for t in txs))

    def test_bank_of_america_preamble_and_running_balance(self):
        txs, info, diags = self.parse("stmt.csv",
                                      "Description,,Summary Amt.\n"
                                      "Beginning balance as of 01/01/2026,,\"1,000.00\"\n"
                                      "Total credits,,\"3,000.00\"\n"
                                      "\n"
                                      "Date,Description,Amount,Running Bal.\n"
                                      "01/01/2026,Beginning balance as of 01/01/2026,,\"1,000.00\"\n"
                                      "01/02/2026,ACME CORP DES:PAYROLL,\"3,000.00\",\"4,000.00\"\n"
                                      "01/05/2026,KROGER #622,-120.50,\"3,879.50\"\n"
                                      "01/09/2026,OPENHOUSETEXAS DES:WEB PMTS ID:7YR06G,\"-2,490.00\",\"1,389.50\"\n")
        self.assertEqual(info.kind, "bank")
        self.assertEqual(rows(txs), [("2026-01-02", "ACME CORP DES:PAYROLL", 3000.0, "in"),
                                     ("2026-01-05", "KROGER #622", 120.5, "out"),
                                     ("2026-01-09", "OPENHOUSETEXAS DES:WEB PMTS ID:7YR06G", 2490.0, "out")])
        self.assertEqual(info.recon_status, "unverified")  # only 2 balance steps: too few to call verified
        self.assertTrue(any(d.status == "header" for d in diags))

    def test_wells_fargo_no_header(self):
        txs, _, _ = self.parse("Checking1.csv",
                               '"01/05/2026","-45.00","*","","KROGER #622 DALLAS TX"\n'
                               '"01/06/2026","1500.00","*","","ACME PAYROLL"\n'
                               '"01/07/2026","-9.99","*","","SPOTIFY USA"\n')
        self.assertEqual(rows(txs), [("2026-01-05", "KROGER #622 DALLAS TX", 45.0, "out"),
                                     ("2026-01-06", "ACME PAYROLL", 1500.0, "in"),
                                     ("2026-01-07", "SPOTIFY USA", 9.99, "out")])

    def test_chase_checking_details_column_and_pending(self):
        txs, info, diags = self.parse("Chase9876_Activity_20260131.CSV",
                                      "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
                                      "DEBIT,01/30/2026,CAPITAL ONE DES:TRANSFER,-500.00,ACH_DEBIT,2100.00,,\n"
                                      "CREDIT,01/15/2026,ACME CORP PAYROLL,3250.00,ACH_CREDIT,2600.00,,\n"
                                      "DEBIT,01/10/2026,KROGER #622,-86.25,DEBIT_CARD,-650.00,,\n")
        self.assertEqual((info.kind, info.last4, info.bank), ("bank", "9876", "Chase"))
        self.assertEqual([r[3] for r in rows(txs)], ["out", "in", "out"])
        txs2, _, diags2 = self.parse("pend.csv", "Date,Description,Amount,Status\n"
                                                 "01/30/2026,STARBUCKS,-5.25,Pending\n01/29/2026,KROGER,-40.00,Posted\n")
        self.assertEqual(len(txs2), 1)
        self.assertTrue(any("pending" in d.reason for d in diags2))

    def test_ofx_bank_and_card(self):
        bank = ("OFXHEADER:100\nDATA:OFXSGML\n<OFX><SIGNONMSGSRSV1><SONRS><FI><ORG>Capital One</ORG></FI></SONRS>"
                "</SIGNONMSGSRSV1><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD<BANKACCTFROM><BANKID>031176110"
                "<ACCTID>36001234<ACCTTYPE>SAVINGS</BANKACCTFROM><BANKTRANLIST><DTSTART>20260101<DTEND>20260131"
                "<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260106120000<TRNAMT>1000.00<FITID>A1<NAME>Deposit from JPMorgan Chase"
                "</STMTTRN><STMTTRN><TRNTYPE>INT<DTPOSTED>20260131<TRNAMT>3.10<FITID>A2<NAME>Monthly Interest Paid</STMTTRN>"
                "<STMTTRN><TRNTYPE>INT<DTPOSTED>20260131<TRNAMT>3.10<FITID>A2<NAME>Monthly Interest Paid</STMTTRN>"
                "</BANKTRANLIST><LEDGERBAL><BALAMT>5003.10<DTASOF>20260131</LEDGERBAL></STMTRS></STMTTRNRS>"
                "</BANKMSGSRSV1></OFX>")
        txs, info, diags = self.parse("export.qfx", bank)
        self.assertEqual((info.kind, info.bank, info.last4, info.account_type), ("bank", "Capital One", "1234", "savings"))
        self.assertEqual(len(txs), 2)                       # FITID A2 listed twice -> once
        self.assertEqual(info.closing_balance, 5003.10)
        card = ("<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS><CCACCTFROM><ACCTID>4111111111114321</CCACCTFROM>"
                "<BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260110<TRNAMT>-62.00<FITID>9<NAME>PATILLA BARBERSHOP"
                "</STMTTRN><STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260120<TRNAMT>200.00<FITID>10<NAME>PAYMENT THANK YOU"
                "</STMTTRN></BANKTRANLIST></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>")
        txs, info, _ = self.parse("card.ofx", card)
        self.assertEqual((info.kind, info.last4), ("card", "4321"))
        self.assertEqual([r[3] for r in rows(txs)], ["out", "in"])


class MixedWithPdf(unittest.TestCase):
    def test_csv_export_overlapping_a_pdf_statement_is_not_double_counted(self):
        """A card's CSV download dated by posting date (a day later) next to the PDF statement of the same card."""
        fixtures = os.path.join(HERE, "fixtures", "Chase Freedom")
        folder = tempfile.mkdtemp()
        os.makedirs(os.path.join(folder, "Card"))
        pdf = "20260113-statements-1234.pdf"
        shutil.copy(os.path.join(fixtures, pdf), os.path.join(folder, "Card", pdf))
        only_pdf = process_folder(folder)
        pdf_txs = only_pdf[0].transactions
        lines = ["Post Date,Description,Type,Amount"]
        for t in pdf_txs:
            amt = t.amount if t.is_credit else -t.amount
            lines.append(f"{(t.date + timedelta(days=1)):%m/%d/%Y},{t.description},"
                         f"{'Payment' if t.is_credit else 'Sale'},{amt:.2f}")
        write(folder, "Card/Chase1234_Activity.CSV", "\n".join(lines) + "\n")

        def total(res):
            txs = [t for r in res for t in r.transactions]
            for r in res:
                for t in r.transactions:
                    t.group = "Card"
                r.group = "Card"
            Categorizer(tempfile.mkdtemp()).apply(txs)
            stats = link(res)
            return analyze(txs).total_spent, stats

        base, _ = total(only_pdf)
        both, stats = total(process_folder(folder))
        self.assertEqual(stats["duplicates"], len(pdf_txs))
        self.assertAlmostEqual(both, base, places=2)


if __name__ == "__main__":
    unittest.main()
