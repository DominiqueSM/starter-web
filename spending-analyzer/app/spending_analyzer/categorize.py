"""Categorisation: learned choices > known merchants > keywords > broad guesses."""
from __future__ import annotations

import json
import os
import re

from .merchants import canonical

# Categories that are not counted as "spending"
NON_SPENDING = {"Income", "Transfers & Payments", "Savings & Investments"}

# Categories considered discretionary (candidates for cutting back)
DISCRETIONARY = {
    "Dining Out", "Fast Food", "Coffee Shops", "Food Delivery", "Bars & Alcohol",
    "Shopping", "Entertainment", "Streaming & Subscriptions", "Rideshare & Taxi",
    "Travel", "Personal Care", "Gaming", "Hobbies", "Convenience Stores",
}

# Order matters: the first matching category wins.
DEFAULT_RULES: list[tuple[str, list[str]]] = [
    ("Transfers & Payments", [
        "TRANSFER TO", "TRANSFER FROM", "ONLINE TRANSFER", "PAYPAL TRANSFER", "CREDIT CARD PAYMENT", "CARD PAYMENT", "INTERNAL TRANSFER", "WIRE TRANSFER",
        "CARD ENDING", "CRD AUTOPAY", "CREDIT CRD", "CRCARDPMT", "AMEX EPAYMENT", "AMERICAN EXPRESS ACH",
        "DISCOVER E-PAYMENT", "DISCOVER PAYMENT", "CAPITAL ONE MOBILE", "CAPITAL ONE ONLINE", "CITI AUTOPAY",
        "CITI CARD ONLINE", "APPLECARD", "GSBANK PAYMENT", "SYNCHRONY", "BARCLAYCARD", "CARDMEMBER SERV",
        "TRANSFER TO SAV", "TRANSFER TO CHK", "XFER", "FUNDS TRANSFER", "PAYPAL INST XFER", "TO SAVINGS",
        "FROM SAVINGS", "TO CHECKING", "FROM CHECKING",
    ]),
    ("Savings & Investments", ["ROBINHOOD", "COINBASE", "ACORNS", "BETTERMENT", "WEALTHFRONT", "VANGUARD",
                               "FIDELITY", "SCHWAB BROKERAGE", "E*TRADE", "ETRADE", "M1 FINANCE", "STASH",
                               "PUBLIC.COM", "WEBULL", "AMERITRADE", "CRYPTO.COM", "KRAKEN", "GEMINI",
                               "BROKERAGE", "INVESTMENT", "TREASURYDIRECT", "SAVINGS DEPOSIT", "TO BROKERAGE",
                               "MARCUS", "AMEX SAVINGS", "ALLY BANK TRANSFER", "SOFI SAVINGS", "CIT BANK",
                               "CASH APP INVESTING", "401K", "ROTH IRA", "IRA CONTRIB"]),
    ("Loans & Debt", ["STUDENT LN", "STUDENT LOAN", "LOAN PMT", "LOAN PAYMENT", "AUTO LOAN", "CAR PAYMENT",
                      "AUTO FINANCE", "AUTO FIN", "LOAN SERVIC", "NAVIENT", "NELNET", "MOHELA", "AIDVANTAGE",
                      "DEPT EDUCATION", "DEPT OF ED", "SALLIE MAE", "LENDINGCLUB", "UPSTART", "PERSONAL LOAN"]),
    ("Income", ["PAYROLL", "DIRECT DEP", "DIR DEP", "SALARY", "INTEREST PAID", "INTEREST EARNED",
                "DIVIDEND", "TAX REFUND", "IRS TREAS", "TREAS 310", "SSA TREAS", "PAYCHECK", "WAGES", "ADP",
                "GUSTO", "PAYCHEX", "INTUIT PAYROLL", "UNEMPLOYMENT", "ACH CREDIT", "ACH CR", "DIRECT CREDIT",
                "MOBILE DEPOSIT", "REMOTE DEPOSIT", "ATM DEPOSIT", "BRANCH DEPOSIT", "DEPOSIT"]),
    ("Fees & Interest", [
        "FEE", "INTEREST CHARGE", "FINANCE CHARGE", "OVERDRAFT", "NSF", "LATE CHARGE", "ANNUAL MEMBERSHIP",
        "FOREIGN TRANSACTION", "ATM SURCHARGE", "SERVICE CHARGE", "PURCHASE INTEREST", "CASH ADVANCE INTEREST",
    ]),
    ("Food Delivery", ["DOORDASH", "UBER EATS", "UBEREATS", "GRUBHUB", "POSTMATES", "SEAMLESS", "CAVIAR",
                       "DELIVEROO", "JUST EAT", "SKIPTHEDISHES", "GOPUFF", "INSTACART"]),
    ("Coffee Shops", ["STARBUCKS", "DUNKIN", "PEET", "TIM HORTONS", "DUTCH BROS", "COFFEE", "CAFE", "ESPRESSO",
                      "BLUE BOTTLE", "CARIBOU", "PHILZ", "COSTA"]),
    ("Fast Food", ["MCDONALD", "BURGER KING", "WENDY", "TACO BELL", "CHICK-FIL-A", "CHICK FIL A", "KFC",
                   "POPEYES", "SUBWAY", "CHIPOTLE", "DOMINO", "PIZZA HUT", "PAPA JOHN", "SONIC DRIVE",
                   "JACK IN THE BOX", "ARBY", "PANDA EXPRESS", "FIVE GUYS", "IN-N-OUT", "WHATABURGER",
                   "CULVER", "JIMMY JOHN", "JERSEY MIKE", "WINGSTOP", "QDOBA", "DAIRY QUEEN", "CARLS JR",
                   "HARDEE", "WHITE CASTLE", "SHAKE SHACK", "PANERA", "LITTLE CAESARS", "DEL TACO"]),
    ("Bars & Alcohol", ["BAR ", " PUB", "TAVERN", "BREWERY", "BREWING", "WINE", "LIQUOR", "SPIRITS",
                        "TAPROOM", "SALOON", "LOUNGE", "BEER", "TOTAL WINE", "BEVMO"]),
    ("Dining Out", ["RESTAURANT", "GRILL", "BISTRO", "DINER", "SUSHI", "PIZZA", "STEAKHOUSE", "KITCHEN",
                    "TAQUERIA", "BBQ", "RAMEN", "THAI", "PHO", "BURRITO", "OLIVE GARDEN", "APPLEBEE",
                    "CHILI'S", "CHILIS", "OUTBACK", "CHEESECAKE", "IHOP", "DENNY", "CRACKER BARREL",
                    "RED ROBIN", "BUFFALO WILD", "TST*", "TOAST", "EATERY", "CANTINA", "BAKERY", "DELI",
                    "NOODLE", "BURGER", "TACO", "WINGS", "BRUNCH"]),
    ("Groceries", ["GROCERY", "SAFEWAY", "KROGER", "WHOLE FOODS", "WHOLEFDS", "TRADER JOE", "ALDI", "PUBLIX",
                   "WEGMANS", "HEB ", "H-E-B", "FOOD LION", "ALBERTSONS", "SPROUTS", "MEIJER", "GIANT",
                   "STOP & SHOP", "HY-VEE", "WINCO", "RALPHS", "VONS", "FRED MEYER", "SMITHS", "MARKET",
                   "SUPERMARKET", "LIDL", "COSTCO", "SAM'S CLUB", "SAMS CLUB", "BJ'S WHOLESALE", "FOOD 4 LESS",
                   "SAVE MART", "PIGGLY", "HARRIS TEETER", "SHOPRITE", "TESCO", "SAINSBURY", "LOBLAWS"]),
    ("Streaming & Subscriptions", [
        "NETFLIX", "HULU", "DISNEY PLUS", "DISNEY+", "DISNEYPLUS", "HBO", "MAX.COM", "SPOTIFY", "APPLE.COM/BILL",
        "APPLE MUSIC", "ITUNES", "YOUTUBE PREMIUM", "YOUTUBE TV", "GOOGLE *YOUTUBE", "PARAMOUNT", "PEACOCK",
        "AMAZON PRIME", "PRIME VIDEO", "AUDIBLE", "SIRIUSXM", "SIRIUS XM", "PANDORA", "TIDAL", "CRUNCHYROLL",
        "ESPN+", "SLING", "FUBO", "PATREON", "SUBSTACK", "ONLYFANS", "MEDIUM.COM", "NYTIMES", "WSJ",
        "WASHINGTON POST", "ICLOUD", "GOOGLE STORAGE", "GOOGLE ONE", "DROPBOX", "MICROSOFT 365",
        "ADOBE", "CHATGPT", "OPENAI", "ANTHROPIC", "CLAUDE.AI", "NORDVPN", "EXPRESSVPN", "DUOLINGO",
        "CALM", "HEADSPACE", "LINKEDIN PREMIUM", "MASTERCLASS", "KINDLE UNLTD", "SUBSCRIPTION",
    ]),
    ("Gaming", ["STEAM", "STEAMGAMES", "PLAYSTATION", "XBOX", "NINTENDO", "EPIC GAMES", "ROBLOX", "BLIZZARD",
                "TWITCH", "RIOT GAMES", "EA *"]),
    ("Gym & Fitness", ["GYM", "FITNESS", "PLANET FIT", "LA FITNESS", "24 HOUR", "EQUINOX", "ORANGETHEORY",
                       "CROSSFIT", "PELOTON", "YOGA", "CLASSPASS", "ANYTIME FIT", "GOLD'S GYM", "CRUNCH"]),
    ("Rideshare & Taxi", ["UBER", "LYFT", "TAXI", "CAB ", "BOLT"]),
    ("Utilities", ["ELECTRIC", "POWER", "ENERGY", "WATER", "SEWER", "GAS CO", "PG&E", "PGE", "CON ED",
                   "DUKE ENERGY", "UTILITY", "UTILITIES", "TRASH", "WASTE MGMT", "WASTE MANAGEMENT", "XCEL",
                   "EDISON", "NATIONAL GRID", "DOMINION"]),
    ("Phone & Internet", ["VERIZON", "AT&T", "ATT*", "T-MOBILE", "TMOBILE", "SPRINT", "COMCAST", "XFINITY",
                          "SPECTRUM", "COX COMM", "CENTURYLINK", "FRONTIER COMM", "MINT MOBILE", "VISIBLE",
                          "GOOGLE FI", "CRICKET", "BOOST MOBILE", "STARLINK", "INTERNET", "WIRELESS"]),
    ("Convenience Stores", ["7-ELEVEN", "7 ELEVEN", "AMPM", "AM PM", "WAWA", "SHEETZ", "CIRCLE K", "QUICK STOP",
                            "CORNER STORE", "BODEGA", "CONVENIENCE"]),
    ("Gas & Fuel", ["SHELL", "CHEVRON", "EXXON", "EXXONMOBIL", "MOBIL OIL", "BP ", "ARCO", "SUNOCO", "VALERO", "CITGO",
                    "MARATHON", "SPEEDWAY", "CIRCLE K", "WAWA", "SHEETZ", "QUIKTRIP", "QT ", "76 ", "PHILLIPS 66",
                    "GAS", "FUEL", "CASEY'S", "KWIK", "PILOT", "LOVE'S", "RACETRAC", "MURPHY USA"]),
    ("Auto & Transport", ["PARKING", "PARK MOBILE", "PARKMOBILE", "TOLL", "E-ZPASS", "EZPASS", "FASTRAK",
                          "SUNPASS", "DMV", "JIFFY LUBE", "AUTOZONE", "O'REILLY", "ADVANCE AUTO", "CAR WASH",
                          "FIRESTONE", "PEP BOYS", "TIRE", "AUTO REPAIR", "MIDAS", "METRO", "TRANSIT",
                          "MTA", "BART", "CLIPPER", "AMTRAK", "GREYHOUND", "TESLA", "NTTA", "TXTAG", "TOLLWAY"]),
    ("Travel", ["AIRLINE", "AIRWAYS", "DELTA AIR", "UNITED AIR", "AMERICAN AIR", "SOUTHWEST", "JETBLUE",
                "ALASKA AIR", "SPIRIT AIR", "FRONTIER", "HOTEL", "MARRIOTT", "HILTON", "HYATT", "AIRBNB",
                "VRBO", "EXPEDIA", "BOOKING.COM", "PRICELINE", "HOTELS.COM", "HERTZ", "AVIS", "ENTERPRISE RENT",
                "BUDGET RENT", "NATIONAL CAR", "INN ", "RESORT", "MOTEL", "TSA PRE", "KAYAK"]),
    ("Housing", ["RENT", "MORTGAGE", "HOA", "PROPERTY MGMT", "APARTMENT", "LEASING", "LANDLORD",
                 "HOME DEPOT", "LOWE'S", "LOWES", "ACE HARDWARE", "MENARDS", "IKEA"]),
    ("Insurance", ["INSURANCE", "GEICO", "PROGRESSIVE", "STATE FARM", "ALLSTATE", "LIBERTY MUTUAL",
                   "FARMERS INS", "NATIONWIDE", "USAA", "LEMONADE", "METLIFE", "AFLAC"]),
    ("Health & Medical", ["PHARMACY", "CVS", "WALGREENS", "RITE AID", "DOCTOR", "MEDICAL", "DENTAL", "DENTIST",
                          "CLINIC", "HOSPITAL", "OPTOMETR", "VISION", "LABCORP", "QUEST DIAG", "HEALTH",
                          "THERAPY", "CHIROPRACT", "URGENT CARE", "KAISER"]),
    ("Personal Care", ["SALON", "BARBER", "SPA", "NAILS", "ULTA", "SEPHORA", "MASSAGE", "COSMETIC",
                       "GREAT CLIPS", "SUPERCUTS", "WAX", "BEAUTY"]),
    ("Entertainment", ["CINEMA", "THEATER", "THEATRE", "AMC ", "REGAL", "FANDANGO", "TICKETMASTER",
                       "STUBHUB", "EVENTBRITE", "CONCERT", "MUSEUM", "BOWLING", "GOLF", "ZOO", "PARK TICKET",
                       "LIVE NATION", "SEATGEEK", "ARCADE", "DAVE & BUSTER"]),
    ("Education", ["TUITION", "UNIVERSITY", "COLLEGE", "SCHOOL", "COURSERA", "UDEMY", "BOOKSTORE",
                   "CHEGG"]),
    ("Kids & Pets", ["PETSMART", "PETCO", "CHEWY", "VET", "DAYCARE", "CHILDCARE", "TOYS", "BABY"]),
    ("Gifts & Donations", ["DONATION", "CHARITY", "GOFUNDME", "RED CROSS", "UNICEF", "CHURCH", "FOUNDATION",
                           "1-800-FLOWERS", "FLORIST", "HALLMARK"]),
    ("Shopping", ["AMAZON", "AMZN", "TARGET", "WALMART", "WAL-MART", "BEST BUY", "EBAY", "ETSY", "APPLE STORE",
                  "MACY", "NORDSTROM", "KOHL", "TJ MAXX", "TJMAXX", "MARSHALLS", "ROSS", "OLD NAVY", "GAP ",
                  "H&M", "ZARA", "UNIQLO", "NIKE", "ADIDAS", "SHEIN", "TEMU", "WISH.COM", "WAYFAIR",
                  "BED BATH", "DOLLAR TREE", "DOLLAR GENERAL", "FIVE BELOW", "BURLINGTON", "NEWEGG",
                  "GAMESTOP", "MICHAELS", "HOBBY LOBBY", "JOANN", "DICK'S", "REI ", "ACADEMY", "SHOP",
                  "STORE", "OUTLET", "BOUTIQUE", "MALL"]),
    ("Cash & ATM", ["ATM", "CASH WITHDRAWAL", "WITHDRAWAL"]),
]

