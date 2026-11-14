"""Find statement PDFs in a folder and parse them (with a cache keyed by file content)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from .parser import PARSER_VERSION, LineDiag, StatementInfo, Transaction, parse_statement
from .pdftext import PasswordRequired, UnsupportedEncryption, extract_lines
from .tabular import TABULAR_EXTS, parse_tabular

log = logging.getLogger(__name__)

__all__ = ["Transaction", "FileResult", "process_folder", "find_statements"]


@dataclass
class FileResult:
    path: str
    status: str = "ok"     # ok | no-text | no-transactions | error | duplicate | password
    pages: int = 0
    transactions: list = field(default_factory=list)
    note: str = ""
    group: str = ""
    info: StatementInfo = field(default_factory=StatementInfo)
    diags: list = field(default_factory=list)
    method: str = ""
    sha1: str = ""
    duplicates_removed: int = 0
    held: list = field(default_factory=list)   # rows from a non-statement document, not counted unless included


def file_hash(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def find_statements(folder: str) -> list[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fn in files:
            if fn.lower().endswith((".pdf",) + TABULAR_EXTS) and not fn.startswith("."):
                out.append(os.path.join(root, fn))
    return sorted(out)


# ------------------------------------------------------------------ cache

def _ser_info(i: StatementInfo) -> dict:
    d = asdict(i)
    for k in ("period_start", "period_end"):
        d[k] = d[k].isoformat() if d[k] else None
    return d


def _de_info(d: dict) -> StatementInfo:
    for k in ("period_start", "period_end"):
        d[k] = date.fromisoformat(d[k]) if d.get(k) else None
    return StatementInfo(**d)


def _cache_load(cache_dir, sha, order_pref):
    if not cache_dir:
        return None
    p = os.path.join(cache_dir, sha + ".json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("v") != PARSER_VERSION or d.get("order") != order_pref:
            return None
        txs = []
        for t in d["txs"]:
            t["date"] = date.fromisoformat(t["date"])
            txs.append(Transaction(**t))
        return dict(txs=txs, info=_de_info(d["info"]), diags=[LineDiag(**x) for x in d["diags"]],
                    pages=d["pages"], method=d["method"], status=d["status"], note=d["note"])
    except Exception:
        return None


def _cache_save(cache_dir, sha, order_pref, fr: FileResult):
    if not cache_dir:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        txs = []
        for t in fr.transactions:
            d = asdict(t)
            d["date"] = t.date.isoformat()
            txs.append(d)
        data = dict(v=PARSER_VERSION, order=order_pref, txs=txs, info=_ser_info(fr.info),
                    diags=[asdict(x) for x in fr.diags], pages=fr.pages, method=fr.method, status=fr.status,
                    note=fr.note)
        tmp = os.path.join(cache_dir, sha + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, os.path.join(cache_dir, sha + ".json"))
    except Exception as e:
        log.warning("cache write failed: %s", e)


# ------------------------------------------------------------------ main

def parse_file(path: str, sha: str, order_pref="auto", password=None, cache_dir=None) -> FileResult:
    fr = FileResult(path=path, sha1=sha)
    if path.lower().endswith(TABULAR_EXTS):   # bank downloads: quick to read, no cache needed
        fr.transactions, fr.info, fr.diags, fr.method = parse_tabular(path)
        if not fr.transactions:
            fr.status = "no-transactions"
            fr.note = fr.info.recon_detail or "No transactions found in this file. See the line preview."
        return fr
    cached = _cache_load(cache_dir, sha, order_pref) if not password else None
    if cached:
        fr.transactions, fr.info, fr.diags = cached["txs"], cached["info"], cached["diags"]
        fr.pages, fr.method, fr.status, fr.note = cached["pages"], cached["method"], cached["status"], cached["note"]
        for t in fr.transactions:
            t.source_file = path
        return _hold_if_not_statement(fr)
    try:
        lines, fr.pages, fr.method = extract_lines(path, password)
    except PasswordRequired as e:
        fr.status, fr.note = "password", str(e)
        return fr
    except UnsupportedEncryption as e:
        fr.status, fr.note = "error", str(e)
        return fr
    if sum(len(l.text) for l in lines) < 20:
        fr.status = "no-text"
        fr.note = "No selectable text (probably a scanned image). Download a text-based PDF from your bank instead."
        _cache_save(cache_dir, sha, order_pref, fr)
        return fr
    fallback_year = datetime.fromtimestamp(os.path.getmtime(path)).year
    fr.transactions, fr.info, fr.diags = parse_statement(lines, path, fallback_year, order_pref)
    if not fr.transactions:
        fr.status = "no-transactions"
        fr.note = "Text found, but no rows that look like 'date  description  amount'. See the line preview."
    elif any(t.year_guessed for t in fr.transactions):
        fr.note = "Statement period not found; year taken from the file's date."
    elif fr.info.doc_type == "other" and fr.info.recon_status not in ("reconciled", "balance-verified"):
        fr.status = "not-statement"
        fr.note = (f"Looks like {fr.info.doc_reason}, not a bank or card statement, so it's skipped: the same "
                   "charges are already on your statements and would be counted twice. Use 'Include anyway' "
                   "if this is a real statement.")
    if not password:   # don't cache contents of password-protected files
        _cache_save(cache_dir, sha, order_pref, fr)
    return _hold_if_not_statement(fr)


def _hold_if_not_statement(fr: FileResult) -> FileResult:
    if fr.status == "not-statement":
        fr.held, fr.transactions = fr.transactions, []
    return fr


def process_folder(folder: str, progress=None, passwords=None, cache_dir=None, order_pref="auto") -> list[FileResult]:
    passwords = passwords or {}
    results = []
    seen = {}
    pdfs = find_statements(folder)
    for i, path in enumerate(pdfs):
        if progress:
            progress(i, len(pdfs), os.path.basename(path))
        try:
            sha = file_hash(path)
            if sha in seen:
                fr = FileResult(path=path, status="duplicate", sha1=sha,
                                note="Identical to " + os.path.relpath(seen[sha], folder) + " (skipped)")
            else:
                seen[sha] = path
                fr = parse_file(path, sha, order_pref, passwords.get(path), cache_dir)
        except Exception as e:
            log.exception("failed on %s", path)
            fr = FileResult(path=path, status="error", note=f"{type(e).__name__}: {str(e)[:200]}")
        results.append(fr)
    if progress:
        progress(len(pdfs), len(pdfs), "")
    return results
