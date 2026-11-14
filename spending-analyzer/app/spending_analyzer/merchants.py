"""Merchant clean-up: map raw statement descriptions to one name per company.

"NETFLIX.COMNETFLIX.COMCA", "NETFLIX.COM NETFLIX.COM CA" and "NETFLIX.COM" all become "Netflix";
"HLU*HULUPLUS" and "HULU CA" become "Hulu".
"""
from __future__ import annotations

import re

# (pattern, display name, category). Order matters: specific before general.
BRANDS: list[tuple[str, str, str]] = [
    # --- streaming, software, memberships
    (r"NETFLIX", "Netflix", "Streaming & Subscriptions"),
    (r"\bHULU|\bHLU\b|HLU\s*\*", "Hulu", "Streaming & Subscriptions"),
    (r"DISNEY\s?(PLUS|\+)|DISNEYPLUS", "Disney+", "Streaming & Subscriptions"),
    (r"\bHBO|\bMAX\.COM|HBOMAX", "Max (HBO)", "Streaming & Subscriptions"),
    (r"PARAMOUNT", "Paramount+", "Streaming & Subscriptions"),
    (r"PEACOCK", "Peacock", "Streaming & Subscriptions"),
    (r"SPOTIFY", "Spotify", "Streaming & Subscriptions"),
    (r"YOUTUBE\s*TV|YOUTUBETV", "YouTube TV", "Streaming & Subscriptions"),
    (r"YOUTUBE|GOOGLE\s*\*?\s*YOUTUBE", "YouTube Premium", "Streaming & Subscriptions"),
    (r"GOOGLE\s*\*?\s*(STORAGE|ONE)\b|GOOGLE\s*\*?\s*GOOGLE ONE", "Google One", "Streaming & Subscriptions"),
    (r"AMAZON\s*PRIME|PRIME\s*VIDEO|AMZN\s*PRIME|PRIME\s*MEMBERSHIP|AMAZON\s*DIGI|KINDLE\s*UNL", "Amazon Prime",
     "Streaming & Subscriptions"),
    (r"AUDIBLE", "Audible", "Streaming & Subscriptions"),
    (r"CRUNCHYROLL", "Crunchyroll", "Streaming & Subscriptions"),
    (r"SIRIUS", "SiriusXM", "Streaming & Subscriptions"),
    (r"PANDORA", "Pandora", "Streaming & Subscriptions"),
    (r"\bTIDAL\b", "Tidal", "Streaming & Subscriptions"),
    (r"ESPN", "ESPN+", "Streaming & Subscriptions"),
    (r"\bSLING\b", "Sling TV", "Streaming & Subscriptions"),
    (r"\bFUBO", "Fubo", "Streaming & Subscriptions"),
    (r"\bPHILO\b", "Philo", "Streaming & Subscriptions"),
    (r"\bSTARZ", "Starz", "Streaming & Subscriptions"),
    (r"APPLE\.COM\s*/?\s*BILL|ITUNES|APPLE\s*SERVICES|ICLOUD", "Apple (App Store / iCloud)", "Streaming & Subscriptions"),
    (r"ANTHROPIC|CLAUDE\.AI|CLAUDE\s*AI", "Anthropic (Claude)", "Streaming & Subscriptions"),
    (r"OPENAI|CHATGPT", "OpenAI (ChatGPT)", "Streaming & Subscriptions"),
    (r"MIDJOURNEY", "Midjourney", "Streaming & Subscriptions"),
    (r"GITHUB", "GitHub", "Streaming & Subscriptions"),
    (r"ADOBE", "Adobe", "Streaming & Subscriptions"),
    (r"DROPBOX", "Dropbox", "Streaming & Subscriptions"),
    (r"CANVA", "Canva", "Streaming & Subscriptions"),
    (r"GRAMMARLY", "Grammarly", "Streaming & Subscriptions"),
    (r"NOTION\b", "Notion", "Streaming & Subscriptions"),
    (r"DUOLINGO", "Duolingo", "Streaming & Subscriptions"),
    (r"HEADSPACE", "Headspace", "Streaming & Subscriptions"),
    (r"\bCALM\.COM|\bCALM\b", "Calm", "Streaming & Subscriptions"),
    (r"LINKEDIN", "LinkedIn", "Streaming & Subscriptions"),
    (r"NORDVPN|NORD\s*SEC", "NordVPN", "Streaming & Subscriptions"),
    (r"EXPRESSVPN", "ExpressVPN", "Streaming & Subscriptions"),
    (r"PATREON", "Patreon", "Streaming & Subscriptions"),
    (r"SUBSTACK", "Substack", "Streaming & Subscriptions"),
    (r"NYTIMES|NY\s*TIMES", "New York Times", "Streaming & Subscriptions"),
    (r"\bWSJ\b|WALL ST", "Wall Street Journal", "Streaming & Subscriptions"),
    (r"XBOX|MICROSOFT\s*\*\s*XBOX", "Xbox", "Gaming"),
    (r"MICROSOFT|MSFT", "Microsoft", "Streaming & Subscriptions"),
    (r"PLAYSTATION|SONY\s*INTERACTIVE", "PlayStation", "Gaming"),
    (r"NINTENDO", "Nintendo", "Gaming"),
    (r"STEAM\s*(GAMES|POWERED|PURCHASE)|STEAMGAMES|\bVALVE\b", "Steam", "Gaming"),
    (r"EPIC\s*GAMES", "Epic Games", "Gaming"),
    (r"ROBLOX", "Roblox", "Gaming"),
    (r"TWITCH", "Twitch", "Gaming"),
    # --- fitness
    (r"PLANET\s*FIT", "Planet Fitness", "Gym & Fitness"),
    (r"LA\s*FITNESS", "LA Fitness", "Gym & Fitness"),
    (r"24\s*HOUR\s*FIT", "24 Hour Fitness", "Gym & Fitness"),
    (r"ANYTIME\s*FIT", "Anytime Fitness", "Gym & Fitness"),
    (r"EQUINOX", "Equinox", "Gym & Fitness"),
    (r"ORANGETHEORY|ORANGE\s*THEORY", "Orangetheory", "Gym & Fitness"),
    (r"CRUNCH\s*FIT", "Crunch Fitness", "Gym & Fitness"),
    (r"LIFE\s*TIME\s*(FIT|MO)", "Life Time", "Gym & Fitness"),
    (r"PELOTON", "Peloton", "Gym & Fitness"),
    (r"CLASSPASS", "ClassPass", "Gym & Fitness"),
    # --- food delivery, coffee, fast food
    (r"UBER\s*\*?\s*EATS|UBEREATS", "Uber Eats", "Food Delivery"),
    (r"DOORDASH|\bDD\s*\*", "DoorDash", "Food Delivery"),
    (r"GRUBHUB", "Grubhub", "Food Delivery"),
    (r"POSTMATES", "Postmates", "Food Delivery"),
    (r"INSTACART", "Instacart", "Food Delivery"),
    (r"STARBUCKS|\bSBUX", "Starbucks", "Coffee Shops"),
    (r"DUNKIN", "Dunkin'", "Coffee Shops"),
    (r"DUTCH\s*BROS", "Dutch Bros", "Coffee Shops"),
    (r"MCDONALD", "McDonald's", "Fast Food"),
    (r"CHICK-?\s?FIL-?\s?A", "Chick-fil-A", "Fast Food"),
    (r"TACO\s*BELL", "Taco Bell", "Fast Food"),
    (r"CHIPOTLE", "Chipotle", "Fast Food"),
    (r"WENDY'?S", "Wendy's", "Fast Food"),
    (r"BURGER\s*KING", "Burger King", "Fast Food"),
    (r"\bSUBWAY\b", "Subway", "Fast Food"),
    (r"DOMINO'?S", "Domino's", "Fast Food"),
    (r"PIZZA\s*HUT", "Pizza Hut", "Fast Food"),
    (r"PANERA", "Panera", "Fast Food"),
    (r"WHATABURGER", "Whataburger", "Fast Food"),
    (r"RAISING\s*CANE", "Raising Cane's", "Fast Food"),
    (r"WINGSTOP", "Wingstop", "Fast Food"),
    (r"POPEYES", "Popeyes", "Fast Food"),
    (r"PANDA\s*EXPRESS", "Panda Express", "Fast Food"),
    (r"JACK\s*IN\s*THE\s*BOX", "Jack in the Box", "Fast Food"),
    (r"IN-N-OUT", "In-N-Out", "Fast Food"),
    (r"FIVE\s*GUYS", "Five Guys", "Fast Food"),
    (r"SONIC\s*DRIVE", "Sonic", "Fast Food"),
    # --- groceries
    (r"COSTCO", "Costco", "Groceries"),
    (r"SAMS\s*CLUB|SAM'S\s*CLUB|SAMSCLUB", "Sam's Club", "Groceries"),
    (r"H-E-B|\bHEB\b", "H-E-B", "Groceries"),
    (r"KROGER", "Kroger", "Groceries"),
    (r"\bALDI\b", "Aldi", "Groceries"),
    (r"TRADER\s*JOE", "Trader Joe's", "Groceries"),
    (r"WHOLE\s*FOODS|WHOLEFDS|\bWFM\b", "Whole Foods", "Groceries"),
    (r"SAFEWAY", "Safeway", "Groceries"),
    (r"PUBLIX", "Publix", "Groceries"),
    (r"TOM\s*THUMB", "Tom Thumb", "Groceries"),
    (r"ALBERTSONS", "Albertsons", "Groceries"),
    (r"SPROUTS", "Sprouts", "Groceries"),
    (r"WINCO", "WinCo", "Groceries"),
    (r"MEIJER", "Meijer", "Groceries"),
    (r"WEGMANS", "Wegmans", "Groceries"),
    (r"HY-?VEE", "Hy-Vee", "Groceries"),
    (r"\bLIDL\b", "Lidl", "Groceries"),
    (r"FIESTA\s*MART", "Fiesta Mart", "Groceries"),
    # --- shopping
    (r"WAL-?MART|WM\s*SUPERCENTER|WALMART", "Walmart", "Shopping"),
    (r"AMAZON|AMZN", "Amazon", "Shopping"),
    (r"\bTARGET\b", "Target", "Shopping"),
    (r"BEST\s*BUY|BESTBUY", "Best Buy", "Shopping"),
    (r"\bEBAY\b", "eBay", "Shopping"),
    (r"\bETSY\b", "Etsy", "Shopping"),
    (r"\bIKEA\b", "IKEA", "Shopping"),
    (r"TJ\s*MAXX|TJMAXX", "TJ Maxx", "Shopping"),
    (r"MARSHALLS", "Marshalls", "Shopping"),
    (r"ROSS\s*STORES?", "Ross", "Shopping"),
    (r"NORDSTROM", "Nordstrom", "Shopping"),
    (r"\bMACY", "Macy's", "Shopping"),
    (r"\bKOHL", "Kohl's", "Shopping"),
    (r"OLD\s*NAVY", "Old Navy", "Shopping"),
    (r"\bSHEIN\b", "Shein", "Shopping"),
    (r"\bTEMU\b", "Temu", "Shopping"),
    (r"WAYFAIR", "Wayfair", "Shopping"),
    (r"DOLLAR\s*TREE", "Dollar Tree", "Shopping"),
    (r"DOLLAR\s*GENERAL", "Dollar General", "Shopping"),
    (r"HOME\s*DEPOT", "Home Depot", "Housing"),
    (r"LOWE'?S\b", "Lowe's", "Housing"),
    (r"\bCVS\b", "CVS", "Health & Medical"),
    (r"WALGREENS", "Walgreens", "Health & Medical"),
    # --- transport
    (r"\bUBER\b", "Uber", "Rideshare & Taxi"),
    (r"\bLYFT\b", "Lyft", "Rideshare & Taxi"),
    (r"\bNTTA\b", "NTTA (tolls)", "Auto & Transport"),
    (r"E-?Z\s*-?PASS", "E-ZPass (tolls)", "Auto & Transport"),
    (r"SUNPASS", "SunPass (tolls)", "Auto & Transport"),
    (r"FASTRAK", "FasTrak (tolls)", "Auto & Transport"),
    (r"TXTAG|TX\s*TAG", "TxTag (tolls)", "Auto & Transport"),
    (r"\bHCTRA\b", "HCTRA (tolls)", "Auto & Transport"),
    (r"PARKMOBILE|PARK\s*MOBILE", "ParkMobile", "Auto & Transport"),
    (r"EXXON|EXXONMOBIL", "Exxon", "Gas & Fuel"),
    (r"\bSHELL\b", "Shell", "Gas & Fuel"),
    (r"CHEVRON", "Chevron", "Gas & Fuel"),
    (r"QUIKTRIP|\bQT\s*\d", "QuikTrip", "Gas & Fuel"),
    (r"RACETRAC", "RaceTrac", "Gas & Fuel"),
    (r"VALERO", "Valero", "Gas & Fuel"),
    (r"BUC-?EE", "Buc-ee's", "Gas & Fuel"),
    (r"MURPHY\s*(USA|EXPRESS)", "Murphy USA", "Gas & Fuel"),
    (r"7-ELEVEN|7\s*ELEVEN|7-11", "7-Eleven", "Convenience Stores"),
    # --- phone, internet, utilities, insurance
    (r"VERIZON|VZWRLSS", "Verizon", "Phone & Internet"),
    (r"AT&T|\bATT\s*\*|\bATT\b", "AT&T", "Phone & Internet"),
    (r"T-?MOBILE", "T-Mobile", "Phone & Internet"),
    (r"SPECTRUM", "Spectrum", "Phone & Internet"),
    (r"XFINITY|COMCAST", "Xfinity", "Phone & Internet"),
    (r"FRONTIER\s*COMM", "Frontier", "Phone & Internet"),
    (r"GOOGLE\s*\*?\s*FI\b", "Google Fi", "Phone & Internet"),
    (r"MINT\s*MOBILE", "Mint Mobile", "Phone & Internet"),
    (r"CRICKET", "Cricket", "Phone & Internet"),
    (r"STARLINK", "Starlink", "Phone & Internet"),
    (r"TXU\s*ENERGY", "TXU Energy", "Utilities"),
    (r"RELIANT\s*ENERGY|\bRELIANT\b", "Reliant", "Utilities"),
    (r"DUKE\s*ENERGY", "Duke Energy", "Utilities"),
    (r"PG&E|\bPGE\b", "PG&E", "Utilities"),
    (r"ATMOS", "Atmos Energy", "Utilities"),
    (r"GEICO", "GEICO", "Insurance"),
    (r"PROGRESSIVE", "Progressive", "Insurance"),
    (r"STATE\s*FARM", "State Farm", "Insurance"),
    (r"ALLSTATE", "Allstate", "Insurance"),
    (r"ASSURANT", "Assurant", "Insurance"),
    (r"LEMONADE", "Lemonade", "Insurance"),
    (r"LIBERTY\s*MUTUAL", "Liberty Mutual", "Insurance"),
    # --- loans and debt
    (r"DEPT\.?\s*(OF\s*)?EDUCATION|DEPT\s*ED\b|US\s*DEPT\s*OF\s*ED", "Dept. of Education (student loans)",
     "Loans & Debt"),
    (r"NAVIENT", "Navient (student loans)", "Loans & Debt"),
    (r"NELNET", "Nelnet (student loans)", "Loans & Debt"),
    (r"MOHELA", "MOHELA (student loans)", "Loans & Debt"),
    (r"AIDVANTAGE", "Aidvantage (student loans)", "Loans & Debt"),
    (r"SALLIE\s*MAE", "Sallie Mae (student loans)", "Loans & Debt"),
    (r"TOYOTA\s*(FIN|MOTOR)|TMCC", "Toyota Financial", "Loans & Debt"),
    (r"HONDA\s*(FIN|PMT)|AMERICAN\s*HONDA", "Honda Financial", "Loans & Debt"),
    (r"FORD\s*(CREDIT|MOTOR\s*CR)", "Ford Credit", "Loans & Debt"),
    (r"GM\s*FINANCIAL", "GM Financial", "Loans & Debt"),
    (r"ALLY\s*(AUTO|FINANCIAL|PAYMT|PMT)", "Ally Auto", "Loans & Debt"),
    (r"ROCKET\s*MORTGAGE|MR\.?\s*COOPER|MORTGAGE", "Mortgage", "Housing"),
    (r"\bAFFIRM\b", "Affirm", "Loans & Debt"),
    (r"\bKLARNA\b", "Klarna", "Loans & Debt"),
    (r"AFTERPAY", "Afterpay", "Loans & Debt"),
]
_BRANDS = [(re.compile(p), name, cat) for p, name, cat in BRANDS]

