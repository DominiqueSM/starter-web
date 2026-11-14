"""One file with every choice you made, to move to another computer or recover after a reinstall."""
from __future__ import annotations

import json
from datetime import datetime

APP_ID = "spending-analyzer"
VERSION = 1
# settings that are your choices (window size and the last folder are not)
CHOICE_KEYS = ["excluded", "direction_flips", "tx_categories", "not_duplicates", "include_files", "budgets",
               "tag_rules", "debts", "debt_extra", "debt_strategy", "date_order"]


def make_backup(settings: dict, categorizer) -> dict:
    try:
        with open(categorizer.rules_path, "r", encoding="utf-8") as f:
            keyword_rules = json.load(f)
    except Exception:
        keyword_rules = None
    return {"app": APP_ID, "version": VERSION, "created": datetime.now().isoformat(timespec="seconds"),
            "settings": {k: settings[k] for k in CHOICE_KEYS if k in settings},
            "company_categories": categorizer.overrides, "contains_rules": categorizer.user_rules,
            "keyword_rules": keyword_rules}


def summarize(data: dict) -> str:
    s = data.get("settings", {})
    parts = [f"{len(data.get('company_categories', {}))} company categories",
             f"{len(data.get('contains_rules', []))} 'contains' rules",
             f"{len(s.get('budgets', {}))} budgets", f"{len(s.get('tag_rules', []))} tag rules",
             f"{len(s.get('debts', {}))} debts", f"{len(s.get('excluded', []))} exclusions"]
    return ", ".join(parts)


def validate(data) -> str | None:
    """None if this looks like our backup, else the reason it can't be used."""
    if not isinstance(data, dict) or data.get("app") != APP_ID:
        return "This file isn't a Spending Analyzer backup."
    if not isinstance(data.get("version"), int) or data["version"] > VERSION:
        return "This backup was made by a newer version of the app."
    if not isinstance(data.get("settings", {}), dict) or not isinstance(data.get("company_categories", {}), dict) \
            or not isinstance(data.get("contains_rules", []), list):
        return "This backup file is damaged."
    return None


def restore(data: dict, settings: dict, categorizer) -> None:
    """Replace your choices with the backup's. Window size and the last folder stay as they are."""
    for k in CHOICE_KEYS:
        settings.pop(k, None)
    settings.update({k: v for k, v in data.get("settings", {}).items() if k in CHOICE_KEYS})
    categorizer.replace_all(data.get("company_categories", {}), data.get("contains_rules", []),
                            data.get("keyword_rules"))
