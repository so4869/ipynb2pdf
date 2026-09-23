"""Notebook loading and image resolution helpers."""
import base64
import mimetypes
import os
import re
import urllib.parse
import urllib.request
from typing import Optional, Tuple

import nbformat


def load_notebook(path: str):
    with open(path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)
    # normalise sources to str
    for cell in nb.cells:
        if isinstance(cell.get("source"), list):
            cell["source"] = "".join(cell["source"])
        for out in cell.get("outputs", []) or []:
            if isinstance(out.get("text"), list):
                out["text"] = "".join(out["text"])
            for k, v in list((out.get("data") or {}).items()):
                if isinstance(v, list) and not k.startswith("application/json"):
                    out["data"][k] = "".join(v)
    return nb


def notebook_language(nb) -> str:
    md = nb.get("metadata", {}) or {}
    lang = (md.get("language_info") or {}).get("name") or (md.get("kernelspec") or {}).get("language")
    return (lang or "python").lower()


_DATA_URI_RE = re.compile(r"^data:([^;,]+)(;base64)?,(.*)$", re.S)


def decode_data_uri(uri: str) -> Optional[Tuple[bytes, str]]:
    m = _DATA_URI_RE.match(uri.strip())
    if not m:
        return None
    mime, is_b64, payload = m.group(1), m.group(2), m.group(3)
    if is_b64:
        try:
            return base64.b64decode(payload), mime
        except Exception:
            return None
    return urllib.parse.unquote_to_bytes(payload), mime


def guess_mime(path_or_url: str, default: str = "image/png") -> str:
    mime, _ = mimetypes.guess_type(path_or_url.split("?")[0])
    return mime or default


def resolve_image(src: str, nb_dir: str, attachments: Optional[dict] = None,
                  fetch_remote: bool = True, timeout: float = 15.0) -> Optional[Tuple[bytes, str]]:
    """Return (bytes, mime) for an image reference used in markdown/html, or None."""
    src = (src or "").strip()
    if not src:
        return None
    if src.startswith("data:"):
        return decode_data_uri(src)
    if src.startswith("attachment:"):
        name = urllib.parse.unquote(src[len("attachment:"):])
        att = (attachments or {}).get(name)
        if not att:
            return None
        for mime, b64 in att.items():
            try:
                return base64.b64decode(b64), mime
            except Exception:
                continue
        return None
    if re.match(r"^https?://", src, re.I):
        if not fetch_remote:
            return None
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0 ipynb2pdf"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                mime = r.headers.get_content_type() or guess_mime(src)
                if not mime.startswith("image/"):
                    mime = guess_mime(src)
                return data, mime
        except Exception:
            return None
    if src.startswith("file://"):
        src = urllib.request.url2pathname(urllib.parse.urlparse(src).path)
    path = urllib.parse.unquote(src)
    if not os.path.isabs(path):
        path = os.path.join(nb_dir, path)
    if os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                return f.read(), guess_mime(path)
        except Exception:
            return None
    return None


def to_data_uri(data: bytes, mime: str) -> str:
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))
