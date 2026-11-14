SPENDING ANALYZER  (v3.0, works 100% offline)
=============================================

Reads the bank and credit-card statements in a folder (PDF statements, and CSV or OFX/QFX
downloads from your bank's website) and shows:
  * how much you really spend, per month and per category
  * subscriptions, bills and loans, one line per company (all the different ways
    "Netflix" can appear on a statement count as one)
  * fees and interest, possible duplicate charges, recurring charges that went up
  * a ranked list of "what to cut back on" with estimated savings and a confidence level
  * a self-check for every statement: do the transactions add up to the balances printed on it?
  * monthly budgets per category, tags across categories, and a debt payoff planner
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
       Cash flow        money in vs. spent, month by month, and exactly what was counted. Two
                        savings rates over the last 3 full months: of ALL money in, and of your
                        JOB PAY only. Pay is recognised from payroll wording (PAYROLL, DIRECT DEP,
                        SALARY, ADP, Gusto...); under "Where money in came from" select a payer
                        and click "Job income: yes / no" to change what counts (remembered).
                        The job-pay rate treats money people send you (Zelle, Venmo, Cash App,
                        e.g. a partner's share of the bills) as paying back shared costs, so it
                        shows what you keep from your paycheck after your share of expenses.
                        and what wasn't (card payments, transfers, savings). Start here if a
                        total looks wrong.
       Cut back         ranked suggestions with estimated savings and confidence
       Needs review     what the app wasn't sure about, one line per company (broad guesses,
                        no category, likely rent, money moved to another bank, possible card
                        payments). Approve confirms the category shown and the app remembers it;
                        Set category picks another. The sidebar shows how many are left.
       Budgets          a monthly limit per category: spent vs. budget, left to spend (and per
                        day for the current month), plus spending by tag
       Transactions     everything found; search, filter by category or tag, fix categories, tag
       Recurring        subscriptions / bills & loans / regular spending, one line per company
       Debt payoff      when you'll be debt-free, and what paying extra each month saves
       By folder        each subfolder side by side
       Files & checks   what was read from each file, whether it adds up, a line-by-line
                        preview showing what was read or skipped and why, and a warning when
                        statements are missing (e.g. no Chase card statement for March)
       Rules & backup   everything you've taught the app (categories, rules, tags, exclusions...)
                        with Delete / Change category, and Back up / Restore
  Try it first with the "sample-statements (fake data)" folder (the locked sample's password is: secret).


CSV AND OFX/QFX DOWNLOADS
-------------------------
Most banks let you download your transactions as CSV, and many as OFX/QFX ("Quicken"/"Money").
These are read more reliably than PDFs; put them in the same folder (or subfolders).
  * CSV columns are recognised automatically (date, description, amount or separate debit/credit,
    balance, type), including files with summary lines above the table and files with no header.
  * Money in/out: from debit/credit columns, a DEBIT/CREDIT or Sale/Payment column, the running
    balance, or else the sign most rows use (purchases outnumber payments).
  * Pending transactions are skipped; import them once they post. Every skipped row is listed with
    the reason on Files & checks.
  * The bank and last 4 digits come from the file name (e.g. Chase1234_Activity...csv) or a card /
    account column. A CSV and a PDF statement of the same account can sit side by side: rows in
    both are counted once, even when the CSV uses the posting date (up to 3 days later).


BUDGETS, TAGS AND DEBT PAYOFF
-----------------------------
  * Budgets: "Suggest budgets" fills in your typical month per category (the median of recent full
    months), then lower the ones you want to cut. Double-click a category to change its budget.
    Going over a budget shows up at the top of the Cut back page.
  * Tags: select transactions > "Tag..." to label them across categories (e.g. "alcohol", "work",
    "vacation 2026"), for a company, a description that contains some text, or only the selection.
    See totals per tag on the Budgets page; filter by tag on Transactions.
  * Debt payoff: cards come in from your newest statement (balance, APR and minimum payment are
    read from it); add loans with "Add a debt...". Type an extra monthly amount and pick
    Avalanche (highest rate first: least interest) or Snowball (smallest balance first: quick
    wins). It shows your debt-free month and how much sooner, and how much less interest, paying
    extra gets you. Cards you pay in full every month cost no interest and are left out.


BACKUPS
-------
Rules & backup > "Back up..." saves every choice you've made (categories, rules, tags, budgets,
debts, exclusions, not-a-duplicate marks) to one file. "Restore from backup..." loads it, e.g. on
a new computer. Your statement files aren't in the backup; keep those yourself.


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
  * PDFs that aren't bank or card statements (hotel bills/folios, receipts, invoices, loan
    statements with payment history, pay stubs) are skipped: their charges are already on your
    statements. They're listed on Files & checks as "Not a statement"; select one and click
    "Include / skip file" if it really is a statement.
  * A charge only counts as recurring when the same amount is paid once a month for at least 3
    months in a row (on separate statements) and it is still being paid. Occasional purchases
    that repeat an amount (e.g. hotel stays) and payments that stopped are not recurring.
    Weekly / every-2-weeks charges need every gap to be regular for 3+ months.
  * Not a duplicate: on the Cut back page click "Not a duplicate" next to a flagged pair, or select
    a transaction on the Transactions page and click "Not a duplicate" (also brings back a row
    that was hidden as "also in another statement"). Click again to undo.
    Double-click a recurring charge to see each transaction and the statement it came from.
  * Money sent to people (Zelle/Venmo/Cash App) counts as spending; money received counts as money in.
    If someone pays you back their share of bills (e.g. a partner's Zelle for rent/utilities),
    double-click one of their payments and set the category to "Shared bills (paid back)". The app
    remembers that person, and from then on their payments lower your spending on bills instead.
    Money you send them is still counted normally.
  * Money moved to savings or investments (Robinhood, Fidelity, Coinbase...) is not spending.
  * Money moved between your own accounts (checking -> savings -> another bank's savings) isn't
    new money either. The By folder page shows it per account as "Moved in" / "Moved out", so a
    savings folder shows its deposits there, and Cash flow has a "Moved in" column. Saving is
    counted once: moving money on from one savings account to another isn't counted as saved again.
  * Money moved between your bank and another bank (e.g. Chase -> Capital One savings) is not
    spending, and money moved back is not new money in. Add both banks' statements and the two
    sides are matched automatically; transfers into a savings account show as "Saved" on the
    Cash flow page. Loan payments, insurance and ATM cash to a bank still count as spending.
  * Refunds and returns are subtracted from spending, not counted as money in.
  * "Money in" is every deposit into your bank accounts except transfers between your own accounts
    and refunds - not just paychecks the app recognises.
  * Spending is compared with money in only for whole months covered by your statements: every
    account with statements around that month must cover it. So a month with a full month of card
    purchases but half a month of checking, or a missing checking statement, isn't compared (and
    the missing statement is flagged on Files & checks and Cut back).


FIXING THINGS (the app remembers your fixes)
--------------------------------------------
  * Wrong category: double-click the transaction (or select several > "Set category...") and choose
    what it applies to:
      - every transaction from that company (remembered), or
      - every transaction whose description contains some text you type, e.g. OPENHOUSETEXAS -
        handy when the bank adds a code that changes each time ("OPENHOUSETEXAS 7YR06G"), or
      - only the selected transaction(s).
    Your text rules are saved in my_rules.json in the .spending_analyzer folder.
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

Ideas credits: CSV import and budgets were inspired by Budgeter (MIT) and Num (AGPL-3.0); no code was
copied from either.

FOR DEVELOPERS: tests live in tests/ (python -m unittest discover -s tests). The fixture PDFs
mimic real statement layouts; regenerate with tests/make_fixtures.py (needs reportlab).
Bundled third-party code: pypdf 7.1.0 (BSD-3-Clause) - see app/vendor/VERSIONS.txt.
