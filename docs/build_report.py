"""Turn REPORT.md into REPORT.html and REPORT.pdf (A4), and count the pages.

    ../.venv/bin/python build_report.py        # needs google-chrome for the PDF
"""
import re
import subprocess
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
CSS = """@page{size:A4;margin:16mm 15mm}
body{font-family:'Noto Sans',Arial,sans-serif;font-size:10.5pt;line-height:1.34;color:#111}
h1{font-size:18pt;margin:0 0 4px}h2{font-size:12pt;margin:11px 0 3px;border-bottom:1px solid #111}
p{margin:4px 0}table{border-collapse:collapse;width:100%;font-size:9pt;margin:4px 0}
th,td{border-bottom:1px solid #bbb;padding:2px 5px;text-align:left;vertical-align:top}
img{display:block;margin:5px auto;max-width:100%;max-height:72mm}
ul{margin:3px 0 3px 16px;padding:0}li{margin:1px 0}em{font-size:9pt;color:#444}code{font-size:9.2pt}"""

body = markdown.markdown((HERE / "REPORT.md").read_text(), extensions=["tables"])
(HERE / "REPORT.html").write_text(
    "<!doctype html><html><head><meta charset='utf-8'><title>ValleyWatch report</title>"
    f"<style>{CSS}</style></head><body>{body}</body></html>")
subprocess.run(["google-chrome", "--headless", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={HERE / 'REPORT.pdf'}", f"file://{HERE / 'REPORT.html'}"],
               check=True, capture_output=True)
pages = len(re.findall(rb"/Type\s*/Page[^s]", (HERE / "REPORT.pdf").read_bytes()))
print(f"REPORT.pdf: {pages} pages (limit 6)")
