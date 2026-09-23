"""ipynb -> self-contained HTML -> PDF via a headless Chromium browser (MathJax rendering)."""
import base64
import html
import json
import os
import re
import tempfile
from typing import List, Optional, Tuple

import mistune
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound

from . import ansi, browser, mdmath, resources
from .notebook import load_notebook, notebook_language, resolve_image, to_data_uri

MIME_PRIORITY = ["text/html", "image/svg+xml", "image/png", "image/jpeg", "image/gif", "image/webp",
                 "text/latex", "text/markdown", "text/plain"]


# ----------------------------------------------------------------------------- markdown
class _Renderer(mistune.HTMLRenderer):
    def __init__(self, nb_dir: str, attachments: dict, fetch_remote: bool):
        super().__init__(escape=False)
        self.nb_dir, self.attachments, self.fetch_remote = nb_dir, attachments, fetch_remote

    def _resolve(self, url: str) -> str:
        if url.startswith("data:"):
            return url
        got = resolve_image(url, self.nb_dir, self.attachments, fetch_remote=self.fetch_remote)
        if got:
            return to_data_uri(*got)
        return url

    def image(self, text, url, title=None):
        return super().image(text, self._resolve(url), title)

    def block_html(self, html_text):
        return self._fix_html_imgs(html_text)

    def inline_html(self, html_text):
        return self._fix_html_imgs(html_text)

    _IMG_SRC_RE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])(.*?)\2""", re.I | re.S)

    def _fix_html_imgs(self, s: str) -> str:
        return self._IMG_SRC_RE.sub(lambda m: m.group(1) + m.group(2) + self._resolve(html.unescape(m.group(3))) + m.group(2), s)

    def task_list_item(self, text, checked=False, **attrs):
        box = '<input type="checkbox" disabled %s/> ' % ("checked" if checked else "")
        return '<li class="task-list-item">' + box + text + "</li>\n"


def _make_markdown(nb_dir, attachments, fetch_remote):
    return mistune.create_markdown(
        renderer=_Renderer(nb_dir, attachments, fetch_remote),
        plugins=["table", "strikethrough", "task_lists", "footnotes", "url", "def_list", "abbr", "superscript", "subscript", "insert", "mark"],
    )


def _math_html(kind: str, tex: str) -> str:
    tex = html.escape(tex, quote=False)
    if kind == "display":
        return '<div class="math-display">\\[%s\\]</div>' % tex
    return '<span class="math-inline">\\(%s\\)</span>' % tex


def _substitute_math(html_text: str, mathlist: mdmath.MathList) -> str:
    def _sub(m):
        kind, tex = mathlist[int(m.group(1))]
        return _math_html(kind, tex)
    return mdmath._PH_RE.sub(_sub, html_text)


def render_markdown(source: str, nb_dir: str, attachments: Optional[dict], fetch_remote: bool = True) -> str:
    mathlist: mdmath.MathList = []
    src = mdmath.extract_math(source, mathlist)
    md = _make_markdown(nb_dir, attachments or {}, fetch_remote)
    out = md(src)
    # a display placeholder that ended up wrapped in <p> alone: unwrap
    out = re.sub(r"<p>\s*(" + mdmath.PH_START + r"\d+" + mdmath.PH_END + r")\s*</p>", r"\1", out)
    out = _block_images(out)
    return _substitute_math(out, mathlist)


_P_RE = re.compile(r"<p>([\s\S]*?)</p>")
_LINE_IMG_RE = re.compile(r"(?:^|\n)[ \t]*(<img\b[^>]*>)[ \t]*(?=\n|$)|^[ \t]*(<img\b[^>]*>)[ \t]*")


def _block_images(html_text: str) -> str:
    """Images that occupy their own line in the markdown source (very common in notebooks:
    heading / image / text without blank lines) become block-level <figure>s instead of inline
    images inside the paragraph. This lets the browser paginate them sensibly."""
    def _fix(m):
        inner = m.group(1)
        if "<img" not in inner:
            return m.group(0)
        parts = []
        pos = 0
        for im in _LINE_IMG_RE.finditer(inner):
            tag = im.group(1) or im.group(2)
            before = inner[pos:im.start()]
            if before.strip():
                parts.append("<p>%s</p>" % before.strip("\n"))
            parts.append('<figure class="md-img">%s</figure>' % tag)
            pos = im.end()
        rest = inner[pos:]
        if rest.strip():
            parts.append("<p>%s</p>" % rest.strip("\n"))
        return "\n".join(parts) if parts else m.group(0)
    return _P_RE.sub(_fix, html_text)


def render_latex_output(text: str) -> str:
    """text/latex outputs: math delimiters -> MathJax; the rest as text."""
    mathlist: mdmath.MathList = []
    src = mdmath.extract_math(text, mathlist)
    parts = []
    for kind, val in mdmath.split_placeholders(src):
        if kind == "text":
            parts.append(html.escape(val))
        else:
            parts.append(_math_html(*mathlist[val]))
    return '<div class="latex-output">%s</div>' % "".join(parts)


# ----------------------------------------------------------------------------- code
_formatter = HtmlFormatter(nowrap=True)


def _lexer(lang: str):
    try:
        return get_lexer_by_name(lang, stripall=False)
    except ClassNotFound:
        return get_lexer_by_name("text")


def highlight_code(code: str, lang: str) -> str:
    code = code.rstrip("\n")
    if not code:
        return ""
    try:
        return highlight(code, _lexer(lang), _formatter)
    except Exception:
        return html.escape(code)


# ----------------------------------------------------------------------------- outputs
_SCRIPT_RE = re.compile(r"<script\b", re.I)


def _pick_mime(data: dict) -> Optional[str]:
    keys = list(data.keys())
    has_img = any(k.startswith("image/") for k in keys)
    if "text/html" in keys and not (_SCRIPT_RE.search(data["text/html"] or "") and has_img):
        return "text/html"
    for m in MIME_PRIORITY:
        if m in keys:
            return m
    return None


def _img_data(v, mime: str) -> str:
    if isinstance(v, bytes):
        b64 = base64.b64encode(v).decode("ascii")
    else:
        b64 = "".join(str(v).split())
    return "data:%s;base64,%s" % (mime, b64)


def _render_output(out: dict, lang: str, nb_dir: str, fetch_remote: bool) -> Tuple[str, Optional[str], bool]:
    """Return (html, prompt_text, is_long)."""
    otype = out.get("output_type")
    if otype == "stream":
        text = out.get("text", "") or ""
        name = out.get("name", "stdout")
        return ('<pre class="stream %s">%s</pre>' % (name, ansi.ansi_to_html(text)), None, text.count("\n") > 30)
    if otype == "error":
        tb = out.get("traceback") or []
        text = "\n".join(tb) if tb else "%s: %s" % (out.get("ename", ""), out.get("evalue", ""))
        return ('<pre class="error">%s</pre>' % ansi.ansi_to_html(text), None, text.count("\n") > 30)
    if otype in ("display_data", "execute_result"):
        data = out.get("data") or {}
        prompt = None
        if otype == "execute_result" and out.get("execution_count") is not None:
            prompt = "Out[%s]:" % out["execution_count"]
        mime = _pick_mime(data)
        if mime is None:
            return "", prompt, False
        v = data[mime]
        if mime == "text/html":
            body = v if isinstance(v, str) else "".join(v)
            return '<div class="rendered_html">%s</div>' % body, prompt, body.count("<tr") > 40
        if mime == "image/svg+xml":
            svg = v if isinstance(v, str) else "".join(v)
            svg = re.sub(r"<\?xml[^>]*\?>", "", svg)
            svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg, flags=re.S)
            return '<div class="svg-output">%s</div>' % svg, prompt, False
        if mime.startswith("image/"):
            meta = (out.get("metadata") or {}).get(mime) or {}
            style = ""
            if meta.get("width"):
                style += "width:%spx;" % meta["width"]
            if meta.get("height"):
                style += "height:%spx;" % meta["height"]
            return '<img src="%s" style="%s" alt="output image"/>' % (_img_data(v, mime), style), prompt, False
        if mime == "text/latex":
            return render_latex_output(v if isinstance(v, str) else "".join(v)), prompt, False
        if mime == "text/markdown":
            return '<div class="md-output">%s</div>' % render_markdown(v if isinstance(v, str) else "".join(v), nb_dir, None, fetch_remote), prompt, False
        text = v if isinstance(v, str) else "".join(v)
        return '<pre class="plain">%s</pre>' % ansi.ansi_to_html(text), prompt, text.count("\n") > 30
    return "", None, False


# ----------------------------------------------------------------------------- document
def _font_face_css() -> str:
    faces = []
    for family, key, weight in (("NanumGothic", "sans", 400), ("NanumGothic", "sans-bold", 700),
                                ("NanumGothicCoding", "mono", 400), ("NanumGothicCoding", "mono-bold", 700)):
        p = resources.font_path(key)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            faces.append('@font-face{font-family:"%s";font-weight:%d;font-style:normal;'
                         'src:url(data:font/ttf;base64,%s) format("truetype");}' % (family, weight, b64))
    return "\n".join(faces)


def _mathjax_script_tag(inline: bool) -> str:
    p = resources.mathjax_path()
    if not os.path.isfile(p):
        return '<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg-full.js"></script>'
    if inline:
        with open(p, "r", encoding="utf-8") as f:
            return "<script>%s</script>" % f.read()
    url = "file:///" + os.path.abspath(p).replace(os.sep, "/").lstrip("/")
    return '<script src="%s"></script>' % url


# Runs inside the browser after layout (and after MathJax): keeps a heading together with the
# block that follows it, and keeps a small image together with its caption paragraph, whenever
# the group is short enough to fit comfortably on one page. Chrome's `break-after: avoid` alone
# is unreliable when the next block starts with a large image.
PAGINATION_JS = r"""
(function(){
  function px(mm){ return mm * 96 / 25.4; }
  var PAGE_H = px(297 - 16 - 16);          // printable height of an A4 page (see @page margins)
  var LIMIT = PAGE_H * 0.75;               // max height of a group we force to stay together
  var HARD = PAGE_H * 0.95;
  function wrap(nodes){
    var d = document.createElement('div');
    d.className = 'keep';
    nodes[0].parentNode.insertBefore(d, nodes[0]);
    nodes.forEach(function(n){ d.appendChild(n); });
  }
  function isHeading(el){ return el && /^H[1-6]$/.test(el.tagName); }
  function is(el, tag){ return el && el.tagName === tag; }
  function height(el){ return el ? el.getBoundingClientRect().height : 0; }
  function sum(nodes){ var t = 0; nodes.forEach(function(n){ t += height(n); }); return t; }
  function fix(){
    var heads = Array.prototype.slice.call(document.querySelectorAll(
      '.cell.markdown h1, .cell.markdown h2, .cell.markdown h3, .cell.markdown h4, .cell.markdown h5, .cell.markdown h6'));
    heads.forEach(function(h){
      if (h.closest('.keep')) return;
      var group = [h], n = h.nextElementSibling;
      while (isHeading(n)) { group.push(n); n = n.nextElementSibling; }
      if (!n) {
        // heading is the last block of its cell: keep the whole (short) cell with the next cell
        wrap(group);
        var cell = h.closest('.cell'), next = cell && cell.nextElementSibling;
        if (next && next.classList.contains('cell') && height(cell) + height(next) <= LIMIT) wrap([cell, next]);
        else if (next && next.classList.contains('cell')) {
          var first = next.querySelector('.input, .output, figure, p, h1, h2, h3, h4, h5, h6');
          if (first && height(cell) + height(first) <= LIMIT) { next.style.breakBefore = 'avoid'; cell.style.breakAfter = 'avoid'; cell.style.breakInside = 'avoid'; }
        }
        return;
      }
      // heading + first block (+ figure + caption when they fit)
      var cand = group.concat([n]);
      if (is(n, 'FIGURE')) {
        if (is(n.nextElementSibling, 'P') && sum(cand) + height(n.nextElementSibling) <= LIMIT) cand.push(n.nextElementSibling);
      } else if (is(n, 'P') && is(n.nextElementSibling, 'FIGURE')) {
        var fig = n.nextElementSibling;
        if (sum(cand) + height(fig) <= HARD) {
          cand.push(fig);
          if (is(fig.nextElementSibling, 'P') && sum(cand) + height(fig.nextElementSibling) <= LIMIT) cand.push(fig.nextElementSibling);
        }
      }
      if (sum(cand) <= HARD) wrap(cand);
      else if (sum(group.concat([n])) <= HARD && is(n, 'FIGURE')) wrap(group.concat([n]));
      else wrap(group);   // at least never split the heading itself
    });
    // figure + caption paragraph
    Array.prototype.slice.call(document.querySelectorAll('.cell.markdown figure.md-img')).forEach(function(f){
      if (f.closest('.keep')) return;
      var n = f.nextElementSibling;
      if (is(n, 'P') && height(f) + height(n) <= LIMIT) wrap([f, n]);
    });
  }
  function run(){ try { fix(); } catch (e) {} }
  if (window.MathJax && MathJax.startup && MathJax.startup.promise) {
    MathJax.startup.promise.then(run, run);
  } else if (document.readyState === 'complete') { run(); } else { window.addEventListener('load', run); }
})();
"""

MATHJAX_CONFIG = {
    "tex": {
        "inlineMath": [["\\(", "\\)"]],
        "displayMath": [["\\[", "\\]"]],
        "processEscapes": True,
        "processEnvironments": True,
        "tags": "ams",
        "packages": {"[+]": ["ams", "boldsymbol", "cancel", "color", "physics", "mathtools", "mhchem", "newcommand", "bbox", "enclose", "unicode", "textmacros", "upgreek", "braket", "cases", "empheq", "gensymb", "centernot", "colortbl", "html"]},
    },
    "svg": {"fontCache": "none", "scale": 1.0},
    "options": {"ignoreHtmlClass": "src|stream|error|plain", "processHtmlClass": "math-inline|math-display|latex-output"},
    "startup": {"typeset": True},
}


def build_html(nb_path: str, include_input: bool = True, include_output: bool = True, title: Optional[str] = None,
               show_title: bool = True, fetch_remote: bool = True, inline_mathjax: bool = False, log=None) -> str:
    nb = load_notebook(nb_path)
    nb_dir = os.path.dirname(os.path.abspath(nb_path))
    lang = notebook_language(nb)
    if title is None:
        title = os.path.splitext(os.path.basename(nb_path))[0]

    with open(resources.css_path(), "r", encoding="utf-8") as f:
        css = f.read()

    parts: List[str] = []
    parts.append("<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>%s</title>" % html.escape(title))
    parts.append("<style>%s\n%s</style>" % (_font_face_css(), css))
    parts.append("<script>window.MathJax=%s;</script>" % json.dumps(MATHJAX_CONFIG))
    parts.append(_mathjax_script_tag(inline_mathjax))
    parts.append("</head><body>")
    if show_title:
        parts.append('<h1 class="nb-title">%s</h1>' % html.escape(title))
    for i, cell in enumerate(nb.cells):
        try:
            parts.append(_render_cell(cell, lang, nb_dir, include_input, include_output, fetch_remote))
        except Exception as e:  # never let one cell kill the document
            if log:
                log("  warning: cell %d failed: %s" % (i, e))
            parts.append('<div class="cell"><div class="conv-error">[cell %d could not be rendered: %s]</div></div>' % (i, html.escape(str(e))))
    parts.append("<script>%s</script>" % PAGINATION_JS)
    parts.append("</body></html>")
    return "\n".join(parts)


def _render_cell(cell, lang, nb_dir, include_input, include_output, fetch_remote) -> str:
    ctype = cell.get("cell_type")
    src = cell.get("source", "") or ""
    if ctype == "markdown":
        return '<div class="cell markdown">%s</div>' % render_markdown(src, nb_dir, cell.get("attachments"), fetch_remote)
    if ctype == "raw":
        return '<div class="cell raw"><pre class="raw">%s</pre></div>' % html.escape(src)
    if ctype != "code":
        return ""
    if not src.strip() and not cell.get("outputs"):
        return ""  # empty trailing cells only waste space
    out: List[str] = ['<div class="cell code">']
    n = cell.get("execution_count")
    prompt = "In [%s]:" % (n if n is not None else " ")
    if include_input:
        long_cls = " long" if src.count("\n") > 35 else ""
        out.append('<div class="input%s"><div class="prompt">%s</div><div class="src highlight"><pre>%s</pre></div></div>'
                   % (long_cls, html.escape(prompt), highlight_code(src, lang)))
    if include_output and cell.get("outputs"):
        out.append('<div class="outputs">')
        for o in cell["outputs"]:
            body, oprompt, is_long = _render_output(o, lang, nb_dir, fetch_remote)
            if not body:
                continue
            out.append('<div class="output%s"><div class="prompt">%s</div><div class="output-body">%s</div></div>'
                       % (" long" if is_long else "", html.escape(oprompt or ""), body))
        out.append("</div>")
    out.append("</div>")
    return "\n".join(out)


def convert(nb_path: str, pdf_path: str, browser_path: Optional[str] = None, keep_html: bool = False,
            log=None, **kwargs) -> str:
    """Convert with the browser engine. Returns the pdf path. Raises BrowserError if no browser."""
    exe = browser.find_browser(browser_path)
    if not exe:
        raise browser.BrowserError("no Chromium-based browser (Chrome/Edge) found")
    html_text = build_html(nb_path, log=log, **kwargs)
    out_dir = os.path.dirname(os.path.abspath(pdf_path))
    if keep_html:
        html_path = os.path.splitext(os.path.abspath(pdf_path))[0] + ".html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_text)
        browser.print_to_pdf(exe, html_path, pdf_path, log=log)
    else:
        with tempfile.TemporaryDirectory(prefix="ipynb2pdf-") as td:
            html_path = os.path.join(td, "notebook.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_text)
            browser.print_to_pdf(exe, html_path, pdf_path, log=log)
    return pdf_path