NOISE_RE = re.compile(
    r"^(POS|DEBIT|CHECKCARD|CHECK CARD|PURCHASE|DEBIT CARD PURCHASE|CARD PURCHASE( WITH PIN)?|VISA|RECURRING"
    r"( PAYMENT)?|ACH( DEBIT| CREDIT)?|PREAUTHORIZED|PRE-AUTH|ELECTRONIC|ONLINE|DBT|POS PURCHASE|POS DEBIT"
    r"|PURCHASE AUTHORIZED ON \d\d/\d\d|WITHDRAWAL|SQ ?\*|TST ?\*|SP ?\*|PAYPAL ?\*|PP ?\*|APL ?\*|IN ?\*|PY ?\*"
    r"|CKO ?\*|BT ?\*|FS ?\*|DNH ?\*|SQSP ?\*|\d{4,}|ORIG CO NAME:?)\s*",
    re.I)
BILLPAY_RE = re.compile(r"^((ONLINE|MOBILE|WEB|RECURRING)\s+)?(BILL\s+)?(PAYMENT|PMT|PYMT|TRANSFER)\s+(\d+\s+)?"
                        r"(TO|FROM)\s+|^ZELLE\s+(PAYMENT\s+)?(TO|FROM)\s+")
STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
             "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
ACH_NOISE = {"PPD", "WEB", "CCD", "ACH", "PMTS", "PMT", "DES", "INDN", "ORIG", "SEC", "TEL", "ID", "CO",
             "ENTRY", "DESCR", "RECURRING", "AUTOPAY", "BILL", "EPAY"}
