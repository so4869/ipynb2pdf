"""ipynb2pdf - Jupyter Notebook(.ipynb) -> PDF converter.

Two rendering engines:
  * browser : builds a self-contained HTML (MathJax, embedded Korean fonts) and
              prints it with a locally installed Chromium browser (Chrome/Edge).
  * native  : pure-python fallback using ReportLab + matplotlib mathtext.
"""
__version__ = "1.0.0"
