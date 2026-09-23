"""Tiny HTML helpers for the native engine: table extraction and text extraction."""
import html
import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple

_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "section", "article", "ul", "ol", "blockquote", "hr"}


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: List[dict] = []
        self._stack: List[dict] = []
        self._cell: Optional[dict] = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "script"):
            self._skip += 1
        elif tag == "table":
            self._stack.append({"rows": [], "in_head": False, "n_head": 0})
        elif not self._stack:
            return
        elif tag == "thead":
            self._stack[-1]["in_head"] = True
        elif tag == "tr":
            self._stack[-1]["rows"].append({"cells": [], "head": self._stack[-1]["in_head"]})
        elif tag in ("td", "th"):
            if not self._stack[-1]["rows"]:
                self._stack[-1]["rows"].append({"cells": [], "head": False})
            self._cell = {"text": [], "th": tag == "th", "colspan": int(a.get("colspan") or 1)}
            self._stack[-1]["rows"][-1]["cells"].append(self._cell)
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th"):
            self._cell = None
        elif tag == "thead" and self._stack:
            self._stack[-1]["in_head"] = False
        elif tag == "table" and self._stack:
            t = self._stack.pop()
            rows = []
            n_head = 0
            for r in t["rows"]:
                cells = []
                for c in r["cells"]:
                    txt = "".join(c["text"])
                    txt = re.sub(r"[ \t]+", " ", txt).strip()
                    cells.append((txt, c["th"]))
                    for _ in range(c["colspan"] - 1):
                        cells.append(("", c["th"]))
                if r["head"] or (cells and all(h for _, h in cells)):
                    if len(rows) == n_head:
                        n_head += 1
                rows.append(cells)
            if rows:
                self.tables.append({"rows": rows, "n_head": n_head})

    def handle_data(self, data):
        if self._skip:
            return
        if self._cell is not None:
            self._cell["text"].append(data)


def extract_tables(html_text: str) -> List[dict]:
    """Return list of {'rows': [[(text, is_header), ...]], 'n_head': int}."""
    p = _TableParser()
    try:
        p.feed(html_text)
        p.close()
    except Exception:
        pass
    return p.tables


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.images: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self._skip += 1
        elif tag == "img":
            src = dict(attrs).get("src")
            if src:
                self.images.append(src)
                self.parts.append("\ue010%d\ue011" % (len(self.images) - 1))
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in ("b", "strong"):
            self.parts.append("<b>")
        elif tag in ("i", "em"):
            self.parts.append("<i>")
        elif tag == "u":
            self.parts.append("<u>")
        elif tag in ("s", "strike", "del"):
            self.parts.append("<strike>")
        elif tag == "sup":
            self.parts.append("<sup>")
        elif tag == "sub":
            self.parts.append("<sub>")
        elif tag == "code":
            self.parts.append("<code>")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in ("b", "strong"):
            self.parts.append("</b>")
        elif tag in ("i", "em"):
            self.parts.append("</i>")
        elif tag == "u":
            self.parts.append("</u>")
        elif tag in ("s", "strike", "del"):
            self.parts.append("</strike>")
        elif tag == "sup":
            self.parts.append("</sup>")
        elif tag == "sub":
            self.parts.append("</sub>")
        elif tag == "code":
            self.parts.append("</code>")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(html.escape(data, quote=False))


def html_to_markup(html_text: str) -> Tuple[str, List[str]]:
    """Convert arbitrary HTML into ReportLab-ish paragraph markup (only safe inline tags kept).

    Returns (markup, image_srcs). Image positions are marked with \\ue010<idx>\\ue011.
    Block boundaries become newlines."""
    p = _TextParser()
    try:
        p.feed(html_text)
        p.close()
    except Exception:
        return html.escape(re.sub(r"<[^>]+>", "", html_text), quote=False), []
    text = "".join(p.parts)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
    return text, p.images


def is_probably_html(s: str) -> bool:
    return bool(re.search(r"<\s*[a-zA-Z][^>]*>", s))
