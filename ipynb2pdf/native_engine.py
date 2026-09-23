"""Pure-python ipynb -> PDF engine (ReportLab + matplotlib mathtext). No browser, no TeX needed."""
import base64
import html as htmlmod
import io
import os
import re
import tempfile
from typing import List, Optional, Tuple

import mistune
from pygments import lex
from pygments.lexers import get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.token import Token
from pygments.util import ClassNotFound
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, Image as RLImage, KeepTogether, ListFlowable, ListItem, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from reportlab.platypus.flowables import Flowable

from . import ansi, mdmath, resources
from .htmlutil import extract_tables, html_to_markup, is_probably_html
from .mathimg import MathRenderer
from .notebook import load_notebook, notebook_language, resolve_image

SANS, SANS_B, MONO, MONO_B = "NanumGothic", "NanumGothic-Bold", "NanumGothicCoding", "NanumGothicCoding-Bold"
_fonts_ready = False


def register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont(SANS, resources.font_path("sans")))
    pdfmetrics.registerFont(TTFont(SANS_B, resources.font_path("sans-bold")))
    pdfmetrics.registerFont(TTFont(MONO, resources.font_path("mono")))
    pdfmetrics.registerFont(TTFont(MONO_B, resources.font_path("mono-bold")))
    pdfmetrics.registerFontFamily(SANS, normal=SANS, bold=SANS_B, italic=SANS, boldItalic=SANS_B)
    pdfmetrics.registerFontFamily(MONO, normal=MONO, bold=MONO_B, italic=MONO, boldItalic=MONO_B)
    _fonts_ready = True


# ----------------------------------------------------------------------------- styles
BODY_SIZE, BODY_LEAD = 10.5, 16
CODE_SIZE, CODE_LEAD = 8.8, 12.5
PROMPT_W = 46
BG_CODE, BORDER_CODE = colors.HexColor("#f7f7f7"), colors.HexColor("#dcdcdc")
BG_ERR, BG_STDERR = colors.HexColor("#fdf0ef"), colors.HexColor("#fdf0ef")
TXT_ERR = colors.HexColor("#7a1f1f")


def _styles():
    st = {}
    st["body"] = ParagraphStyle("body", fontName=SANS, fontSize=BODY_SIZE, leading=BODY_LEAD, spaceAfter=5)
    st["cell"] = ParagraphStyle("cell", parent=st["body"], fontSize=9, leading=12.5, spaceAfter=0)
    st["cellhead"] = ParagraphStyle("cellhead", parent=st["cell"], fontName=SANS_B)
    st["title"] = ParagraphStyle("title", parent=st["body"], fontName=SANS_B, fontSize=20, leading=26, spaceAfter=4)
    for lvl, size in ((1, 18), (2, 15), (3, 13), (4, 11.5), (5, 10.5), (6, 10.5)):
        st["h%d" % lvl] = ParagraphStyle("h%d" % lvl, parent=st["body"], fontName=SANS_B, fontSize=size,
                                         leading=size * 1.35, spaceBefore=size * 0.8, spaceAfter=size * 0.4, keepWithNext=1)
    st["code"] = ParagraphStyle("code", fontName=MONO, fontSize=CODE_SIZE, leading=CODE_LEAD, wordWrap="CJK")
    st["out"] = ParagraphStyle("out", parent=st["code"])
    st["err"] = ParagraphStyle("err", parent=st["code"], textColor=TXT_ERR)
    st["prompt_in"] = ParagraphStyle("pin", fontName=MONO, fontSize=7.2, leading=CODE_LEAD, textColor=colors.HexColor("#303f9f"), alignment=TA_RIGHT)
    st["prompt_out"] = ParagraphStyle("pout", parent=st["prompt_in"], textColor=colors.HexColor("#d84315"))
    st["quote"] = ParagraphStyle("quote", parent=st["body"], textColor=colors.HexColor("#555555"))
    st["raw"] = ParagraphStyle("raw", parent=st["code"], textColor=colors.HexColor("#444444"))
    st["center"] = ParagraphStyle("center", parent=st["body"], alignment=TA_CENTER)
    st["note"] = ParagraphStyle("note", parent=st["body"], fontSize=8.5, leading=11, textColor=colors.HexColor("#b00020"))
    st["footer"] = ParagraphStyle("footer", fontName=SANS, fontSize=8, textColor=colors.HexColor("#888888"))
    return st


