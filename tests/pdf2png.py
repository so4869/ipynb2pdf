import sys, pymupdf
src, out, dpi = sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 70
doc = pymupdf.open(src)
print("pages:", len(doc))
for i, page in enumerate(doc):
    page.get_pixmap(dpi=dpi).save("%s_p%02d.png" % (out, i + 1))
