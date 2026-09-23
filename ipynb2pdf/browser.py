"""Locate a Chromium-based browser and print HTML to PDF with it (headless)."""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import List, Optional


def _win_candidates() -> List[str]:
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    c = [
        os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        os.path.join(local, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        os.path.join(pf, "Chromium", "Application", "chrome.exe"),
        os.path.join(local, "Chromium", "Application", "chrome.exe"),
        os.path.join(pf, "Vivaldi", "Application", "vivaldi.exe"),
        os.path.join(local, "Vivaldi", "Application", "vivaldi.exe"),
        os.path.join(pf, "Naver", "Naver Whale", "Application", "whale.exe"),
        os.path.join(pf86, "Naver", "Naver Whale", "Application", "whale.exe"),
    ]
    # registry App Paths
    try:
        import winreg  # type: ignore
        for exe in ("msedge.exe", "chrome.exe", "brave.exe", "whale.exe"):
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s" % exe) as k:
                        val, _ = winreg.QueryValueEx(k, None)
                        if val:
                            c.append(val)
                except OSError:
                    pass
    except ImportError:
        pass
    return c


def _mac_candidates() -> List[str]:
    return [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
        "/Applications/Whale.app/Contents/MacOS/Whale",
        os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        os.path.expanduser("~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ]


def _linux_candidates() -> List[str]:
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
             "microsoft-edge", "microsoft-edge-stable", "brave-browser", "chrome"]
    found = [shutil.which(n) for n in names]
    return [f for f in found if f] + ["/usr/bin/google-chrome", "/snap/bin/chromium", "/usr/bin/chromium"]


def find_browser(explicit: Optional[str] = None) -> Optional[str]:
    """Return the path of a usable Chromium-based browser executable, or None."""
    cands: List[str] = []
    if explicit:
        cands.append(explicit)
    env = os.environ.get("IPYNB2PDF_BROWSER")
    if env:
        cands.append(env)
    if sys.platform.startswith("win"):
        cands += _win_candidates()
    elif sys.platform == "darwin":
        cands += _mac_candidates()
    else:
        cands += _linux_candidates()
    # generic PATH lookup
    for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser", "brave"):
        w = shutil.which(n)
        if w:
            cands.append(w)
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


class BrowserError(RuntimeError):
    pass


def print_to_pdf(browser: str, html_path: str, pdf_path: str, timeout: float = 180.0,
                 virtual_time_ms: int = 30000, log=None) -> None:
    """Print *html_path* to *pdf_path* using a headless Chromium browser."""
    html_url = "file:///" + os.path.abspath(html_path).replace(os.sep, "/").lstrip("/")
    pdf_path = os.path.abspath(pdf_path)
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    errors = []
    for headless_flag in ("--headless=new", "--headless"):
        with tempfile.TemporaryDirectory(prefix="ipynb2pdf-profile-") as profile:
            cmd = [
                browser, headless_flag, "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-sync", "--disable-background-networking",
                "--disable-component-update", "--hide-scrollbars", "--mute-audio",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=%d" % virtual_time_ms,
                "--no-pdf-header-footer", "--print-to-pdf-no-header",
                "--allow-file-access-from-files",
                "--user-data-dir=%s" % profile,
                "--print-to-pdf=%s" % pdf_path,
                html_url,
            ]
            if sys.platform.startswith("linux"):
                cmd.insert(1, "--no-sandbox")
            kwargs = {}
            if sys.platform.startswith("win"):
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if log:
                log("  [browser] %s %s" % (os.path.basename(browser), headless_flag))
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kwargs)
            except OSError as e:
                errors.append(str(e))
                continue
            stderr_buf = []
            reader = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
            reader.start()
            ok = _wait_for_pdf(proc, pdf_path, timeout)
            _terminate(proc)
            if ok:
                return
            errors.append("%s: rc=%s stderr=%s" % (headless_flag, proc.returncode,
                                                   "".join(stderr_buf)[-600:].strip()))
    raise BrowserError("browser failed to produce PDF: " + " | ".join(errors))


def _drain(pipe, buf):
    try:
        for line in iter(pipe.readline, b""):
            buf.append(line.decode("utf-8", "replace"))
    except Exception:
        pass


def _wait_for_pdf(proc, pdf_path: str, timeout: float) -> bool:
    """Wait until the PDF is fully written (size stable) or the process exits. Some Chrome
    builds never exit after printing, so we must not rely on process termination."""
    deadline = time.time() + timeout
    last_size, stable = -1, 0
    while time.time() < deadline:
        if os.path.exists(pdf_path):
            size = os.path.getsize(pdf_path)
            if size > 0 and size == last_size:
                stable += 1
                if stable >= 3:  # ~0.6s without change
                    return True
            else:
                stable = 0
            last_size = size
        if proc.poll() is not None:
            return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0
        time.sleep(0.2)
    return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0


def _terminate(proc):
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass
