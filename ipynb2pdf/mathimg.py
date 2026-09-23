"""Render LaTeX math to PNG images with matplotlib's mathtext (no TeX installation needed).

mathtext lacks environments (align, cases, matrices ...), so those are typeset here by
rendering each cell with mathtext and composing the grid (plus delimiters) with Pillow.
CJK text inside math (e.g. \\text{한글}) is rendered with the bundled Korean font.
"""
import hashlib
import os
import re
from typing import List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")


def _install_portable_font_cache():
    """Avoid matplotlib's slow system-font scan (30s+ on first run of the frozen exe):
    if no font cache exists yet, install the bundled one that lists only matplotlib's own fonts."""
    try:
        import json
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "mpl_fontlist.json")
        try:
            from . import resources as _res
            src = _res.resource_path("mpl_fontlist.json")
        except Exception:
            pass
        if not os.path.isfile(src):
            return
        with open(src, "r", encoding="utf-8") as f:
            version = json.load(f).get("_version")
        if not version:
            return
        cache_dir = matplotlib.get_cachedir()
        dst = os.path.join(cache_dir, "fontlist-v%s.json" % version)
        if os.path.exists(dst):
            return
        os.makedirs(cache_dir, exist_ok=True)
        import shutil
        shutil.copyfile(src, dst)
    except Exception:
        pass


_install_portable_font_cache()
from matplotlib import font_manager  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.mathtext import MathTextParser  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from . import resources  # noqa: E402

_CJK_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]+")

# --------------------------------------------------------------------------- preprocessing
_SIMPLE_SUBS = [
    (re.compile(r"\\(?:displaystyle|textstyle|scriptstyle|scriptscriptstyle|nonumber|notag|limits|nolimits|mathstrut|allowbreak|strut)(?![a-zA-Z])"), ""),
    (re.compile(r"\\(?:tag\*?|label|vspace\*?|hphantom|vphantom|phantom|ref|eqref|hspace\*?)\{[^{}]*\}"), ""),
    (re.compile(r"\\(?:big|Big|bigg|Bigg)(?:l|r|m)?(?=\s*(?:[()\[\]|/.<>]|\\[{}|]|\\l?angle|\\r?angle|\\l?vert|\\r?vert|\\l?Vert|\\r?Vert|\\lfloor|\\rfloor|\\lceil|\\rceil|\\lbrace|\\rbrace))"), ""),
    (re.compile(r"\\implies(?![a-zA-Z])"), r"\\Rightarrow"),
    (re.compile(r"\\impliedby(?![a-zA-Z])"), r"\\Leftarrow"),
    (re.compile(r"\\iff(?![a-zA-Z])"), r"\\Leftrightarrow"),
    (re.compile(r"\\to(?![a-zA-Z])"), r"\\rightarrow"),
    (re.compile(r"\\gets(?![a-zA-Z])"), r"\\leftarrow"),
    (re.compile(r"\\ge(?![a-zA-Z])"), r"\\geq"),
    (re.compile(r"\\le(?![a-zA-Z])"), r"\\leq"),
    (re.compile(r"\\ne(?![a-zA-Z])"), r"\\neq"),
    (re.compile(r"\\land(?![a-zA-Z])"), r"\\wedge"),
    (re.compile(r"\\lor(?![a-zA-Z])"), r"\\vee"),
    (re.compile(r"\\lnot(?![a-zA-Z])"), r"\\neg"),
    (re.compile(r"\\[lr]Vert(?![a-zA-Z])"), r"\\|"),
    (re.compile(r"\\[lr]vert(?![a-zA-Z])"), "|"),
    (re.compile(r"\\middle(?![a-zA-Z])"), ""),
    (re.compile(r"\\colon(?![a-zA-Z])"), ":"),
    (re.compile(r"\\varnothing(?![a-zA-Z])"), r"\\emptyset"),
    (re.compile(r"\\dots(?![a-zA-Z])"), r"\\ldots"),
    (re.compile(r"\\dots[cbmio](?![a-zA-Z])"), r"\\cdots"),
    (re.compile(r"\\newline(?![a-zA-Z])"), r"\\\\"),
    (re.compile(r"\\operatorname\*?\s*\{"), r"\\mathrm{"),
    (re.compile(r"\\text(bf|it|tt|rm|sf)\s*\{"), r"\\math\1{"),
    (re.compile(r"\\textnormal\s*\{"), r"\\mathrm{"),
    (re.compile(r"\\emph\s*\{"), r"\\mathit{"),
    (re.compile(r"\\(?:mbox|hbox|textup)\s*\{"), r"\\text{"),
    (re.compile(r"\\bmod(?![a-zA-Z])"), r"\\ \\mathrm{mod}\\ "),
    (re.compile(r"\\pmod\s*\{([^{}]*)\}"), r"\\ (\\mathrm{mod}\\ \1)"),
    (re.compile(r"\\xrightarrow\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}"), r"\\overset{\1}{\\longrightarrow}"),
    (re.compile(r"\\xleftarrow\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}"), r"\\overset{\1}{\\longleftarrow}"),
    (re.compile(r"\\substack\s*\{([^{}\\]*)\\\\([^{}]*)\}"), r"\\genfrac{}{}{0}{}{\1}{\2}"),
    (re.compile(r"\\&"), "&"),
    (re.compile(r"(?<!\\)~"), r"\\ "),
    (re.compile(r"\\(?:hline|cline\{[^}]*\})"), ""),
    (re.compile(r"\\(?:quad|qquad)(?![a-zA-Z])"), lambda m: m.group(0)),  # keep
    (re.compile(r"\\(?:mathop|mathbin|mathrel|mathord|mathpunct|mathinner|smash|cancel|bcancel|xcancel|boxed|underbracket|overbracket)\s*\{"), "{"),
    (re.compile(r"\\textcolor\s*\{[^{}]*\}\s*\{"), "{"),
    (re.compile(r"\\color\s*\{[^{}]*\}"), ""),
    (re.compile(r"\\underbrace\s*\{([^{}]*)\}\s*_\s*\{([^{}]*)\}"), r"\\underset{\2}{\\underline{\1}}"),
    (re.compile(r"\\underbrace\s*\{"), r"\\underline{"),
    (re.compile(r"\\overbrace\s*\{([^{}]*)\}\s*\^\s*\{([^{}]*)\}"), r"\\overset{\2}{\\overline{\1}}"),
    (re.compile(r"\\overbrace\s*\{"), r"\\overline{"),
    (re.compile(r"\\stackrel\s*\{"), r"\\overset{"),
    (re.compile(r"\\intertext\s*\{[^{}]*\}"), ""),
]


