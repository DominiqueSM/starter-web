"""Turn PDF pages into text lines that keep each word's horizontal position.

Positions let the parser tell columns apart (Debit vs Credit vs Balance) and put
spaces back between pieces of text that a plain text dump glues together
(e.g. "NETFLIX.COMNETFLIX.COMCA").
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pypdf import PdfReader
from pypdf.errors import DependencyError, FileNotDecryptedError, PdfReadError

log = logging.getLogger(__name__)


class PasswordRequired(Exception):
    pass


class UnsupportedEncryption(Exception):
    pass


@dataclass
class Word:
    x0: float
    x1: float
    text: str


@dataclass
class Line:
    page: int
    y: float
    words: list = field(default_factory=list)   # list[Word], sorted by x0; empty when positions are unknown
    raw: str = ""                               # used when positions are unknown
    size: float = 9.0                           # typical font size on the line

    @property
    def has_positions(self) -> bool:
        return bool(self.words)

    @property
    def text(self) -> str:
        if not self.words:
            return self.raw
        parts = [self.words[0].text]
        for prev, w in zip(self.words, self.words[1:]):
            # a wide gap means a new column: mark it with three spaces
            parts.append(("   " if w.x0 - prev.x1 > self.size * 1.2 else " ") + w.text)
        return "".join(parts)

    def text_between(self, x_start: float, x_end: float) -> str:
        return " ".join(w.text for w in self.words if w.x0 >= x_start - 1 and w.x1 <= x_end + 1)


def _split_fragment(tx: float, x_end: float, text: str) -> list[Word]:
    """Split one positioned fragment into words, estimating each word's position."""
    if not text.strip():
        return []
    n = len(text)
    cw = (x_end - tx) / n if n else 0
    words = []
    for m in re.finditer(r"\S+", text):
        words.append(Word(tx + m.start() * cw, tx + m.end() * cw, m.group()))
    return words


def _merge_touching(words: list[Word], space_width: float) -> list[Word]:
    """Join fragments that touch (no visible gap) into one word; keep a split where there is a gap."""
    if not words:
        return words
    words.sort(key=lambda w: w.x0)
    out = [words[0]]
    for w in words[1:]:
        last = out[-1]
        if w.x0 - last.x1 < space_width * 0.25:
            out[-1] = Word(last.x0, max(last.x1, w.x1), last.text + w.text)
        else:
            out.append(w)
    return out


def _page_lines_positioned(reader: PdfReader, page, page_no: int) -> list[Line]:
    from pypdf._text_extraction import _layout_mode  # pinned, bundled pypdf version
    from pypdf.generic import ArrayObject, ContentStream, StreamObject

    contents = page.get("/Contents")
    if contents is None:
        return []
    contents = contents.get_object()
    if not isinstance(contents, (ArrayObject, StreamObject)):
        return []
    fonts = page._layout_mode_fonts()
    ops = iter(ContentStream(contents, reader, "bytes").operations)
    groups = _layout_mode.text_show_operations(ops, fonts, True, None)
    if not groups:
        return []
    lines = []
    for ty, grp in sorted(_layout_mode.y_coordinate_groups(groups, None).items(), key=lambda kv: -kv[0]):
        words = []
        sizes = []
        for g in grp:
            words.extend(_split_fragment(g["tx"], g["displaced_tx"], g["text"]))
            sizes.append(g["font_size"] or 9)
        size = sorted(sizes)[len(sizes) // 2] if sizes else 9
        words = _merge_touching(words, size * 0.28)
        if words:
            lines.append(Line(page=page_no, y=float(ty), words=words, size=size))
    return lines


def open_reader(path: str, password: str | None = None) -> PdfReader:
    try:
        reader = PdfReader(path)
    except PdfReadError as e:
        raise ValueError(f"Not a readable PDF ({e})") from e
    if reader.is_encrypted:
        try:
            ok = reader.decrypt(password or "")
        except DependencyError as e:
            raise UnsupportedEncryption(
                "This PDF uses AES encryption. Open it and save/print a copy without a password, "
                "or install the 'cryptography' Python package.") from e
        if not ok:
            raise PasswordRequired("This PDF is password-protected.")
    return reader


def extract_lines(path: str, password: str | None = None) -> tuple[list[Line], int, str]:
    """Return (lines, page_count, method). method is 'positioned' or 'plain'."""
    reader = open_reader(path, password)
    lines: list[Line] = []
    methods = set()
    try:
        n_pages = len(reader.pages)
    except FileNotDecryptedError as e:
        raise PasswordRequired("This PDF is password-protected.") from e
    for i, page in enumerate(reader.pages):
        page_lines = []
        try:
            page_lines = _page_lines_positioned(reader, page, i)
            if page_lines:
                methods.add("positioned")
        except Exception as e:  # fall back to plain text for odd pages
            log.info("positioned extraction failed on %s p%d: %s", path, i + 1, e)
        if not page_lines:
            try:
                txt = page.extract_text() or ""
            except Exception as e:
                log.info("plain extraction failed on %s p%d: %s", path, i + 1, e)
                txt = ""
            page_lines = [Line(page=i, y=-k, raw=t) for k, t in enumerate(txt.splitlines()) if t.strip()]
            if page_lines:
                methods.add("plain")
        lines.extend(page_lines)
    method = "positioned" if methods == {"positioned"} else ("plain" if methods == {"plain"} else "mixed")
    return lines, n_pages, method
