import html
import ipaddress
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from kinetics_audit.reference_store import offline_page, offline_search

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TAGS = re.compile(r"(?is)<(script|style).*?>.*?</\1>|<[^>]+>")


def search_web(query):
    found = []
    try:
        found = _search_bing(query)
    except (OSError, ET.ParseError, ValueError, TimeoutError):
        found = []
    if not found:
        found = offline_search(query)
    return found


def fetch_page(url):
    cached = offline_page(url)
    if cached is not None:
        return cached[:6000]
    if not _public_https(url):
        raise ValueError("url")
    try:
        payload = _get(url, 200_000)
    except (OSError, ValueError, TimeoutError):
        raise ValueError("fetch_failed") from None
    return _plain(payload.decode("utf-8", "replace"))[:6000]


def _search_bing(query):
    url = "https://cn.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
    payload = _get(url, 500_000)
    root = ET.fromstring(payload)
    found = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        excerpt = _plain(item.findtext("description") or "")
        if not title or not excerpt or not link.startswith("https://"):
            continue
        if not _public_https(link):
            continue
        if not useful_result(title, link):
            continue
        found.append({"title": title, "url": link, "excerpt": excerpt[:500]})
        if len(found) == 8:
            break
    return found


def _get(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=12) as response:
        return response.read(limit)


def useful_result(title, url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    folded = f"{title} {url}".casefold()
    if any(name in host for name in ("baike.", "iciba.com", "dict.", "youdao.com", "speedtest.")):
        return False
    if "/dict/" in url.casefold() or "zhihu.com" in host or "donanimhaber.com" in host:
        return False
    if any(word in folded for word in ("百科", "词典", "释义")):
        return False
    return True


def _plain(value):
    text = _TAGS.sub(" ", html.unescape(value))
    return " ".join(text.split())


def _public_https(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return address.is_global
