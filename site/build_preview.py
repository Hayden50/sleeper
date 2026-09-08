"""
Builds single-file, Artifact-preview versions of the site's pages: CSS
inlined and Sleeper avatar images embedded as base64 data URIs.

Only needed for previewing the design as a Claude Artifact (that sandbox
blocks image loads from arbitrary external hosts, so sleepercdn.com avatars
have to be inlined, and each page has to be self-contained since relative
links between pages don't resolve inside a single published artifact - the
"back to rankings" / glossary links in these preview files are inert).
The real deployable site (site/index.html, site/stats/variance.html) does
not need any of this - it links style.css and Sleeper avatars normally.

Run generate.py first so the source pages are up to date.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.request
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
AVATAR_CACHE = SITE_DIR / "_avatar_datauris.json"


def fetch_avatar_data_uris(urls: set[str]) -> dict[str, str]:
    cache = json.loads(AVATAR_CACHE.read_text()) if AVATAR_CACHE.exists() else {}
    missing = urls - cache.keys()
    for url in missing:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "image/jpeg")
        cache[url] = f"data:{ctype};base64,{base64.b64encode(data).decode()}"
    AVATAR_CACHE.write_text(json.dumps(cache))
    return cache


def build_single_file_preview(source_path: Path, css_path: Path, out_path: Path) -> None:
    html = source_path.read_text()
    css = css_path.read_text()

    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    font_link = re.search(r'<link rel="stylesheet" href="https://fonts\.googleapis\.com[^"]*">', html).group(0)

    urls = set(re.findall(r'src="(https://sleepercdn[^"]+)"', body))
    data_uris = fetch_avatar_data_uris(urls)
    for url, data_uri in data_uris.items():
        body = body.replace(url, data_uri)

    out = f"<title>{title}</title>\n{font_link}\n<style>\n{css}\n</style>\n{body}"
    out_path.write_text(out)
    print(f"Wrote {out_path}")


def main():
    build_single_file_preview(
        SITE_DIR / "index.html", SITE_DIR / "style.css", SITE_DIR / "_artifact_preview.html"
    )
    build_single_file_preview(
        SITE_DIR / "stats" / "variance.html", SITE_DIR / "style.css", SITE_DIR / "_artifact_preview_variance.html"
    )


if __name__ == "__main__":
    main()
