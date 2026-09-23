"""Command line / GUI entry point."""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List, Optional

from . import __version__

ENGINES = ("auto", "browser", "native", "nbconvert")


def _setup_env():
    os.environ.setdefault("MPLBACKEND", "Agg")
    if getattr(sys, "frozen", False):
        os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "ipynb2pdf-mpl"))
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass


def log(msg: str):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ipynb2pdf", description="Jupyter Notebook(.ipynb) -> PDF 변환기 (수식/이미지/한글 지원)")
    p.add_argument("files", nargs="*", help=".ipynb 파일 (여러 개 가능). 생략하면 파일 선택 창이 열립니다.")
    p.add_argument("-o", "--output", help="출력 PDF 경로 (입력 파일이 하나일 때)")
    p.add_argument("--outdir", help="출력 폴더 (기본: 입력 파일과 같은 폴더)")
    p.add_argument("--engine", choices=ENGINES, default="auto",
                   help="렌더링 엔진: auto(기본: browser→native 순), browser(Chrome/Edge+MathJax), native(순수 파이썬), nbconvert(jupyter nbconvert --to webpdf)")
    p.add_argument("--browser", help="Chromium 계열 브라우저 실행 파일 경로 (browser 엔진)")
    p.add_argument("--no-input", action="store_true", help="코드 셀 입력(소스) 숨김")
    p.add_argument("--no-output", action="store_true", help="코드 셀 출력 숨김")
    p.add_argument("--no-title", action="store_true", help="문서 상단 제목 생략")
    p.add_argument("--title", help="문서 제목 (기본: 파일 이름)")
    p.add_argument("--no-remote", action="store_true", help="원격(http) 이미지 다운로드 안 함")
    p.add_argument("--keep-html", action="store_true", help="browser 엔진의 중간 HTML 파일을 PDF 옆에 남김")
    p.add_argument("--no-gui", action="store_true", help="완료 후 메시지 창을 띄우지 않음")
    p.add_argument("--version", action="version", version="ipynb2pdf " + __version__)
    return p


def _output_path(nb_path: str, args) -> str:
    if args.output and len(args.files) == 1:
        return os.path.abspath(args.output)
    base = os.path.splitext(os.path.basename(nb_path))[0] + ".pdf"
    outdir = os.path.abspath(args.outdir) if args.outdir else os.path.dirname(os.path.abspath(nb_path))
    os.makedirs(outdir, exist_ok=True)
    return os.path.join(outdir, base)


def _nbconvert(nb_path: str, pdf_path: str) -> str:
    exe = shutil.which("jupyter") or shutil.which("jupyter-nbconvert")
    if not exe:
        raise RuntimeError("jupyter(nbconvert)가 설치되어 있지 않습니다")
    outdir = os.path.dirname(pdf_path)
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    cmd = [exe, "nbconvert", "--to", "webpdf", "--allow-chromium-download", "--output", name, "--output-dir", outdir, nb_path]
    if exe.endswith("jupyter-nbconvert") or "jupyter-nbconvert" in os.path.basename(exe):
        cmd = [exe, "--to", "webpdf", "--allow-chromium-download", "--output", name, "--output-dir", outdir, nb_path]
    log("  [nbconvert] " + " ".join(cmd))
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0 or not os.path.exists(pdf_path):
        raise RuntimeError("nbconvert 실패:\n" + r.stdout.decode("utf-8", "replace")[-1500:])
    return pdf_path


def convert_one(nb_path: str, pdf_path: str, args) -> str:
    """Convert a notebook; returns the engine actually used."""
    common = dict(include_input=not args.no_input, include_output=not args.no_output, title=args.title,
                  show_title=not args.no_title, fetch_remote=not args.no_remote)
    engine = args.engine
    if engine == "nbconvert":
        _nbconvert(nb_path, pdf_path)
        return "nbconvert"
    if engine in ("auto", "browser"):
        from . import browser, html_engine
        try:
            html_engine.convert(nb_path, pdf_path, browser_path=args.browser, keep_html=args.keep_html, log=log, **common)
            return "browser"
        except browser.BrowserError as e:
            if engine == "browser":
                raise
            log("  browser engine unavailable (%s) -> native engine" % e)
    from . import native_engine
    native_engine.convert(nb_path, pdf_path, log=log, **common)
    return "native"


def _pick_files_gui() -> List[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return []
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    files = filedialog.askopenfilenames(title="PDF로 변환할 Jupyter Notebook 선택",
                                        filetypes=[("Jupyter Notebook", "*.ipynb"), ("All files", "*.*")])
    root.destroy()
    return list(files)


def _message(title: str, text: str, error: bool = False):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        (messagebox.showerror if error else messagebox.showinfo)(title, text)
        root.destroy()
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    _setup_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    gui_mode = False
    if not args.files:
        args.files = _pick_files_gui()
        gui_mode = True
        if not args.files:
            parser.print_help()
            return 1
    if args.output and len(args.files) > 1:
        log("경고: 입력 파일이 여러 개이면 -o 는 무시됩니다 (--outdir 사용)")
    results = []
    failures = 0
    for f in args.files:
        f = os.path.abspath(f)
        if not os.path.isfile(f):
            log("없는 파일: %s" % f)
            results.append((f, None, "파일 없음"))
            failures += 1
            continue
        pdf = _output_path(f, args)
        log("변환 중: %s" % f)
        t0 = time.time()
        try:
            eng = convert_one(f, pdf, args)
            log("  완료 (%s, %.1fs): %s" % (eng, time.time() - t0, pdf))
            results.append((f, pdf, eng))
        except Exception as e:  # noqa: BLE001
            failures += 1
            log("  실패: %s" % e)
            results.append((f, None, "오류: %s" % e))
    if (gui_mode or (getattr(sys, "frozen", False) and sys.platform.startswith("win"))) and not args.no_gui:
        lines = []
        for src, pdf, info in results:
            lines.append(("✔ %s\n    → %s (%s)" % (os.path.basename(src), pdf, info)) if pdf else ("✘ %s\n    %s" % (os.path.basename(src), info)))
        _message("ipynb2pdf", "\n".join(lines)[:3000], error=failures > 0)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
