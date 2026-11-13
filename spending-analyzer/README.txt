SPENDING ANALYZER  (v1.0, works 100% offline)
=============================================

Reads the PDF bank and credit-card statements in a folder and shows:
  * how much you spend, per month and per category (dining, groceries, shopping...)
  * recurring charges and subscriptions, and any whose price went up
  * fees and interest you paid
  * possible duplicate charges
  * a ranked list of "what to cut back on" with estimated monthly savings
  * export to CSV, or to an HTML report you can print or keep

PRIVACY: the app never connects to the internet. It blocks network access
inside its own process. Your PDFs are only read; nothing is uploaded or changed.


1. ONE-TIME SETUP: install Python (free)
----------------------------------------
You need Python 3.10 or newer. Download the installer from python.org once
(do it on any computer, then install offline if you like).

  Windows: run the installer and TICK "Add python.exe to PATH".
  macOS:   run the python.org installer (it includes everything needed).
  Linux:   sudo apt install python3 python3-tk   (or your distro's equivalent)

No other installs are needed: the PDF reader library is bundled in app/vendor.


2. START THE APP
----------------
  Windows: double-click  "Start Spending Analyzer (Windows).bat"
  macOS:   double-click  "Start Spending Analyzer (Mac).command"
           (first time: right-click > Open, then Open, because the file is unsigned.
            If it says permission denied, open Terminal and run:
            chmod +x "/path/to/Start Spending Analyzer (Mac).command")
  Linux:   ./start-linux.sh

Or from a terminal in this folder:  python3 app/main.py


3. USE IT
---------
  1. Click Browse... and pick the folder that holds your statement PDFs
     (subfolders are included; exact duplicate files are skipped).
  2. Click Analyze.
  3. Look at the tabs:
       Overview             totals and charts
       What to cut back on  ranked suggestions with estimated savings
       Transactions         every transaction found; search and filter
       Recurring charges    subscriptions and bills
       Files                what was read from each PDF, and any problems

  Try it first with the "sample-statements (fake data)" folder.

Fixing things up (this improves the suggestions):
  * Wrong category?  Double-click the transaction (or select several and click
    "Set category..."). The app remembers it for that merchant from then on.
  * A transfer between your own accounts, or something you don't want counted?
    Select it and click "Exclude / include".
  * A refund showing as spending (or the reverse)?  Click "Flip in/out".


TIPS AND LIMITS
---------------
  * Use the PDFs you download from your bank's website. Scanned/photographed
    statements have no text and can't be read (the Files tab will say so).
  * Password-protected PDFs: open and re-save them without a password first.
  * Credit-card payments and transfers are recognised and not counted as
    spending, so paying your card from checking isn't counted twice.
  * Statement layouts vary a lot. If a PDF shows 0 transactions in the Files
    tab, its layout wasn't recognised. Exporting CSV from your bank and
    comparing helps spot gaps.
  * Savings figures are estimates based on common, realistic reductions
    (e.g. eating out 30% less), not guarantees.

Your settings and category choices are saved in a ".spending_analyzer" folder
in your home folder. category_rules.json there holds the keyword list used to
pick categories; you can edit it with any text editor. Delete it to restore
the defaults.

Bundled third-party code: pypdf (BSD-3-Clause licence, see app/vendor/pypdf/LICENSE.txt).
