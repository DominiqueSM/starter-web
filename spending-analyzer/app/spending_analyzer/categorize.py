"""Keyword-based categorisation and merchant-name cleanup."""
from __future__ import annotations

import json
import os
import re

# Categories that are not counted as "spending"
NON_SPENDING = {"Income", "Transfers & Payments"}

# Categories considered discretionary (candidates for cutting back)
DISCRETIONARY = {
    "Dining Out", "Fast Food", "Coffee Shops", "Food Delivery", "Bars & Alcohol",
    "Shopping", "Entertainment", "Streaming & Subscriptions", "Rideshare & Taxi",
    "Travel", "Personal Care", "Gaming", "Hobbies", "Convenience Stores",
}

# Order matters: the first matching category wins.
DEFAULT_RULES: list[tuple[str, list[str]]] = [
    ("Transfers & Payments", [
        "PAYMENT THANK", "AUTOPAY", "AUTO PAY", "ONLINE PAYMENT", "TRANSFER TO", "TRANSFER FROM",
        "ONLINE TRANSFER", "ZELLE", "VENMO", "CASH APP", "CASHAPP", "PAYPAL TRANSFER", "CREDIT CARD PAYMENT",
        "CARD PAYMENT", "ACH PMT", "EPAY", "BILL PAY", "SAVINGS", "INTERNAL TRANSFER", "WIRE TRANSFER",
        "MOBILE PAYMENT", "PAYMENT RECEIVED",
    ]),
    ("Income", ["PAYROLL", "DIRECT DEP", "DIR DEP", "SALARY", "INTEREST PAID", "INTEREST EARNED",
                "DIVIDEND", "TAX REFUND", "IRS TREAS", "DEPOSIT"]),
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
                          "MTA", "BART", "CLIPPER", "AMTRAK", "GREYHOUND", "CAR PAYMENT", "AUTO LOAN", "TESLA"]),
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
    ("Education", ["TUITION", "UNIVERSITY", "COLLEGE", "SCHOOL", "COURSERA", "UDEMY", "STUDENT LOAN",
                   "NAVIENT", "NELNET", "BOOKSTORE", "CHEGG"]),
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

# Prefixes/noise removed before computing a merchant key
NOISE_RE = re.compile(
    r"^(POS|DEBIT|CHECKCARD|CHECK CARD|PURCHASE|DEBIT CARD PURCHASE|CARD PURCHASE|VISA|RECURRING|ACH|"
    r"PREAUTHORIZED|PRE-AUTH|ELECTRONIC|ONLINE|DBT|POS PURCHASE|PURCHASE AUTHORIZED ON \d\d/\d\d|"
    r"WITHDRAWAL|SQ ?\*|TST ?\*|SP ?\*|PAYPAL ?\*|PP ?\*|GOOGLE ?\*|APL ?\*|IN ?\*|PY ?\*)\s*",
    re.I,
)
STATE_RE = re.compile(
    r"\s+(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|"
    r"NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)$"
)


def merchant_key(desc: str) -> str:
    s = desc.upper()
    for _ in range(3):
        s = NOISE_RE.sub("", s).strip()
    s = re.sub(r"(X{2,}|\*{2,})\d+", " ", s)       # masked card numbers
    s = re.sub(r"\b\d{2}/\d{2}(/\d{2,4})?\b", " ", s)  # dates
    s = re.sub(r"[#*]\s*\d+", " ", s)                  # store numbers
    s = re.sub(r"\b\d{3,}\b", " ", s)                  # long numbers / phone numbers
    s = re.sub(r"https?://\S+|WWW\.\S+", " ", s)
    s = re.sub(r"[^A-Z0-9&'.+ ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = STATE_RE.sub("", s)
    words = [w for w in s.split()
             if not (len(w) >= 4 and re.search(r"\d", w) and re.search(r"[A-Z]", w))]  # reference codes
    # Keep the first two words: enough to identify the merchant, drops city names
    words = words[:2]
    key = " ".join(words).strip(" .")
    return key or desc.upper()[:30]


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
        self._compiled = [(c, _keywords_regex(ks)) for c, ks in self.rules]
        self.overrides: dict[str, str] = self._load_json(self.overrides_path, {})

    @staticmethod
    def _load_json(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _load_rules(self):
        if not os.path.exists(self.rules_path):
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.rules_path, "w", encoding="utf-8") as f:
                json.dump({"_help": "Edit keywords freely. First matching category wins. "
                                    "Keywords are matched case-insensitively against the transaction description.",
                           "rules": [{"category": c, "keywords": k} for c, k in DEFAULT_RULES]},
                          f, indent=2)
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
        if "Other" not in cats:
            cats.append("Other")
        return cats

    def categorize(self, desc: str, merchant: str) -> str:
        if merchant in self.overrides:
            return self.overrides[merchant]
        d = desc.upper()
        for cat, rx in self._compiled:
            if rx.search(d):
                return cat
        return "Other"

    def set_override(self, merchant: str, category: str):
        self.overrides[merchant] = category
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.overrides_path, "w", encoding="utf-8") as f:
            json.dump(self.overrides, f, indent=2, sort_keys=True)

    def apply(self, txs):
        for t in txs:
            t.merchant = merchant_key(t.description)
            t.category = self.categorize(t.description, t.merchant)
            if t.category == "Income":
                t.is_credit = True