def esc(s: str) -> str:
    return htmlmod.escape(s, quote=False)


def code_esc(s: str) -> str:
    """Escape for monospace paragraphs: preserve spaces (nbsp) and tabs."""
    return esc(s).replace("\t", "    ").replace(" ", " ")


# ----------------------------------------------------------------------------- pygments -> markup
_PYG_STYLE = get_style_by_name("default")
_TOKEN_CACHE = {}


def _tok_fmt(ttype):
    if ttype in _TOKEN_CACHE:
        return _TOKEN_CACHE[ttype]
    d = _PYG_STYLE.style_for_token(ttype)
    fmt = (("#" + d["color"]) if d.get("color") else None, bool(d.get("bold")), bool(d.get("italic")))
    _TOKEN_CACHE[ttype] = fmt
    return fmt


def highlight_lines(code: str, lang: str) -> List[str]:
    """Return one markup string per line."""
    try:
        lexer = get_lexer_by_name(lang or "text", stripnl=False)
    except ClassNotFound:
        lexer = get_lexer_by_name("text", stripnl=False)
    lines: List[List[str]] = [[]]
    try:
        tokens = list(lex(code, lexer))
    except Exception:
        tokens = [(Token.Text, code)]
    for ttype, value in tokens:
        color, bold, italic = _tok_fmt(ttype)
        segs = value.split("\n")
        for i, seg in enumerate(segs):
            if i > 0:
                lines.append([])
            if not seg:
                continue
            m = code_esc(seg)
            if bold:
                m = "<b>%s</b>" % m
            if italic:
                m = "<i>%s</i>" % m
            if color:
                m = '<font color="%s">%s</font>' % (color, m)
            lines[-1].append(m)
    out = ["".join(l) for l in lines]
    while out and out[-1] == "":
        out.pop()
    return out or [""]


def ansi_lines(text: str, base_color: Optional[str] = None) -> List[str]:
    lines: List[List[str]] = [[]]
    for seg, state in ansi.ansi_to_segments(text):
        parts = seg.split("\n")
        for i, p in enumerate(parts):
            if i > 0:
                lines.append([])
            if not p:
                continue
            m = code_esc(p)
            if state.get("bold"):
                m = "<b>%s</b>" % m
            if state.get("underline"):
                m = "<u>%s</u>" % m
            color = state.get("fg") or base_color
            attrs = []
            if color:
                attrs.append('color="%s"' % color)
            if state.get("bg"):
                attrs.append('backColor="%s"' % state["bg"])
            if attrs:
                m = "<font %s>%s</font>" % (" ".join(attrs), m)
            lines[-1].append(m)
    out = ["".join(l) for l in lines]
    while len(out) > 1 and out[-1] == "":
        out.pop()
    return out