def preprocess(tex: str) -> str:
    t = re.sub(r"\s*\n\s*", " ", tex)
    for pat, rep in _SIMPLE_SUBS:
        t = pat.sub(rep, t)
    # balance \left / \right (fragments produced by splitting around environments)
    nl, nr = len(re.findall(r"\\left\b", t)), len(re.findall(r"\\right\b", t))
    if nl > nr:
        t += " \\right." * (nl - nr)
    elif nr > nl:
        t = "\\left. " * (nr - nl) + t
    # balance braces
    depth = 0
    out = []
    for ch in t:
        if ch == "{":
            depth += 1
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
        out.append(ch)
    t = "".join(out) + "}" * depth
    return t.strip()


# --------------------------------------------------------------------------- env splitting
_BEGIN_RE = re.compile(r"\\begin\s*\{([a-zA-Z]+\*?)\}")
_TEXT_RE = re.compile(r"\\(?:text|mbox|hbox|textrm|textnormal|textbf|textit|mathrm)\s*\{")

ROW_ENVS = {"align", "align*", "aligned", "alignat", "alignat*", "alignedat", "flalign", "flalign*", "split",
            "eqnarray", "eqnarray*", "gather", "gather*", "gathered", "multline", "multline*", "cases", "dcases", "rcases",
            "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "array", "subarray",
            "matrix*", "pmatrix*", "bmatrix*", "Bmatrix*", "vmatrix*", "Vmatrix*"}
WRAP_ENVS = {"equation", "equation*", "displaymath", "math", "subequations"}


def _match_brace(s: str, i: int) -> int:
    """s[i] == '{'; return index of matching '}' (or len(s))."""
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(s)


def _find_env(tex: str):
    m = _BEGIN_RE.search(tex)
    if not m:
        return None
    name = m.group(1)
    body_start = m.end()
    # optional args: [t] or {ccc}
    opt = ""
    rest = tex[body_start:]
    mo = re.match(r"\s*(\[[^\]]*\])?\s*(\{[^{}]*\})?", rest) if name in ("array", "subarray", "alignat", "alignat*", "alignedat") or name.endswith("matrix*") else re.match(r"\s*(\[[^\]]*\])?", rest)
    if mo:
        opt = (mo.group(2) if mo.lastindex and mo.lastindex >= 2 and mo.group(2) else "") or (mo.group(1) or "")
        body_start += mo.end()
    depth = 1
    pos = body_start
    pat = re.compile(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}")
    while True:
        m2 = pat.search(tex, pos)
        if not m2:
            return m.start(), len(tex), name, tex[body_start:], opt
        if m2.group(1) == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.start(), m2.end(), name, tex[body_start:m2.start()], opt
        pos = m2.end()