RULES_VERSION = 3

# On a card statement these mean "payment received" (money in). Out of a checking account they are
# usually bill payments (real spending), so they only count as transfers for money coming in.
GENERIC_PAYMENT = re.compile(
    r"\b(PAYMENT\s*-?\s*THANK|THANK YOU|AUTO\s?PAY|ONLINE PAYMENT|MOBILE PAYMENT|ONLINE PMT|MOBILE PMT|EPAY"
    r"|E-PAYMENT|PAYMENT RECEIVED|BILL PAY|ACH PMT|INTERNET PAYMENT|PAYMENT - WEB|PAYMENT)\b")
# Money sent to people is real spending (rent to a landlord, splitting a bill); money received isn't income.
P2P_CATEGORY = "Zelle / Venmo / Cash App"
CARD_PAYMENT_OUT = re.compile(r"PAYMENT TO .{0,20}(CARD|CRD|VISA|MASTERCARD|AMEX)|(CARD|CRD) (ENDING|PMT|PAYMENT)")

# Broad words that often mislead: matches on these are marked as a guess.
WEAK_KEYWORDS = {"SHOP", "STORE", "MARKET", "GAS", "WATER", "POWER", "BAR", "CAFE", "OUTLET", "MALL", "BOUTIQUE",
                 "DEPOSIT", "WITHDRAWAL", "INN", "KITCHEN", "GRILL", "SPA", "HEALTH", "VISION", "TIRE", "ENERGY",
                 "INTERNET", "WIRELESS", "SAVINGS", "LOUNGE", "WINE", "BEER", "TOYS", "BABY", "VET", "METRO",
                 "TRANSIT", "SCHOOL", "RENT", "TOAST", "DELI", "BAKERY", "BURGER", "TACO", "WINGS", "PIZZA", "MARKET"}


