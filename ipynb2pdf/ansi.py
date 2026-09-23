"""ANSI escape sequence handling (strip, or convert SGR colors to HTML spans)."""
import html
import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")

_BASE = ["#000000", "#c62828", "#2e7d32", "#b26a00", "#1565c0", "#8e24aa", "#00838f", "#9e9e9e"]
_BRIGHT = ["#616161", "#e53935", "#43a047", "#f9a825", "#1e88e5", "#ab47bc", "#00acc1", "#bdbdbd"]


def _apply_cr(text: str) -> str:
    """Emulate carriage returns (progress bars): keep only text after the last \\r on each line."""
    out = []
    for line in text.split("\n"):
        if "\r" in line:
            line = line.split("\r")[-1]
        out.append(line)
    return "\n".join(out)


def strip_ansi(text: str) -> str:
    return _apply_cr(_ANSI_RE.sub("", text)).replace("\x08", "")


def _color256(n: int) -> str:
    if n < 8:
        return _BASE[n]
    if n < 16:
        return _BRIGHT[n - 8]
    if n < 232:
        n -= 16
        r, g, b = n // 36, (n // 6) % 6, n % 6
        conv = lambda v: 0 if v == 0 else 55 + v * 40
        return "#%02x%02x%02x" % (conv(r), conv(g), conv(b))
    v = 8 + (n - 232) * 10
    return "#%02x%02x%02x" % (v, v, v)


def _parse_sgr(params, state):
    codes = [int(p) if p else 0 for p in params.split(";")] if params else [0]
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0:
            state.clear()
        elif c == 1:
            state["bold"] = True
        elif c == 2:
            state["dim"] = True
        elif c == 3:
            state["italic"] = True
        elif c == 4:
            state["underline"] = True
        elif c == 22:
            state.pop("bold", None); state.pop("dim", None)
        elif c == 23:
            state.pop("italic", None)
        elif c == 24:
            state.pop("underline", None)
        elif 30 <= c <= 37:
            state["fg"] = _BASE[c - 30]
        elif 90 <= c <= 97:
            state["fg"] = _BRIGHT[c - 90]
        elif 40 <= c <= 47:
            state["bg"] = _BASE[c - 40]
        elif 100 <= c <= 107:
            state["bg"] = _BRIGHT[c - 100]
        elif c == 39:
            state.pop("fg", None)
        elif c == 49:
            state.pop("bg", None)
        elif c in (38, 48) and i + 1 < len(codes):
            key = "fg" if c == 38 else "bg"
            if codes[i + 1] == 5 and i + 2 < len(codes):
                state[key] = _color256(codes[i + 2]); i += 2
            elif codes[i + 1] == 2 and i + 4 < len(codes):
                state[key] = "#%02x%02x%02x" % (codes[i + 2], codes[i + 3], codes[i + 4]); i += 4
        i += 1


def _style_css(state) -> str:
    css = []
    if state.get("fg"): css.append("color:%s" % state["fg"])
    if state.get("bg"): css.append("background:%s" % state["bg"])
    if state.get("bold"): css.append("font-weight:bold")
    if state.get("italic"): css.append("font-style:italic")
    if state.get("underline"): css.append("text-decoration:underline")
    if state.get("dim"): css.append("opacity:.7")
    return ";".join(css)


def ansi_to_html(text: str) -> str:
    """Convert ANSI-colored text to escaped HTML with inline-styled spans."""
    text = _apply_cr(text).replace("\x08", "")
    out, state, pos = [], {}, 0
    for m in _SGR_RE.finditer(text):
        chunk = text[pos:m.start()]
        if chunk:
            css = _style_css(state)
            out.append('<span style="%s">%s</span>' % (css, html.escape(chunk)) if css else html.escape(chunk))
        _parse_sgr(m.group(1), state)
        pos = m.end()
    chunk = text[pos:]
    if chunk:
        css = _style_css(state)
        out.append('<span style="%s">%s</span>' % (css, html.escape(chunk)) if css else html.escape(chunk))
    return _ANSI_RE.sub("", "".join(out))


def ansi_to_segments(text: str):
    """Yield (text, state-dict) segments for non-HTML renderers."""
    text = _apply_cr(text).replace("\x08", "")
    state, pos = {}, 0
    for m in _SGR_RE.finditer(text):
        chunk = text[pos:m.start()]
        if chunk:
            yield _ANSI_RE.sub("", chunk), dict(state)
        _parse_sgr(m.group(1), state)
        pos = m.end()
    chunk = text[pos:]
    if chunk:
        yield _ANSI_RE.sub("", chunk), dict(state)