def _split_top(s: str, sep_re) -> List[str]:
    """Split on separator regex at brace/env depth 0."""
    parts, buf, i, depth = [], [], 0, 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = _BEGIN_RE.match(s, i)
            if m:
                depth += 1
                buf.append(m.group(0)); i = m.end(); continue
            m = re.match(r"\\end\s*\{[a-zA-Z]+\*?\}", s[i:])
            if m:
                depth -= 1
                buf.append(m.group(0)); i += m.end(); continue
            if depth == 0:
                m = sep_re.match(s, i)
                if m:
                    parts.append("".join(buf)); buf = []; i = m.end(); continue
            buf.append(s[i:i + 2]); i += 2; continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif depth == 0:
            m = sep_re.match(s, i)
            if m:
                parts.append("".join(buf)); buf = []; i = m.end(); continue
        buf.append(c); i += 1
    parts.append("".join(buf))
    return parts


_ROW_SEP = re.compile(r"\\\\(?:\[[^\]]*\])?|\\cr(?![a-zA-Z])")
_COL_SEP = re.compile(r"&")
_LEFT_RE = re.compile(r"\\left\s*(\(|\[|\\\{|\\lbrace|\||\\\||\\lvert|\\lVert|\\vert|\\Vert|\.)\s*$")
_RIGHT_RE = re.compile(r"^\s*\\right\s*(\)|\]|\\\}|\\rbrace|\||\\\||\\rvert|\\rVert|\\vert|\\Vert|\.)")
_DELIM_MAP = {"(": "(", ")": ")", "[": "[", "]": "]", "\\{": "{", "\\}": "}", "\\lbrace": "{", "\\rbrace": "}",
              "|": "|", "\\|": "‖", "\\lvert": "|", "\\rvert": "|", "\\vert": "|", "\\lVert": "‖", "\\rVert": "‖", "\\Vert": "‖", ".": ""}


# --------------------------------------------------------------------------- image helpers
def _blank(w: int, h: int) -> Image.Image:
    return Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))


def _hconcat(parts: List[Tuple[Image.Image, float]], gap: int) -> Tuple[Image.Image, float]:
    if not parts:
        return _blank(1, 1), 0
    asc = max(p.height - d for p, d in parts)
    dep = max(d for _, d in parts)
    W = sum(p.width for p, _ in parts) + gap * (len(parts) - 1)
    out = _blank(W, asc + dep)
    x = 0
    for img, d in parts:
        y = int(round(asc - (img.height - d)))
        out.alpha_composite(img, (x, y))
        x += img.width + gap
    return out, dep


def _colorize(mask: np.ndarray, color=(0, 0, 0)) -> Image.Image:
    h, w = mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = color
    rgba[..., 3] = mask
    return Image.fromarray(rgba, "RGBA")


# --------------------------------------------------------------------------- renderer
class MathImage:
    __slots__ = ("path", "width", "height", "depth")

    def __init__(self, path: str, width: float, height: float, depth: float):
        self.path, self.width, self.height, self.depth = path, width, height, depth  # points


