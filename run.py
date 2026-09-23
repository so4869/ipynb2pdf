"""PyInstaller entry point."""
import multiprocessing
import sys

from ipynb2pdf.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
