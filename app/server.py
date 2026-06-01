#!/usr/bin/env python3
"""
ETF Analysis — dynamic web app backend.

Zero-dependency (Python standard library only) on purpose: this runs in a
sandbox where `pip install` is blocked (no outbound network to PyPI). It serves
a small JSON API over the theme data files in app/data/*.json plus the static
frontend in app/static/.

Run:    python3 app/server.py            # then open http://127.0.0.1:8000
        python3 app/server.py --port 9000

NOTE ON DATA: the backend serves PRE-POPULATED theme files. It does not fetch
live ETF data at runtime, because outbound internet is blocked in this
environment. Data is refreshed out-of-band (via web search) and written into
app/data/*.json. See docs/DATA-SOURCES.md.
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
# Canonical app is the Vercel layout at repo-root: public/ (static) + public/data.
# This local stdlib server now serves the SAME files so there's a single source
# of truth. (The live /api/etf refresh only runs on Vercel; locally you get the
# curated static data, which is the whole analysis.)
DATA_DIR = os.path.join(REPO_ROOT, "public", "data")
STATIC_DIR = os.path.join(REPO_ROOT, "public")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def load_themes():
    """Read every app/data/*.json theme file. Returns (themes, errors)."""
    themes, errors = {}, []
    if not os.path.isdir(DATA_DIR):
        return themes, [f"data directory not found: {DATA_DIR}"]
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(DATA_DIR, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                theme = json.load(fh)
            tid = theme.get("id") or os.path.splitext(fn)[0]
            theme["id"] = tid
            themes[tid] = theme
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{fn}: {exc}")
    return themes, errors


class Handler(BaseHTTPRequestHandler):
    server_version = "ETFAnalysis/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # --- helpers ---------------------------------------------------------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        ext = os.path.splitext(path)[1]
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send_json({"error": "not found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- routing ---------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path

        # API: list of themes (summary only)
        if path == "/api/themes":
            themes, errors = load_themes()
            summary = [
                {
                    "id": t["id"],
                    "name": t.get("name", t["id"]),
                    "as_of": t.get("as_of"),
                    "tagline": t.get("tagline", ""),
                    "etf_count": len(t.get("etfs", [])),
                }
                for t in themes.values()
            ]
            summary.sort(key=lambda s: s["name"])
            return self._send_json({"themes": summary, "errors": errors})

        # API: one full theme (with all ETFs + memos)
        if path.startswith("/api/theme/"):
            tid = path[len("/api/theme/"):]
            themes, _ = load_themes()
            if tid in themes:
                return self._send_json(themes[tid])
            return self._send_json({"error": f"theme '{tid}' not found"}, 404)

        # Static files
        if path in ("/", ""):
            return self._send_file(os.path.join(STATIC_DIR, "index.html"))
        # prevent path traversal; serve only from STATIC_DIR
        safe = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(STATIC_DIR, safe)
        if os.path.commonpath([os.path.abspath(full), STATIC_DIR]) != STATIC_DIR:
            return self._send_json({"error": "forbidden"}, 403)
        if os.path.isfile(full):
            return self._send_file(full)
        return self._send_json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="ETF Analysis web app")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    themes, errors = load_themes()
    print(f"ETF Analysis — loaded {len(themes)} theme(s): "
          f"{', '.join(themes) or '(none)'}")
    for e in errors:
        print(f"  ! data error: {e}")
    print(f"Serving on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        httpd.shutdown()


if __name__ == "__main__":
    main()