class MathRenderer:
    def __init__(self, out_dir: str, dpi: int = 300, fontsize: float = 10.5, display_fontsize: float = 12.0,
                 fontset: str = "cm"):
        self.out_dir, self.dpi, self.fontsize, self.display_fontsize = out_dir, dpi, fontsize, display_fontsize
        self.fontset = fontset
        self.parser = MathTextParser("agg")
        os.makedirs(out_dir, exist_ok=True)
        self._pil_fonts = {}
        self._cache = {}

    # --- public
    def render(self, tex: str, display: bool = False, color=(0, 0, 0)) -> Optional[MathImage]:
        key = (tex, display, color)
        if key in self._cache:
            return self._cache[key]
        size = self.display_fontsize if display else self.fontsize
        try:
            img, depth = self._render_tex(tex, size, color)
        except Exception:
            self._cache[key] = None
            return None
        if img.width < 2 or img.height < 2:
            self._cache[key] = None
            return None
        name = hashlib.md5(("%s|%s|%s" % (tex, display, color)).encode("utf-8")).hexdigest()[:16] + ".png"
        path = os.path.join(self.out_dir, name)
        img.save(path, "PNG")
        scale = 72.0 / self.dpi
        mi = MathImage(path, img.width * scale, img.height * scale, depth * scale)
        self._cache[key] = mi
        return mi

    # --- internals
    def _px(self, size_pt: float) -> float:
        return size_pt * self.dpi / 72.0

    def _mathtext(self, tex: str, size: float, color) -> Tuple[Image.Image, float]:
        tex = preprocess(tex)
        if not tex:
            return _blank(1, 1), 0
        last = None
        for fs in (self.fontset, "dejavusans"):
            try:
                r = self.parser.parse("$" + tex + "$", dpi=self.dpi, prop=FontProperties(size=size, math_fontfamily=fs))
                mask = np.asarray(r.image)
                return _colorize(mask, color), float(r.depth)
            except Exception as e:  # noqa: BLE001
                last = e
        raise last  # type: ignore[misc]

    def _pil_font(self, size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = (round(size, 1), bold)
        if key not in self._pil_fonts:
            self._pil_fonts[key] = ImageFont.truetype(resources.font_path("sans-bold" if bold else "sans"), int(round(self._px(size))))
        return self._pil_fonts[key]

    def _text(self, s: str, size: float, color, bold=False) -> Tuple[Image.Image, float]:
        font = self._pil_font(size, bold)
        asc, desc = font.getmetrics()
        w = int(font.getlength(s)) + 2
        img = _blank(w, asc + desc)
        ImageDraw.Draw(img).text((1, 0), s, font=font, fill=color + (255,))
        return img, float(desc)

    def _render_tex(self, tex: str, size: float, color) -> Tuple[Image.Image, float]:
        """Recursively split around environments / CJK text and compose."""
        tex = tex.strip()
        if not tex:
            return _blank(1, 1), 0
        env = _find_env(tex)
        # \text{...CJK...}
        tm = None
        for m in _TEXT_RE.finditer(tex):
            end = _match_brace(tex, m.end() - 1)
            if _CJK_RE.search(tex[m.end():end]):
                tm = (m.start(), end + 1, tex[m.end():end], "text{" in m.group(0) or "mbox" in m.group(0) or "hbox" in m.group(0))
                break
        cm = _CJK_RE.search(tex)
        cands = []
        if env:
            cands.append((env[0], "env"))
        if tm:
            cands.append((tm[0], "text"))
        if cm and not (tm and tm[0] <= cm.start() < tm[1]):
            cands.append((cm.start(), "cjk"))
        if not cands:
            return self._mathtext(tex, size, color)
        start, kind = min(cands)
        pre_extra = post_extra = None
        if kind == "env":
            s, e, name, inner, opt = env
            pre, post = tex[:s], tex[e:]
            delims = None
            ml = _LEFT_RE.search(pre)
            mr = _RIGHT_RE.match(post)
            if ml and mr and name.rstrip("*") in ("matrix", "array", "smallmatrix", "aligned", "gathered", "subarray"):
                delims = (_DELIM_MAP.get(ml.group(1), ""), _DELIM_MAP.get(mr.group(1), ""))
                pre_extra, post_extra = pre[:ml.start()], post[mr.end():]
            mid = self._render_env(name, inner, opt, size, color, delims)
        elif kind == "text":
            s, e, content, _ = tm
            mid = self._text(content, size, color)
        else:
            s, e = cm.start(), cm.end()
            mid = self._text(tex[s:e], size, color)
        parts = []
        pre, post = tex[:s], tex[e:]
        if pre_extra is not None:
            pre, post = pre_extra, post_extra
        if pre.strip():
            parts.append(self._render_tex(pre, size, color))
        parts.append(mid)
        if post.strip():
            parts.append(self._render_tex(post, size, color))
        return _hconcat(parts, gap=int(self._px(size) * 0.15))

    def _render_env(self, name: str, inner: str, opt: str, size: float, color, delims=None) -> Tuple[Image.Image, float]:
        if name in WRAP_ENVS or name not in ROW_ENVS:
            return self._render_tex(inner, size, color)
        small = name == "smallmatrix"
        csize = size * (0.8 if small else 1.0)
        rows = [_split_top(r, _COL_SEP) for r in _split_top(inner, _ROW_SEP)]
        rows = [r for r in rows if any(c.strip() for c in r)] or [[""]]
        ncols = max(len(r) for r in rows)
        cells = [[self._render_tex(c, csize, color) if c.strip() else (_blank(1, 1), 0.0) for c in r] + [(_blank(1, 1), 0.0)] * (ncols - len(r)) for r in rows]
        # alignment spec
        if name.startswith(("align", "flalign", "split", "eqnarray")):
            aligns = ["r" if i % 2 == 0 else "l" for i in range(ncols)]
            if name.startswith("eqnarray"):
                aligns = ["r", "c", "l"] + ["l"] * max(0, ncols - 3)
            colgap = 0.0
        elif name in ("cases", "dcases", "rcases"):
            aligns = ["l"] * ncols
            colgap = 1.0
        elif name in ("array", "subarray") and opt:
            spec = [c for c in opt.strip("{}") if c in "lcr"]
            aligns = (spec + ["c"] * ncols)[:ncols]
            colgap = 1.0
        else:
            aligns = ["c"] * ncols
            colgap = 1.0
        em = self._px(csize)
        gap_x = int(em * colgap) if colgap else int(em * 0.25)
        gap_y = int(em * (0.15 if small else 0.35))
        colw = [max(cells[r][c][0].width for r in range(len(rows))) for c in range(ncols)]
        row_asc = [int(round(max(img.height - d for img, d in row))) for row in cells]
        row_dep = [int(round(max(d for _, d in row))) for row in cells]
        W = sum(colw) + gap_x * (ncols - 1)
        H = sum(a + d for a, d in zip(row_asc, row_dep)) + gap_y * (len(rows) - 1)
        grid = _blank(W, H)
        y = 0
        for ri, row in enumerate(cells):
            x = 0
            for ci, (img, d) in enumerate(row):
                a = aligns[ci]
                if a == "l":
                    dx = 0
                elif a == "r":
                    dx = colw[ci] - img.width
                else:
                    dx = (colw[ci] - img.width) // 2
                yy = y + int(round(row_asc[ri] - (img.height - d)))
                grid.alpha_composite(img, (x + dx, yy))
                x += colw[ci] + gap_x
            y += row_asc[ri] + row_dep[ri] + gap_y
        # delimiters
        left = right = None
        base = name.rstrip("*")
        if delims:
            left, right = delims[0] or None, delims[1] or None
        elif base == "pmatrix":
            left, right = "(", ")"
        elif base == "bmatrix":
            left, right = "[", "]"
        elif base == "Bmatrix":
            left, right = "{", "}"
        elif base == "vmatrix":
            left, right = "|", "|"
        elif base == "Vmatrix":
            left, right = "‖", "‖"
        elif base in ("cases", "dcases"):
            left = "{"
        elif base == "rcases":
            right = "}"
        if left or right:
            pad = int(em * 0.2)
            dh = H + 2 * pad
            dw = int(em * 0.45)
            parts = []
            if left:
                parts.append(self._delim(left, dw, dh, em, color))
            parts.append(grid)
            if right:
                parts.append(self._delim(right, dw, dh, em, color))
            W2 = sum(p.width for p in parts) + int(em * 0.15) * (len(parts) - 1)
            out = _blank(W2, dh)
            x = 0
            for p in parts:
                out.alpha_composite(p, (x, (dh - p.height) // 2))
                x += p.width + int(em * 0.15)
            grid = out
            H = dh
        # baseline: centre on the math axis (~0.25em above baseline) for matrices/cases,
        # for multi-row equation environments as well (they are display-only anyway)
        depth = H / 2.0 - 0.25 * em
        return grid, depth

    def _delim(self, ch: str, w: int, h: int, em: float, color) -> Image.Image:
        img = _blank(w, h)
        d = ImageDraw.Draw(img)
        lw = max(1, int(round(em * 0.06)))
        col = color + (255,)
        if ch in "()":
            box = [lw, lw, 2 * w - lw, h - lw] if ch == "(" else [-w + lw, lw, w - lw, h - lw]
            d.arc(box, 90 if ch == "(" else 270, 270 if ch == "(" else 90, fill=col, width=lw)
        elif ch in "[]":
            x = lw if ch == "[" else w - lw
            xe = w - lw if ch == "[" else lw
            d.line([(x, lw), (x, h - lw)], fill=col, width=lw)
            d.line([(x, lw), (xe, lw)], fill=col, width=lw)
            d.line([(x, h - lw), (xe, h - lw)], fill=col, width=lw)
        elif ch == "|":
            d.line([(w // 2, 0), (w // 2, h)], fill=col, width=lw)
        elif ch == "‖":
            d.line([(w // 3, 0), (w // 3, h)], fill=col, width=lw)
            d.line([(2 * w // 3, 0), (2 * w // 3, h)], fill=col, width=lw)
        elif ch in "{}":
            mid = h / 2
            k = w * 0.45
            if ch == "{":
                pts = [(w - lw, lw), (w - k, lw + k), (w - k, mid - k), (lw, mid), (w - k, mid + k), (w - k, h - lw - k), (w - lw, h - lw)]
            else:
                pts = [(lw, lw), (k, lw + k), (k, mid - k), (w - lw, mid), (k, mid + k), (k, h - lw - k), (lw, h - lw)]
            d.line(pts, fill=col, width=lw, joint="curve")
        return img
