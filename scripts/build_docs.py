"""Build docs/index.html (GitHub Pages) from the app page, pointing it at a hosted API.

Usage: .venv/bin/python scripts/build_docs.py https://api.example.com [https://relay.workers.dev] [G-XXXXXXXXXX]
The page is identical to the one the server serves at /, plus one line setting window.KONTA_API
(and window.KONTA_RELAY when a relay worker address is given; the browser then asks OASA through it).
A third argument sets window.KONTA_GA (Google Analytics measurement id) on both pages; the pages only
load Analytics after the visitor accepts the consent bar.
"""
import re
import sys
from pathlib import Path

api = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else ""
relay = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else ""
ga = sys.argv[3].strip() if len(sys.argv) > 3 else ""
src = Path("simera/web/index.html").read_text(encoding="utf-8")
out = src.replace("<script>\nconst API", f'<script>window.KONTA_API = "{api}"; window.KONTA_RELAY = "{relay}"; window.KONTA_GA = "{ga}";</script>\n<script>\nconst API', 1)
Path("docs/index.html").write_text(out, encoding="utf-8")
# PWA files (manifest, service worker, icons) are published next to the page
import shutil
for name in ("manifest.webmanifest", "sw.js"):
    shutil.copy(Path("simera/web") / name, Path("docs") / name)
Path("docs/icons").mkdir(exist_ok=True)
for ic in (Path("simera/web/icons")).glob("*.png"):
    shutil.copy(ic, Path("docs/icons") / ic.name)
about = Path("docs/about.html")
about.write_text(re.sub(r'window\.KONTA_GA = "[^"]*";', f'window.KONTA_GA = "{ga}";', about.read_text(encoding="utf-8"), count=1), encoding="utf-8")
print(f"docs/index.html written, API = {api or '(same origin)'}, relay = {relay or '(none)'}")
