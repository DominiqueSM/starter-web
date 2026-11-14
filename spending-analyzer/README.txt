SPENDING ANALYZER  (v2.0, works 100% offline)
=============================================

Reads the PDF bank and credit-card statements in a folder and shows:
  * how much you really spend, per month and per category
  * subscriptions, bills and loans, one line per company (all the different ways
    "Netflix" can appear on a statement count as one)
  * fees and interest, possible duplicate charges, recurring charges that went up
  * a ranked list of "what to cut back on" with estimated savings and a confidence level
  * a self-check for every statement: do the transactions add up to the balances printed on it?
  * export to CSV, or an HTML report you can print or keep

PRIVACY: the app never connects to the internet; it blocks network access inside its own
process. Your PDFs are only read. Nothing is uploaded or changed.


1. ONE-TIME SETUP: install Python (free)
----------------------------------------
You need Python 3.10 or newer from python.org.
  Windows: run the installer and TICK "Add python.exe to PATH".
  macOS:   run the python.org installer (it includes everything needed).
  Linux:   sudo apt install python3 python3-tk   (or your distro's equivalent)
No other installs: the PDF reader is bundled in app/vendor.

(No Python? Standalone builds for Windows/macOS/Linux are produced automatically on GitHub:
repository > Actions tab > "Spending Analyzer - test and build" > latest run > Artifacts.)


2. START THE APP
----------------
  Windows: double-click  "Start Spending Analyzer (Windows).bat"
  macOS:   double-click  "Start Spending Analyzer (Mac).command"
           (first time: right-click > Open > Open, because the file is unsigned. If it says
            permission denied, run in Terminal: chmod +x "/path/to/Start Spending Analyzer (Mac).command")
  Linux:   ./start-linux.sh            or from a terminal here:  python3 app/main.py


3. USE IT
---------
  1. Click "Choose folder..." (bottom left) and pick the folder with your statement PDFs.
     Put each card/account in its own subfolder if you like; subfolders are read too.
  2. The analysis runs straight away (click Analyze to run it again).
  3. Pages (left side):
       Overview         totals, where the money goes, monthly chart (hover for details)
       Cut back         ranked suggestions with estimated savings and confidence
       Transactions     everything found; search, filter, fix categories
       Recurring        subscriptions / bills & loans / regular spending, one line per company
       By folder        each subfolder side by side
       Files & checks   what was read from each PDF, whether it adds up, and a
                        line-by-line preview showing exactly what was read or skipped and why
  Try it first with the "sample-statements (fake data)" folder (the locked sample's password is: secret).


HOW DOUBLE COUNTING IS AVOIDED
------------------------------
  * Paying a credit card from checking is not spending (the card purchases are). Card payments
    are recognised by their wording ("Payment to Chase card ending 1234", "AMEX EPAYMENT"...) AND
    by matching: a checking withdrawal with the same amount as a payment received on one of your
    card statements a few days later is marked as a transfer. Add your card statements AND your
    checking statements for the best results.
  * If two statements of the same account overlap (e.g. a monthly statement plus a custom date-range
    download), transactions that appear in both are counted once.
  * The "Cut back" page warns about any large payments to card companies that are still counted.
  * Money sent to people (Zelle/Venmo/Cash App) counts as spending; money received doesn't count
    as income.


FIXING THINGS (the app remembers your fixes)
--------------------------------------------
  * Wrong category: double-click the transaction (or select several > "Set category...").
    Leave "Use this for every transaction from these companies" ticked to apply it everywhere.
    In the Category column:  ?  = broad guess,  * = your choice,  <-> = matched transfer.
  * Not real spending (e.g. moving money between your own accounts): select > "Exclude".
  * Refund shown as spending, or the reverse: select > "Flip in/out".
  * Dates read wrong (e.g. a UK statement): bottom-left menu > "Dates: DD/MM".


SELF-CHECK RESULTS (Files & checks page)
----------------------------------------
  Adds up          opening balance +/- every transaction = closing balance. Reliable.
  Balance checked  each row was verified against the statement's running-balance column.
  Doesn't add up   something was missed or misread: open the line preview to see which lines
                   were skipped (orange) and why.
  Not checkable    no balances printed (e.g. an activity download).


TIPS AND LIMITS
---------------
  * Use PDFs downloaded from your bank's website. Scanned/photographed statements have no text
    and can't be read (no OCR).
  * Password-protected PDFs: the app asks for the password (kept in memory only). Some banks use
    AES encryption, which needs an extra package; if so, save a copy without the password.
  * Savings figures are estimates based on realistic reductions (e.g. eating out 30% less).
  * "Probably rent or mortgage": the same large amount to the same unknown payee every month is
    guessed as Housing (marked with ?). Correct it if it's something else.

Your settings, choices and a cache of read statements are in the ".spending_analyzer" folder in
your home folder. app.log there records errors. category_rules.json holds the keyword list used
for categories (edit with any text editor; delete it to restore defaults).

FOR DEVELOPERS: tests live in tests/ (python -m unittest discover -s tests). The fixture PDFs
mimic real statement layouts; regenerate with tests/make_fixtures.py (needs reportlab).
Bundled third-party code: pypdf 7.1.0 (BSD-3-Clause) - see app/vendor/VERSIONS.txt.
