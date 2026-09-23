"""Generate resources/mpl_fontlist.json: a portable matplotlib font cache that lists only the
fonts shipped with matplotlib (paths stored relative to mpl-data). Installing it into the
matplotlib cache dir at runtime avoids the slow system-font scan on first run of the exe."""
import json
import os
import sys

import matplotlib
import matplotlib.font_manager as fm

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(here, "resources", "mpl_fontlist.json")
data_path = matplotlib.get_data_path()
mgr = fm.FontManager()
mgr.ttflist = [e for e in mgr.ttflist if os.path.abspath(e.fname).startswith(os.path.abspath(data_path))]
mgr.afmlist = [e for e in mgr.afmlist if os.path.abspath(e.fname).startswith(os.path.abspath(data_path))]
with open(out, "w", encoding="utf-8") as f:
    json.dump(mgr, f, cls=fm._JSONEncoder, indent=1)
print("wrote", out, "version", fm.FontManager.__version__, "ttf:", len(mgr.ttflist), "afm:", len(mgr.afmlist))
