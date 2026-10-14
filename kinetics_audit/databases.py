import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from kinetics_audit.search import USER_AGENT, _public_https
from kinetics_audit.vectors import embed

_SOLUTION_SEARCH = "https://kinetics.nist.gov/solution/SearchForm"
_SOLUTION_ROOT = "https://kinetics.nist.gov/solution/"
_ENZYME_SEARCH = "https://sabiork.h-its.org/export-api/sabio/kinlaw-entry/json"
_TERM = re.compile(r"^[\w\s.+\-(),/]{1,80}$", re.UNICODE)
_DETAIL_LINK = re.compile(r"Detail\?id=([^\"'&\s<>]+)", re.I)
_LABELS = (
    "Data type",
    "Experimental method",
    "Analytical technique",
    "Comment",
    "Log(A)",
    "Activation energy (kJ /RT)",
    "Temperature range (K)",
    "pH range",
)
_COLUMN_NAMES = {
    "temperature (k)": "温度",
    "ph": "pH",
    "pressure (mpa)": "压力",
    "rate constant": "速率常数",
    "reaction order": "反应级数",
    "ionic strength": "离子强度",
}


def search_solution(reactant, solvent=""):
    reactant = _term(reactant)
    solvent = _term(solvent, required=False)
    if reactant is None or solvent is None:
        raise ValueError("query_required")
    form = {"database": "solution", "REACTANT1": reactant}
    if solvent:
        form["SOLVENT1"] = solvent
    page = _request(_SOLUTION_SEARCH, form).decode("utf-8", "replace")
    if _down(page):
        raise ValueError("database_unavailable")
    found = []
    for url in solution_links(page):
        try:
            detail = _request(url).decode("utf-8", "replace")
        except ValueError:
            continue
        if _down(detail):
            continue
        text = solution_record(detail)
        if not text:
            continue
        found.append({"title": reactant, "url": url, "text": text})
        if len(found) == 4:
            break
    return found


def search_enzyme(substrate, enzyme="", organism=""):
    substrate = _term(substrate)
    enzyme = _term(enzyme, required=False)
    organism = _term(organism, required=False)
    if substrate is None or enzyme is None or organism is None:
        raise ValueError("query_required")
    parts = [f'Substrate:"{substrate}"']
    if enzyme:
        parts.append(f'Enzymename:"{enzyme}"')
    if organism:
        parts.append(f'Organism:"{organism}"')
    url = _ENZYME_SEARCH + "?pageSize=4&q=" + urllib.parse.quote(" AND ".join(parts))
    payload = json.loads(_request(url).decode("utf-8", "replace"))
    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError("database_unavailable")
    return [item for item in (enzyme_record(record) for record in records) if item][:4]


def solution_links(page):
    found = []
    seen = set()
    for raw in _DETAIL_LINK.findall(page or ""):
        identifier = urllib.parse.unquote(raw).strip()
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        quoted = urllib.parse.quote(identifier, safe="/:")
        found.append(urllib.parse.urljoin(_SOLUTION_ROOT, "Detail?id=" + quoted))
        if len(found) == 4:
            break
    return found


def solution_record(page):
    reaction = _labeled(page, "Reaction")
    solvent = _solvent(page)
    rows = _table_rows(page)
    labels = [_loose(page, label) for label in _LABELS]
    pieces = ["NDRL/NIST 溶液动力学库记录。"]
    if reaction:
        pieces.append(f"反应 {reaction}。")
    if solvent:
        pieces.append(f"溶剂 {solvent}。")
    for row in rows:
        pieces.append(row + "。")
    for label, value in zip(_LABELS, labels):
        if value:
            pieces.append(f"{label}: {value}。")
    author = _labeled(page, "Author(s)")
    year = _labeled(page, "Year")
    title = _labeled(page, "Title")
    if author:
        pieces.append(f"Author(s): {author}。")
    if year:
        pieces.append(f"Year: {year}。")
    if title:
        pieces.append(f"Title: {title}。")
    text = "".join(pieces)
    if "速率常数" not in text and "Activation energy" not in text:
        return ""
    return text


