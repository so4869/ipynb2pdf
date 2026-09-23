"""Locate bundled resources (fonts, MathJax, CSS) both in source and PyInstaller builds."""
import os
import sys


def base_dir() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    return os.path.join(base_dir(), "resources", *parts)


FONT_FILES = {
    "sans": "NanumGothic-Regular.ttf",
    "sans-bold": "NanumGothic-Bold.ttf",
    "mono": "NanumGothicCoding-Regular.ttf",
    "mono-bold": "NanumGothicCoding-Bold.ttf",
}


def font_path(key: str) -> str:
    return resource_path("fonts", FONT_FILES[key])


def mathjax_path() -> str:
    return resource_path("mathjax", "tex-svg-full.js")


def css_path() -> str:
    return resource_path("style.css")
