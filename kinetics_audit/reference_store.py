import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "reference_cache"
_INDEX = None


def offline_search(query):
    folded = _fold(query)
    if not folded:
        return []
    hits = []
    for page in _pages():
        tags = page.get("tags") or []
        if not any(_fold(tag) in folded for tag in tags):
            continue
        text = page.get("text") or ""
        hits.append(
            {
                "title": page["title"],
                "url": page["url"],
                "excerpt": text[:80],
                "offline": True,
            }
        )
        if len(hits) == 8:
            break
    return hits


def offline_page(url):
    if not isinstance(url, str) or not url:
        return None
    for page in _pages():
        if page.get("url") == url:
            return page.get("text") or ""
    return None


def _pages():
    global _INDEX
    if _INDEX is None:
        path = _ROOT / "catalog.json"
        if not path.is_file():
            _INDEX = {"pages": []}
        else:
            _INDEX = json.loads(path.read_text(encoding="utf-8"))
    return _INDEX.get("pages") or []


def _fold(text):
    return "".join((text or "").split()).casefold()