# ----------------------------------------------------------------------------- converter
class NativeConverter:
    def __init__(self, nb_path: str, pdf_path: str, include_input=True, include_output=True, title=None,
                 show_title=True, fetch_remote=True, log=None, workdir: Optional[str] = None):
        register_fonts()
        self.nb_path, self.pdf_path = nb_path, pdf_path
        self.include_input, self.include_output = include_input, include_output
        self.title = title if title is not None else os.path.splitext(os.path.basename(nb_path))[0]
        self.show_title, self.fetch_remote, self.log = show_title, fetch_remote, (log or (lambda s: None))
        self.nb_dir = os.path.dirname(os.path.abspath(nb_path))
        self.workdir = workdir or tempfile.mkdtemp(prefix="ipynb2pdf-native-")
        self.math = MathRenderer(os.path.join(self.workdir, "math"), dpi=300, fontsize=BODY_SIZE, display_fontsize=12)
        self.st = _styles()
        self.pagesize = A4
        self.margin_l = self.margin_r = 14 * mm
        self.margin_t, self.margin_b = 16 * mm, 16 * mm
        self.avail_w = self.pagesize[0] - self.margin_l - self.margin_r
        self.avail_h = self.pagesize[1] - self.margin_t - self.margin_b - 12
        self._img_counter = 0
        self.md = mistune.create_markdown(renderer=None, plugins=["table", "strikethrough", "task_lists", "url"])

    # ------------------------------------------------------------------ public
    def run(self) -> str:
        nb = load_notebook(self.nb_path)
        self.lang = notebook_language(nb)
        story: List[Flowable] = []
        if self.show_title:
            story.append(Paragraph(esc(self.title), self.st["title"]))
            story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#333333"), spaceAfter=8))
        for i, cell in enumerate(nb.cells):
            try:
                story.extend(self._cell(cell))
            except Exception as e:  # noqa: BLE001
                self.log("  warning: cell %d failed: %s" % (i, e))
                story.append(Paragraph(esc("[cell %d could not be rendered: %s]" % (i, e)), self.st["note"]))
        doc = SimpleDocTemplate(self.pdf_path, pagesize=self.pagesize, leftMargin=self.margin_l, rightMargin=self.margin_r,
                                topMargin=self.margin_t, bottomMargin=self.margin_b, title=self.title, author="ipynb2pdf")
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return self.pdf_path

    def _footer(self, canv, doc):
        canv.saveState()
        canv.setFont(SANS, 8)
        canv.setFillColor(colors.HexColor("#888888"))
        canv.drawCentredString(self.pagesize[0] / 2.0, self.margin_b * 0.55, str(doc.page))
        canv.drawString(self.margin_l, self.margin_b * 0.55, self.title[:80])
        canv.restoreState()

    # ------------------------------------------------------------------ cells
    def _cell(self, cell) -> List[Flowable]:
        ctype = cell.get("cell_type")
        src = cell.get("source", "") or ""
        if ctype == "markdown":
            fl = self._markdown(src, cell.get("attachments") or {})
            if fl and isinstance(fl[-1], Paragraph) and getattr(fl[-1].style, "keepWithNext", 0):
                return fl  # cell ends with a heading: let keepWithNext bind it to the next cell
            return fl + [Spacer(1, 4)]
        if ctype == "raw":
            return self._lines_table([code_esc(l) for l in src.split("\n")], self.st["raw"], None, None, None, None) + [Spacer(1, 6)]
        if ctype != "code":
            return []
        if not src.strip() and not cell.get("outputs"):
            return []  # empty trailing cells only waste space
        out: List[Flowable] = []
        n = cell.get("execution_count")
        if self.include_input:
            prompt = "In [%s]:" % (n if n is not None else " ")
            out += self._lines_table(highlight_lines(src, self.lang), self.st["code"], prompt, self.st["prompt_in"], BG_CODE, BORDER_CODE)
            out.append(Spacer(1, 3))
        if self.include_output:
            for o in cell.get("outputs") or []:
                out += self._output(o)
        out.append(Spacer(1, 6))
        return out

    def _lines_table(self, lines: List[str], style, prompt, prompt_style, bg, border, pad=5) -> List[Flowable]:
        if not lines:
            lines = [""]
        rows = []
        for i, line in enumerate(lines):
            p = Paragraph(prompt and i == 0 and esc(prompt) or "", prompt_style or self.st["prompt_in"]) if i == 0 and prompt else ""
            rows.append([p, Paragraph(line or " ", style)])
        t = Table(rows, colWidths=[PROMPT_W, self.avail_w - PROMPT_W], splitByRow=1)
        ts = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 5),
              ("LEFTPADDING", (1, 0), (1, -1), 7), ("RIGHTPADDING", (1, 0), (1, -1), 7),
              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
              ("TOPPADDING", (0, 0), (-1, 0), pad), ("BOTTOMPADDING", (0, -1), (-1, -1), pad)]
        if bg is not None:
            ts.append(("BACKGROUND", (1, 0), (1, -1), bg))
        if border is not None:
            ts.append(("BOX", (1, 0), (1, -1), 0.5, border))
        t.setStyle(TableStyle(ts))
        return [t]

    def _with_prompt(self, flowables: List[Flowable], prompt: Optional[str], prompt_style=None) -> List[Flowable]:
        """Place flowables in the output column with an optional Out[n]: prompt on the first row."""
        if not flowables:
            return []
        rows = []
        for i, f in enumerate(flowables):
            p = Paragraph(esc(prompt), prompt_style or self.st["prompt_out"]) if (i == 0 and prompt) else ""
            rows.append([p, f])
        t = Table(rows, colWidths=[PROMPT_W, self.avail_w - PROMPT_W], splitByRow=1)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 5),
                               ("LEFTPADDING", (1, 0), (1, -1), 7), ("RIGHTPADDING", (1, 0), (1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return [t]

    # ------------------------------------------------------------------ outputs
    def _output(self, o) -> List[Flowable]:
        otype = o.get("output_type")
        if otype == "stream":
            text = o.get("text", "") or ""
            if o.get("name") == "stderr":
                return self._lines_table(ansi_lines(text), self.st["out"], None, None, BG_STDERR, None, pad=3)
            return self._lines_table(ansi_lines(text), self.st["out"], None, None, None, None, pad=3)
        if otype == "error":
            tb = o.get("traceback") or []
            text = "\n".join(tb) if tb else "%s: %s" % (o.get("ename", ""), o.get("evalue", ""))
            return self._lines_table(ansi_lines(text, base_color="#7a1f1f"), self.st["err"], None, None, BG_ERR, None, pad=4)
        if otype not in ("display_data", "execute_result"):
            return []
        data = o.get("data") or {}
        meta = o.get("metadata") or {}
        prompt = "Out[%s]:" % o["execution_count"] if (otype == "execute_result" and o.get("execution_count") is not None) else None
        for mime in ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/svg+xml",
                     "text/html", "text/latex", "text/markdown", "text/plain"):
            if mime not in data:
                continue
            v = data[mime]
            if isinstance(v, list):
                v = "".join(v)
            if mime == "image/svg+xml":
                fl = self._svg_flowable(v)
                if fl is None:
                    continue
                return self._with_prompt([fl], prompt)
            if mime.startswith("image/"):
                try:
                    raw = base64.b64decode("".join(str(v).split()))
                except Exception:
                    continue
                m = meta.get(mime) or {}
                fl = self._image_flowable(raw, mime, req_w=m.get("width"), req_h=m.get("height"))
                if fl is None:
                    continue
                return self._with_prompt([fl], prompt)
            if mime == "text/html":
                fls = self._html_block(v)
                if not fls:
                    continue
                return self._with_prompt(fls, prompt)
            if mime == "text/latex":
                fls = self._latex_output(v)
                if not fls:
                    continue
                return self._with_prompt(fls, prompt)
            if mime == "text/markdown":
                return self._with_prompt(self._markdown(v, {}), prompt)
            if mime == "text/plain":
                return self._lines_table(ansi_lines(v), self.st["out"], prompt, self.st["prompt_out"], None, None, pad=3)
        return []

    def _latex_output(self, text: str) -> List[Flowable]:
        mathlist: mdmath.MathList = []
        src = mdmath.extract_math(text, mathlist)
        if not mathlist:  # whole thing is probably math without delimiters
            mathlist.append(("display", text))
            src = mdmath.PH_START + "0" + mdmath.PH_END
        return self._para_from_text(src, mathlist, self.st["body"], display_center=False)

    # ------------------------------------------------------------------ images
    def _image_flowable(self, raw: bytes, mime: str, req_w=None, req_h=None, max_w=None, max_h=None) -> Optional[Flowable]:
        from PIL import Image as PILImage
        max_w = max_w or (self.avail_w - PROMPT_W - 8)
        max_h = max_h or (self.avail_h - 10)
        try:
            im = PILImage.open(io.BytesIO(raw))
            im.load()
            if im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("P", "LA") else "RGB")
            if im.mode == "RGBA":  # flatten onto white (ReportLab handles alpha, but flattening is safer)
                bg = PILImage.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[3])
                im = bg
            buf = io.BytesIO()
            im.save(buf, "PNG")
            buf.seek(0)
        except Exception as e:  # noqa: BLE001
            self.log("  warning: image skipped (%s)" % e)
            return None
        w_px, h_px = im.size
        # natural size: assume 96 dpi like a browser
        w_pt, h_pt = w_px * 72.0 / 96.0, h_px * 72.0 / 96.0
        try:
            if req_w:
                w_pt = float(str(req_w).replace("px", "")) * 72.0 / 96.0
                h_pt = w_pt * h_px / w_px if not req_h else float(str(req_h).replace("px", "")) * 72.0 / 96.0
            elif req_h:
                h_pt = float(str(req_h).replace("px", "")) * 72.0 / 96.0
                w_pt = h_pt * w_px / h_px
        except ValueError:
            pass
        scale = min(1.0, max_w / w_pt, max_h / h_pt)
        img = RLImage(buf, width=w_pt * scale, height=h_pt * scale)
        img.hAlign = "LEFT"
        return img

    def _svg_flowable(self, svg_text: str) -> Optional[Flowable]:
        try:
            from svglib.svglib import svg2rlg
            drawing = svg2rlg(io.BytesIO(svg_text.encode("utf-8")))
            if drawing is None:
                return None
            max_w, max_h = self.avail_w - PROMPT_W - 8, self.avail_h - 10
            w, h = drawing.width or 1, drawing.height or 1
            s = min(1.0, max_w / w, max_h / h)
            drawing.scale(s, s)
            drawing.width, drawing.height = w * s, h * s
            drawing.hAlign = "LEFT"
            return drawing
        except Exception as e:  # noqa: BLE001
            self.log("  warning: svg output skipped (%s); trying raster fallback" % e)
            return None

    def _resolve_image_flowable(self, src: str, attachments: dict, max_w=None, req_w=None, req_h=None) -> Optional[Flowable]:
        got = resolve_image(src, self.nb_dir, attachments, fetch_remote=self.fetch_remote)
        if not got:
            return Paragraph(esc("[image not found: %s]" % src[:120]), self.st["note"])
        raw, mime = got
        if mime == "image/svg+xml" or raw[:200].lstrip().startswith(b"<svg") or b"<svg" in raw[:400]:
            fl = self._svg_flowable(raw.decode("utf-8", "replace"))
            if fl is not None:
                return fl
        return self._image_flowable(raw, mime, req_w=req_w, req_h=req_h, max_w=max_w or self.avail_w)

    # ------------------------------------------------------------------ html outputs
    def _html_block(self, html_text: str, attachments: Optional[dict] = None) -> List[Flowable]:
        out: List[Flowable] = []
        tables = extract_tables(html_text)
        if tables:
            for t in tables:
                out.append(self._table_from_rows(t["rows"], t["n_head"], max_w=self.avail_w - PROMPT_W - 8))
                out.append(Spacer(1, 4))
            # text outside tables is dropped when tables exist (pandas wrappers etc.)
            stripped = re.sub(r"<table[\s\S]*?</table>", "", html_text, flags=re.I)
            markup, images = html_to_markup(stripped)
            if markup.strip() or images:
                out += self._markup_blocks(markup, images, attachments)
            return out
        markup, images = html_to_markup(html_text)
        return self._markup_blocks(markup, images, attachments)

    def _markup_blocks(self, markup: str, images: List[str], attachments: Optional[dict]) -> List[Flowable]:
        out: List[Flowable] = []
        for para in re.split(r"\n{2,}", markup):
            para = para.strip("\n")
            if not para.strip():
                continue
            pieces = re.split(r"\ue010(\d+)\ue011", para)
            buf = []
            for i, piece in enumerate(pieces):
                if i % 2 == 1:
                    if "".join(buf).strip():
                        out.append(Paragraph(self._clean_markup("".join(buf)), self.st["body"]))
                    buf = []
                    fl = self._resolve_image_flowable(images[int(piece)], attachments or {}, max_w=self.avail_w - PROMPT_W - 8)
                    if fl is not None:
                        out.append(fl)
                else:
                    buf.append(piece)
            if "".join(buf).strip():
                out.append(Paragraph(self._clean_markup("".join(buf)), self.st["body"]))
        return out

    def _clean_markup(self, m: str) -> str:
        m = m.replace("<code>", '<font face="%s" backColor="#f2f2f2">' % MONO).replace("</code>", "</font>")
        m = m.replace("\n", "<br/>")
        try:
            Paragraph(m, self.st["body"])  # validate markup
            return m
        except Exception:
            return esc(re.sub(r"<[^>]+>", "", m)).replace("\n", "<br/>")

    # ------------------------------------------------------------------ markdown
    def _markdown(self, source: str, attachments: dict) -> List[Flowable]:
        mathlist: mdmath.MathList = []
        src = mdmath.extract_math(source, mathlist)
        try:
            tokens = self.md(src)
        except Exception as e:  # noqa: BLE001
            self.log("  warning: markdown parse failed (%s)" % e)
            return [Paragraph(esc(source), self.st["body"])]
        ctx = {"math": mathlist, "att": attachments}
        return self._blocks(tokens, ctx)

    def _blocks(self, tokens, ctx, width=None) -> List[Flowable]:
        width = width or self.avail_w
        out: List[Flowable] = []
        for tok in tokens:
            t = tok.get("type")
            if t in ("paragraph", "block_text"):
                out += self._paragraph(tok.get("children") or [], ctx, self.st["body"], width)
            elif t == "heading":
                lvl = min(6, max(1, (tok.get("attrs") or {}).get("level", 1)))
                out += self._paragraph(tok.get("children") or [], ctx, self.st["h%d" % lvl], width)
            elif t == "block_code":
                info = ((tok.get("attrs") or {}).get("info") or "").strip().split(" ")[0]
                lines = highlight_lines(tok.get("raw", "").rstrip("\n"), info or "text")
                out.append(self._plain_code_table(lines, width))
                out.append(Spacer(1, 5))
            elif t == "block_quote":
                inner = self._blocks(tok.get("children") or [], ctx, width - 14)
                if inner:
                    rows = [[f] for f in inner]
                    qt = Table(rows, colWidths=[width - 4], splitByRow=1)
                    qt.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#bbbbbb")),
                                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
                                            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 1),
                                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
                    out += [qt, Spacer(1, 5)]
            elif t == "list":
                out.append(self._list(tok, ctx, width))
                out.append(Spacer(1, 3))
            elif t == "table":
                out.append(self._md_table(tok, ctx, width))
                out.append(Spacer(1, 5))
            elif t == "thematic_break":
                out.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#cccccc"), spaceBefore=4, spaceAfter=6))
            elif t == "block_html":
                out += self._html_block(tok.get("raw", ""), ctx["att"])
            elif t in ("blank_line", "newline"):
                continue
            elif tok.get("children"):
                out += self._blocks(tok["children"], ctx, width)
            elif tok.get("raw"):
                out.append(Paragraph(esc(tok["raw"]), self.st["body"]))
        return out

    def _plain_code_table(self, lines: List[str], width: float) -> Flowable:
        rows = [[Paragraph(l or " ", self.st["code"])] for l in (lines or [""])]
        t = Table(rows, colWidths=[width], splitByRow=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f6f6")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e3e3e3")),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, -1), (-1, -1), 5)]))
        return t

    def _list(self, tok, ctx, width: float) -> Flowable:
        attrs = tok.get("attrs") or {}
        ordered = attrs.get("ordered", False)
        start = attrs.get("start") or 1
        items = []
        for item in tok.get("children") or []:
            if item.get("type") not in ("list_item", "task_list_item"):
                continue
            checked = (item.get("attrs") or {}).get("checked")
            fls = self._blocks(item.get("children") or [], ctx, width - 18)
            if not fls:
                fls = [Paragraph("", self.st["body"])]
            if checked is not None and fls and isinstance(fls[0], Paragraph):
                box = "■ " if checked else "□ "
                fls[0] = Paragraph(box + fls[0].text, self.st["body"])
            items.append(ListItem(fls, leftIndent=18, value=None))
        if not items:
            return Spacer(1, 1)
        is_task = any((it.get("attrs") or {}).get("checked") is not None for it in tok.get("children") or [])
        kw = dict(bulletType="1", start=start) if ordered else dict(bulletType="bullet", start=" " if is_task else "•")
        return ListFlowable(items, leftIndent=18, bulletFontName=SANS, bulletFontSize=BODY_SIZE, bulletOffsetY=0, **kw)

    def _md_table(self, tok, ctx, width: float) -> Flowable:
        rows: List[List[Tuple[str, bool, str]]] = []
        n_head = 0
        for section in tok.get("children") or []:
            if section.get("type") == "table_head":
                cells = [(c, True) for c in section.get("children") or []]
                rows.append(cells)
                n_head = 1
            elif section.get("type") == "table_body":
                for row in section.get("children") or []:
                    rows.append([(c, False) for c in row.get("children") or []])
        data = []
        aligns = []
        for r in rows:
            data_row = []
            for c, is_head in r:
                al = ((c.get("attrs") or {}).get("align") or "left")
                if len(aligns) < len(r):
                    aligns.append(al)
                data_row.append((self._inline(c.get("children") or [], ctx), is_head, al))
            data.append(data_row)
        return self._table_from_rows(data, n_head, max_w=width, markup=True)

    def _table_from_rows(self, rows, n_head: int, max_w: float, markup: bool = False) -> Flowable:
        ncols = max(len(r) for r in rows) if rows else 1
        norm = []
        for r in rows:
            r = list(r) + [("", False)] * (ncols - len(r))
            norm.append(r)
        # column width estimate
        est = [0.0] * ncols
        for r in norm:
            for j, cell in enumerate(r):
                text = cell[0]
                plain = re.sub(r"<[^>]+>", "", text) if markup else text
                longest = max((pdfmetrics.stringWidth(line, SANS, 9) for line in plain.split("\n")), default=0)
                est[j] = max(est[j], min(longest + 12, max_w * 0.6))
        est = [max(e, 24) for e in est]
        total = sum(est)
        if total > max_w:
            est = [e * max_w / total for e in est]
        data = []
        for ri, r in enumerate(norm):
            row = []
            for j, cell in enumerate(r):
                text, is_head = cell[0], cell[1]
                al = cell[2] if len(cell) > 2 else "left"
                if len(text) > 3000:
                    text = text[:3000] + "…"
                style = ParagraphStyle("c%d" % j, parent=self.st["cellhead" if (is_head or ri < n_head) else "cell"],
                                       alignment={"center": 1, "right": 2}.get(al, 0))
                m = text if markup else esc(text).replace("\n", "<br/>")
                try:
                    row.append(Paragraph(m, style))
                except Exception:
                    row.append(Paragraph(esc(re.sub(r"<[^>]+>", "", m)), style))
            data.append(row)
        t = Table(data, colWidths=est, repeatRows=min(n_head, 3), splitByRow=1)
        ts = [("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
              ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        if n_head:
            ts.append(("BACKGROUND", (0, 0), (-1, n_head - 1), colors.HexColor("#f0f0f0")))
        for ri, r in enumerate(norm):
            for j, cell in enumerate(r):
                if cell[1] and ri >= n_head:
                    ts.append(("BACKGROUND", (j, ri), (j, ri), colors.HexColor("#f0f0f0")))
        t.setStyle(TableStyle(ts))
        t.hAlign = "LEFT"
        return t

    # ------------------------------------------------------------------ inline / paragraph
    def _math_markup(self, idx: int, ctx, display_inline=False) -> str:
        kind, tex = ctx["math"][idx]
        mi = self.math.render(mdmath.strip_math_env(tex), display=(kind == "display"))
        if mi is None:
            return '<font face="%s" color="#555555">%s</font>' % (MONO, esc(tex))
        w, h = mi.width, mi.height
        max_w = self.avail_w * 0.95
        if w > max_w:
            s = max_w / w
            w, h = w * s, h * s
        return '<img src="%s" width="%.2f" height="%.2f" valign="%.2f"/>' % (mi.path, w, h, -mi.depth * (h / mi.height))

    def _inline(self, children, ctx, in_link=False) -> str:
        out = []
        for c in children:
            t = c.get("type")
            if t == "text":
                for kind, val in mdmath.split_placeholders(c.get("raw", "")):
                    out.append(esc(val) if kind == "text" else self._math_markup(val, ctx))
            elif t == "emphasis":
                out.append("<i>%s</i>" % self._inline(c.get("children") or [], ctx, in_link))
            elif t == "strong":
                out.append("<b>%s</b>" % self._inline(c.get("children") or [], ctx, in_link))
            elif t == "strikethrough":
                out.append("<strike>%s</strike>" % self._inline(c.get("children") or [], ctx, in_link))
            elif t == "codespan":
                out.append('<font face="%s" backColor="#f2f2f2">%s</font>' % (MONO, code_esc(c.get("raw", ""))))
            elif t == "link":
                url = (c.get("attrs") or {}).get("url", "")
                inner = self._inline(c.get("children") or [], ctx, True) or esc(url)
                out.append('<a href="%s" color="#1a5fb4">%s</a>' % (esc(url).replace('"', "%22"), inner))
            elif t == "image":
                out.append(self._inline_image_markup(c, ctx))
            elif t == "linebreak":
                out.append("<br/>")
            elif t == "softbreak":
                out.append(" ")
            elif t == "inline_html":
                raw = c.get("raw", "")
                m = re.match(r"<img\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", raw, re.I)
                if m:
                    w = re.search(r"\bwidth\s*=\s*[\"']?(\d+)", raw, re.I)
                    h = re.search(r"\bheight\s*=\s*[\"']?(\d+)", raw, re.I)
                    out.append("\ue020%s|%s|%s\ue021" % (m.group(1), w.group(1) if w else "", h.group(1) if h else ""))
                else:
                    markup, _ = html_to_markup(raw)
                    out.append(markup.replace("\n", "<br/>"))
            elif c.get("children"):
                out.append(self._inline(c["children"], ctx, in_link))
            elif c.get("raw"):
                out.append(esc(c["raw"]))
        return "".join(out)

    def _inline_image_markup(self, c, ctx) -> str:
        url = (c.get("attrs") or {}).get("url", "")
        return "\ue020%s\ue021" % url

    _IMG_MARK_RE = re.compile("\ue020(.*?)\ue021")

    def _paragraph(self, children, ctx, style, width: float) -> List[Flowable]:
        markup = self._inline(children, ctx)
        return self._markup_to_flowables(markup, ctx, style, width)

    def _markup_to_flowables(self, markup: str, ctx, style, width: float) -> List[Flowable]:
        """Split paragraph markup at block images and standalone display math."""
        out: List[Flowable] = []
        pieces = self._IMG_MARK_RE.split(markup)
        for i, piece in enumerate(pieces):
            if i % 2 == 1:
                src, w, h = (piece.split("|") + ["", ""])[:3] if "|" in piece else (piece, "", "")
                fl = self._resolve_image_flowable(src, ctx.get("att") or {}, max_w=width, req_w=w or None, req_h=h or None)
                if fl is not None:
                    out.append(fl)
                    out.append(Spacer(1, 4))
                continue
            if not piece.strip():
                continue
            out += self._text_piece(piece, ctx, style, width)
        return out

    def _text_piece(self, markup: str, ctx, style, width: float) -> List[Flowable]:
        # standalone display math (whole paragraph is a single <img> of display kind) -> centred
        imgs = re.findall(r'<img src="[^"]+" width="([\d.]+)" height="([\d.]+)" valign="[-\d.]+"/>', markup)
        stripped = re.sub(r"<img [^>]+/>", "", markup).strip()
        if imgs and not stripped:
            # only images (display math): centre each on its own line as a real Image flowable
            out = [Spacer(1, 3)]
            for m in re.finditer(r'<img src="([^"]+)" width="([\d.]+)" height="([\d.]+)"', markup):
                img = RLImage(m.group(1), width=float(m.group(2)), height=float(m.group(3)))
                img.hAlign = "CENTER"
                out += [img, Spacer(1, 5)]
            return out
        max_h = max((float(h) for _, h in imgs), default=0)
        if max_h > style.leading:
            style = ParagraphStyle("tall", parent=style, leading=max_h + 3)
        try:
            return [Paragraph(markup, style)]
        except Exception:
            return [Paragraph(esc(re.sub(r"<[^>]+>", "", markup)), style)]

    def _para_from_text(self, text_with_ph: str, mathlist, style, display_center=True) -> List[Flowable]:
        ctx = {"math": mathlist, "att": {}}
        parts = []
        for kind, val in mdmath.split_placeholders(text_with_ph):
            parts.append(esc(val).replace("\n", "<br/>") if kind == "text" else self._math_markup(val, ctx))
        return self._text_piece("".join(parts), ctx, style, self.avail_w)


def convert(nb_path: str, pdf_path: str, log=None, **kwargs) -> str:
    with tempfile.TemporaryDirectory(prefix="ipynb2pdf-native-") as td:
        conv = NativeConverter(nb_path, pdf_path, log=log, workdir=td, **kwargs)
        return conv.run()