STOP_TOKENS = {"THE", "INC", "LLC", "CO", "CORP", "COM", "WWW", "HTTPS", "HTTP", "USA", "US"}


def unglue(desc: str) -> str:
    """Add spaces where statement text has glued words together."""
    s = desc.upper()
    s = re.sub(r"(\.(?:COM|NET|ORG|AI|IO|TV|CO))(?=[A-Z0-9])", r"\1 ", s)   # NETFLIX.COMNETFLIX.COMCA
    s = re.sub(r"\*", " * ", s)
    return re.sub(r"\s+", " ", s).strip()


def brand_of(desc: str):
    s = unglue(desc)
    for rx, name, cat in _BRANDS:
        if rx.search(s):
            return name, cat
    return None


def fallback_key(desc: str) -> str:
    s = unglue(desc)
    m = re.match(r"^ZELLE\s+(TRANSFER|PAYMENT)?\s*CONF#?\s*\S+\s*;\s*(.+)$", s)
    if m:   # "Zelle Transfer Conf# abc; Doe, Jane" -> "Jane Doe"
        parts = [p.strip() for p in m.group(2).split(",")]
        s = " ".join(reversed(parts)) if len(parts) == 2 else m.group(2)
    # Bank transfer (ACH) layouts: keep the payee name, drop the bank's extra fields
    m = re.search(r"ORIG CO NAME\s*:?\s*(.+?)\s+(ORIG ID|CO ENTRY|DESC DATE|SEC\s*:|IND ID|IND NAME|$)", s)
    if m:
        s = m.group(1)
    s = re.split(r"\s+(?:DES|ID|INDN|CO ID|ORIG ID|PPD ID|WEB ID|CCD ID|TRN|REF|CONF|TRACE)\s*[:#]", s, maxsplit=1)[0]
    s = BILLPAY_RE.sub("", s)
    for _ in range(3):
        s = NOISE_RE.sub("", s).strip(" *")
    s = re.sub(r"(X{2,}|\*{2,})\d+", " ", s)
    s = re.sub(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", " ", s)
    s = re.sub(r"[#*]\s*\d+", " ", s)
    s = re.sub(r"\b[\w-]*\d{3,}[\w-]*\b", " ", s)          # numbers and reference codes
    s = re.sub(r"\.(COM|NET|ORG|AI|IO|TV|CO)\b", " ", s)
    s = re.sub(r"[^A-Z0-9&' ]", " ", s)
    s = re.sub(r"\bFROM\b", " ", s) if s.startswith("ZELLE") or s.startswith("VENMO") else s
    s = re.sub(r"^(ZELLE|VENMO|CASH APP)\s+(?=[A-Z])(?!CASHOUT)", "", s)
    out = []
    toks = s.split()
    for tok in toks:
        if tok in STOP_TOKENS or tok in out:
            continue
        # reference codes that change every payment ("7YR06G") and ACH filler words
        if len(toks) > 1 and ((len(tok) >= 3 and re.search(r"\d", tok) and re.search(r"[A-Z]", tok))
                              or tok in ACH_NOISE):
            continue
        out.append(tok)
    while len(out) > 1 and out[-1] in STATES:
        out.pop()
    out = out[:2]
    if len(out) == 2 and out[1] in STATES:
        out = out[:1]
    return " ".join(out) or desc.upper()[:24]


def canonical(desc: str) -> tuple[str, str | None]:
    """Return (merchant name, brand category or None)."""
    b = brand_of(desc)
    if b:
        return b
    key = fallback_key(desc)
    return key.title().replace("'S", "'s"), None