def _keywords_regex(keywords):
    """Keywords match at a word start; short ones (<=4 chars) must also end at a word boundary,
    so e.g. 'PHO' doesn't match 'PHONE' and 'FEE' doesn't match 'COFFEE'."""
    parts = []
    for kw in keywords:
        kw = kw.strip().upper()
        if not kw:
            continue
        p = re.escape(kw)
        if kw[0].isalnum():
            p = r"(?<![A-Z0-9])" + p
        if len(kw) <= 4 and kw[-1].isalnum():
            p = p + r"(?![A-Z0-9])"
        parts.append(p)
    return re.compile("|".join(parts) if parts else r"(?!x)x")


class Categorizer:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.rules_path = os.path.join(data_dir, "category_rules.json")
        self.overrides_path = os.path.join(data_dir, "merchant_overrides.json")
        self.rules = self._load_rules()
        self._compiled = []
        for c, ks in self.rules:
            strong = [k for k in ks if k.strip().upper() not in WEAK_KEYWORDS]
            weak = [k for k in ks if k.strip().upper() in WEAK_KEYWORDS]
            self._compiled.append((c, _keywords_regex(strong), _keywords_regex(weak)))
        self.overrides: dict[str, str] = self._load_json(self.overrides_path, {})

    @staticmethod
    def _load_json(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _write_default_rules(self):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.rules_path, "w", encoding="utf-8") as f:
            json.dump({"_help": "Edit keywords freely. First matching category wins. Keywords are matched "
                                "case-insensitively against the transaction description. Known merchants "
                                "(Netflix, Costco, ...) are recognised before these rules.",
                       "version": RULES_VERSION,
                       "rules": [{"category": c, "keywords": k} for c, k in DEFAULT_RULES]}, f, indent=2)

    def _load_rules(self):
        data = self._load_json(self.rules_path, None)
        if data is None or data.get("version") != RULES_VERSION:
            if data is not None:   # keep the old file in case it was edited by hand
                try:
                    os.replace(self.rules_path, self.rules_path.replace(".json", f".v{data.get('version', 1)}.bak.json"))
                except OSError:
                    pass
            try:
                self._write_default_rules()
            except OSError:
                pass
            data = self._load_json(self.rules_path, None)
        try:
            rules = [(r["category"], [k.upper() for k in r["keywords"]]) for r in data["rules"]]
            if rules:
                return rules
        except Exception:
            pass
        return [(c, [k.upper() for k in ks]) for c, ks in DEFAULT_RULES]

    def all_categories(self) -> list[str]:
        cats = [c for c, _ in self.rules]
        for c in self.overrides.values():
            if c not in cats:
                cats.append(c)
        for extra in (P2P_CATEGORY, "Other"):
            if extra not in cats:
                cats.append(extra)
        return cats

    def categorize(self, desc: str, merchant: str, brand_cat: str | None = None,
                   money_in: bool = False) -> tuple[str, str]:
        """Return (category, source). Source: learned | merchant | keyword | guess | none."""
        if merchant in self.overrides:
            return self.overrides[merchant], "learned"
        d = desc.upper()
        # Transfers/income keywords beat merchant names ("Payment to Chase card" stays a transfer)
        if CARD_PAYMENT_OUT.search(d) or (money_in and GENERIC_PAYMENT.search(d)):
            return "Transfers & Payments", "keyword"
        if re.search(r"\b(ZELLE|VENMO|CASH ?APP|SQUARE CASH|APPLE CASH)\b", d):
            return P2P_CATEGORY, "keyword"   # money in this way counts as money in, unless matched to own account
        for cat, strong, _ in self._compiled:
            if cat in ("Transfers & Payments", "Savings & Investments") and strong.search(d):
                return cat, "keyword"
            if cat == "Income" and money_in and strong.search(d):
                return cat, "keyword"
        if brand_cat:
            return brand_cat, "merchant"
        for cat, strong, _ in self._compiled:
            if cat == "Income" and not money_in:
                continue
            if strong.search(d):
                return cat, "keyword"
        for cat, _, weak in self._compiled:
            if cat == "Income" and not money_in:
                continue
            if weak.search(d):
                return cat, "guess"
        return "Other", "none"

    def set_override(self, merchant: str, category: str):
        self.overrides[merchant] = category
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.overrides_path, "w", encoding="utf-8") as f:
            json.dump(self.overrides, f, indent=2, sort_keys=True)

    def apply(self, txs):
        for t in txs:
            t.merchant, brand_cat = canonical(t.description)
            t.category, t.category_source = self.categorize(t.description, t.merchant, brand_cat, t.is_credit)
            # (Income is only ever given to money coming in, so it never flips a withdrawal)


def infer_rent(transactions) -> int:
    """Same large amount to the same unrecognised payee every month is almost always rent or a mortgage.
    Marked as a guess so it's easy to spot and correct."""
    import statistics
    from collections import defaultdict
    groups = defaultdict(list)
    for t in transactions:
        if (t.category == "Other" and t.category_source in ("none", "guess") and not t.is_credit
                and not t.excluded and not t.duplicate):
            groups[t.merchant].append(t)
    changed = 0
    for txs in groups.values():
        txs.sort(key=lambda t: t.date)
        months = {(t.date.year, t.date.month) for t in txs}
        if len(months) < 2:
            continue
        med = statistics.median(t.amount for t in txs)
        gaps = [(b.date - a.date).days for a, b in zip(txs, txs[1:])]
        if med >= 700 and all(abs(t.amount - med) <= med * 0.01 for t in txs) and all(24 <= g <= 37 for g in gaps):
            for t in txs:
                t.category, t.category_source = "Housing", "guess"
                t.note = "Same large amount every month: probably rent or mortgage"
                changed += 1
    return changed
