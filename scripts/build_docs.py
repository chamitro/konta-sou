"""Build docs/index.html (GitHub Pages) from the app page, pointing it at a hosted API.

Usage: .venv/bin/python scripts/build_docs.py https://api.example.com
The page is identical to the one the server serves at /, plus one line setting window.KONTA_API.
"""
import sys
from pathlib import Path

api = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else ""
src = Path("simera/web/index.html").read_text(encoding="utf-8")
out = src.replace("<script>\nconst API", f'<script>window.KONTA_API = "{api}";</script>\n<script>\nconst API', 1)
Path("docs/index.html").write_text(out, encoding="utf-8")
print(f"docs/index.html written, API = {api or '(same origin)'}")
