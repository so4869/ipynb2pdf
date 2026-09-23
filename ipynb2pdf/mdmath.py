"""Extract LaTeX math from markdown before markdown parsing.

Math is replaced by private-use-area placeholders which survive markdown
rendering untouched; the engines then substitute rendered math back in.
"""
import re
from typing import List, Tuple

PH_START, PH_END = "\ue000", "\ue001"
_PH_RE = re.compile(PH_START + r"(\d+)" + PH_END)
_CODE_START, _CODE_END = "\ue002", "\ue003"
_CODE_RE = re.compile(_CODE_START + r"(\d+)" + _CODE_END)

_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^\1\2[ \t]*$|\Z)", re.M)
_INLINE_CODE_RE = re.compile(r"(`+)(?!`)([\s\S]*?[^`])\1(?!`)")

_ENVS = r"(?:equation\*?|align\*?|aligned|alignat\*?|gather\*?|gathered|eqnarray\*?|multline\*?|flalign\*?|split|displaymath|math)"

_MATH_PATTERNS = [
    ("display", re.compile(r"\$\$([\s\S]+?)\$\$")),
    ("display", re.compile(r"\\\[([\s\S]+?)\\\]")),
    ("display", re.compile(r"\\begin\{(" + _ENVS + r")\}[\s\S]+?\\end\{\1\}")),
    ("inline", re.compile(r"\\\(([\s\S]+?)\\\)")),
    # pandoc-style rules: opening $ must not be followed by space, closing $ must not be
    # preceded by space nor followed by a digit ("$5 and $6" is not math, "$x$한글" is)
    ("inline", re.compile(r"(?<![\\$])\$(?![\s$])((?:\\.|[^$\\\n]|\n(?!\n))+?)(?<![\s\\])\$(?![\d$])")),
]

MathList = List[Tuple[str, str]]  # (kind, tex)


def extract_math(text: str, mathlist: MathList) -> str:
    """Replace math in *text* (markdown) with placeholders; append (kind, tex) to mathlist."""
    if not text:
        return text
    pieces = []
    pos = 0
    for m in _FENCE_RE.finditer(text):
        pieces.append(_extract_in_text(text[pos:m.start()], mathlist))
        pieces.append(m.group(0))
        pos = m.end()
    pieces.append(_extract_in_text(text[pos:], mathlist))
    return "".join(pieces)


def _extract_in_text(text: str, mathlist: MathList) -> str:
    if not text:
        return text
    codes: List[str] = []

    def _protect(m):
        codes.append(m.group(0))
        return _CODE_START + str(len(codes) - 1) + _CODE_END

    text = _INLINE_CODE_RE.sub(_protect, text)
    for kind, pat in _MATH_PATTERNS:
        def _repl(m, kind=kind, pat=pat):
            whole = m.group(0)
            if pat.pattern.startswith(r"\\begin"):
                tex = whole  # keep environment
            else:
                tex = m.group(1)
            mathlist.append((kind, tex.strip("\n") if kind == "display" else tex))
            idx = len(mathlist) - 1
            if kind == "display":
                return "\n\n" + PH_START + str(idx) + PH_END + "\n\n" if _standalone(text, m) else PH_START + str(idx) + PH_END
            return PH_START + str(idx) + PH_END
        text = pat.sub(_repl, text)
    text = _CODE_RE.sub(lambda m: codes[int(m.group(1))], text)
    return text


def _standalone(text: str, m) -> bool:
    """True if the display-math match is alone on its line(s)."""
    before = text[:m.start()].rsplit("\n", 1)[-1]
    after = text[m.end():].split("\n", 1)[0]
    return before.strip() == "" and after.strip() == ""


def split_placeholders(text: str):
    """Yield ('text', str) or ('math', idx) pieces."""
    pos = 0
    for m in _PH_RE.finditer(text):
        if m.start() > pos:
            yield "text", text[pos:m.start()]
        yield "math", int(m.group(1))
        pos = m.end()
    if pos < len(text):
        yield "text", text[pos:]


def has_placeholder(text: str) -> bool:
    return bool(_PH_RE.search(text))


def strip_math_env(tex: str) -> str:
    """Remove outer equation-like environment wrappers that only affect numbering."""
    t = tex.strip()
    m = re.match(r"^\\begin\{(equation\*?|displaymath|math)\}([\s\S]*)\\end\{\1\}$", t)
    if m:
        return m.group(2).strip()
    return t