def enzyme_record(record):
    if not isinstance(record, dict):
        return None
    entry_id = record.get("id")
    if not isinstance(entry_id, int):
        return None
    reaction = (record.get("reaction") or {}).get("equation") or ""
    enzyme = (record.get("enzyme_description") or {}).get("enzyme_name") or ""
    general = record.get("general") or {}
    organism = (general.get("organism") or {}).get("name") or ""
    conditions = record.get("experimental_conditions") or {}
    temperature = conditions.get("envvar_temperature") or {}
    ph = conditions.get("envvar_ph") or {}
    publication = record.get("publication") or {}
    pieces = [f"SABIO-RK 条目 {entry_id}。"]
    if reaction:
        pieces.append(f"反应 {reaction}。")
    if enzyme:
        pieces.append(f"酶 {enzyme}。")
    if organism:
        pieces.append(f"生物 {organism}。")
    if conditions.get("buffer"):
        pieces.append(f"缓冲液 {conditions['buffer']}。")
    ph_text = _span(ph.get("start_value"), ph.get("end_value"), "")
    if ph_text:
        pieces.append(f"pH {ph_text}。")
    temperature_text = _span(temperature.get("start_value"), temperature.get("end_value"), temperature.get("unit") or "")
    if temperature_text:
        pieces.append(f"温度 {temperature_text}。")
    for parameter in _constants(record):
        unit = ((parameter.get("unit") or {}).get("name") or "").strip()
        value = _span(parameter.get("start_value"), parameter.get("end_value"), unit)
        name = ((parameter.get("parameter_type") or {}).get("name") or parameter.get("name") or "").strip()
        if name and value:
            pieces.append(f"{name} {value}。")
    citation = " ".join(
        str(publication.get(key)).strip()
        for key in ("author", "journal", "year", "title")
        if publication.get(key)
    )
    if citation:
        pieces.append(f"文献 {citation}。")
    text = "".join(pieces)
    if "温度" not in text and "kcat" not in text.casefold() and "rate constant" not in text.casefold():
        return None
    return {
        "title": reaction or f"SABIO-RK {entry_id}",
        "url": f"https://sabiork.h-its.org/export-api/sabio/kinlaw-entry/json/{entry_id}",
        "text": text,
    }


def remember(job, claim_id, database, records):
    for item in records:
        sentences = [{"id": "s0", "text": item["text"], "vector": embed(item["text"])}]
        job.references[item["url"]] = {
            "title": item["title"],
            "text": item["text"],
            "sentences": sentences,
            "local": True,
        }
    job.searches.append(
        {"claim_id": claim_id, "database": database, "urls": [item["url"] for item in records]}
    )


def _request(url, data=None):
    if not _public_https(url):
        raise ValueError("url")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html"}
    payload = None
    if data is not None:
        payload = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            final = response.geturl()
            if urllib.parse.urlparse(final).netloc != urllib.parse.urlparse(url).netloc:
                raise ValueError("database_unavailable")
            return response.read(200_000)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError("database_unavailable") from exc


def _term(value, required=True):
    if value is None:
        value = ""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return "" if not required else None
    if not _TERM.fullmatch(text):
        return None
    return text


def _down(page):
    plain = _plain(page)
    return "Unable to connect to database" in plain or "pool error" in plain


def _loose(page, label):
    found = _labeled(page, label)
    if found:
        return found
    later = "|".join(re.escape(item) for item in _LABELS if item != label)
    match = re.search(rf"{re.escape(label)}\s*:\s*(.+?)(?:\s+(?:{later})\s*:|$)", _plain(page))
    if not match:
        return ""
    return " ".join(match.group(1).split())


def _labeled(page, label):
    match = re.search(
        rf"{re.escape(label)}\s*:?\s*</B>(.*?)(?:<BR|<P|</TABLE|</TD)",
        page or "",
        re.I | re.S,
    )
    if not match:
        return ""
    return _plain(match.group(1)).lstrip(":").strip()


def _solvent(page):
    match = re.search(r"Solvent details.*?<B>\s*Name\s*</B>(.*?)<BR>", page or "", re.I | re.S)
    if not match:
        return ""
    return _plain(match.group(1))


def _table_rows(page):
    table = re.search(r"Reaction data.*?<TABLE[^>]*>(.*?)</TABLE>", page or "", re.I | re.S)
    if not table:
        return []
    parts = re.split(r"(?i)<TR>", table.group(1))[1:]
    if not parts:
        return []
    headers = [_plain(item).casefold() for item in re.findall(r"<TH>(.*?)</TH>", parts[0], re.I | re.S)]
    rows = []
    for raw in parts[1:]:
        cells = [_plain(item) for item in re.findall(r"<TD>(.*?)</TD>", raw, re.I | re.S)]
        pairs = []
        for header, cell in zip(headers, cells):
            name = _COLUMN_NAMES.get(header)
            if name and cell and cell != "\xa0":
                pairs.append(f"{name} {cell}")
        if pairs:
            rows.append("，".join(pairs))
        if len(rows) == 2:
            break
    return rows


def _constants(record):
    parameters = (record.get("kineticlaw") or {}).get("parameter") or []
    kept = []
    for item in parameters:
        if not isinstance(item, dict) or item.get("role") == "Variable" or item.get("start_value") is None:
            continue
        kept.append(item)
        if len(kept) == 6:
            break
    return kept


def _span(start, end, unit):
    if start is None:
        return ""
    text = _num(start)
    if end not in (None, start):
        text = f"{text}-{_num(end)}"
    unit = str(unit or "").strip()
    return f"{text} {unit}".strip()


def _num(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _plain(value):
    text = re.sub(r"(?is)<img[^>]*>", " -> ", value or "")
    text = re.sub(r"(?is)</?su[bp]>", "", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())
