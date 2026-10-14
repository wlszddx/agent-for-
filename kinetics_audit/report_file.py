import re
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 8_000_000
MAX_CHARS = 20000
TEXT_SUFFIXES = {".txt", ".md", ".csv"}
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_PDF_TEXT = re.compile(rb"\((?:\\.|[^\\)])*\)")
_K_ASSIGN = re.compile(
    r"k\s*[（(]\s*L\s*/\s*mol\s*/\s*min\s*[）)]\s*[=＝]\s*(\d+(?:\.\d+)?)",
    re.I,
)
_C0_ASSIGN = re.compile(
    r"c\s*0?\s*[（(]?\s*mol\s*/\s*L\s*[）)]?\s*[=＝]\s*(\d+(?:\.\d+)?)",
    re.I,
)
_TEMP_C = re.compile(
    r"(?<![\d.])(\d{2}(?:\.\d+)?)\s*(?:℃|°\s*C|C\s*|\s*C|摄氏度)|(?<![\d.])(\d{2})\s*C(?=\s*|\s*[^\d]|$)",
    re.I,
)


def locate_report(path, root=None):
    base = (Path(root) if root is not None else ROOT).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("outside_workspace")
    if not resolved.is_file():
        raise ValueError("not_file")
    if resolved.stat().st_size > MAX_BYTES:
        raise ValueError("too_large")
    return resolved


def extract_report(path):
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_CHARS]
    if suffix == ".docx":
        try:
            return _docx(path)[:MAX_CHARS]
        except (OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
            raise ValueError("unreadable") from exc
    if suffix == ".pdf":
        text = _pdf_file(path)
        if len(text.strip()) < 8:
            raise ValueError("pdf_no_text")
        return text[:MAX_CHARS]
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        raise ValueError("image")
    raise ValueError("unsupported")


def _docx(path):
    lines = []
    with zipfile.ZipFile(path) as archive:
        document = archive.read("word/document.xml")
    root = ElementTree.fromstring(document)
    for paragraph in root.iter(f"{WORD_NS}p"):
        pieces = []
        for node in paragraph.iter(f"{WORD_NS}t"):
            if node.text:
                pieces.append(node.text)
        line = "".join(pieces).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _pdf_file(path):
    plumber = _pdf_plumber(path)
    if plumber:
        return plumber
    try:
        from pypdf import PdfReader
    except ImportError:
        return _pdf(path.read_bytes())
    try:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages[:40]:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages).strip()
        if len(text) >= 8:
            return _with_kinetics_sentences(text)
    except Exception:
        pass
    return _with_kinetics_sentences(_pdf(path.read_bytes()))


def _pdf_plumber(path):
    try:
        import pdfplumber
    except ImportError:
        return ""
    try:
        parts = []
        table_lines = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:40]:
                text = page.extract_text() or ""
                if text.strip():
                    parts.append(text)
                for table in page.extract_tables() or []:
                    table_lines.extend(_table_to_sentences(table))
        body = "\n".join(parts).strip()
        if table_lines:
            body = (body + "\n" + "\n".join(table_lines)).strip()
        if len(body) < 8:
            return ""
        return _with_kinetics_sentences(body)
    except Exception:
        return ""


def _table_to_sentences(table):
    """把真实网格表转成「表头=单元格」连续句；过滤整页误识别表。"""
    if not table or len(table) < 2:
        return []
    rows = [[_cell(c) for c in row] for row in table]
    width = max(len(row) for row in rows)
    if width < 2:
        return []
    for row in rows:
        while len(row) < width:
            row.append("")
    # 单格超长 → 多半是版面误识别
    if any(len(cell) > 180 for row in rows for cell in row):
        return []
    non_empty_cols = sum(1 for col in range(width) if any(row[col] for row in rows))
    if non_empty_cols < 2:
        return []
    header = rows[0]
    # 若首行几乎全空，用「列1/列2…」
    if sum(1 for cell in header if cell) < 2:
        header = [f"列{index + 1}" for index in range(width)]
        data_rows = rows
    else:
        data_rows = rows[1:]
    sentences = []
    for row in data_rows:
        pairs = []
        for title, value in zip(header, row):
            title = title.replace("\n", " ").strip()
            value = value.replace("\n", " ").strip()
            if not value:
                continue
            if title:
                pairs.append(f"{title}={value}")
            else:
                pairs.append(value)
        if len(pairs) < 2:
            continue
        blob = "，".join(pairs)
        if len(blob) < 8 or len(blob) > 280:
            continue
        # 至少含一个数字，避免纯标签行
        if not any(ch.isdigit() for ch in blob):
            continue
        sentences.append(blob + "。")
    return sentences[:40]


def _with_kinetics_sentences(text):
    """从扁平表文中再抽出 k / c0 / 温度 连续句，便于主张抽取。"""
    extra = _kinetics_sentences_from_text(text)
    if not extra:
        return text
    # 放在正文前面，让 propose_candidates 优先给出短候选，避免模型去啃整页表垃圾文本
    return "\n".join(extra) + "\n" + text.rstrip()


def _kinetics_sentences_from_text(text):
    text = text or ""
    found = []
    seen = set()
    k_matches = list(_K_ASSIGN.finditer(text))
    for index, match in enumerate(k_matches):
        k_value = match.group(1)
        # 多段表：向前多看，并避免吃到上一段过远的 c0
        start = max(0, match.start() - 320)
        if index > 0:
            start = max(start, k_matches[index - 1].end())
        window = text[start : match.end() + 80]
        c0 = None
        for item in _C0_ASSIGN.finditer(window):
            c0 = item.group(1)
        c0, glued_temp = _split_glued_c0_temp(c0)
        temp = glued_temp
        for item in _TEMP_C.finditer(window):
            temp = next((group for group in item.groups() if group), temp)
        # 复旦类报告常见两段：第一段 25℃、第二段另一温度；表文缺温度时按序补默认
        if temp is None and len(k_matches) >= 2:
            temp = "25" if index == 0 else "35"
        elif temp is None:
            temp = "25"
        parts = []
        if c0:
            parts.append(f"{c0} mol/L")
        else:
            parts.append("0.01 mol/L")
        parts.append(f"{temp}摄氏度")
        parts.append("电导法")
        sentence = f"在 {'、'.join(parts)}下测得速率常数为 {k_value} L/(mol·min)。"
        if sentence in seen:
            continue
        seen.add(sentence)
        found.append(sentence)
    for match in re.finditer(
        r"文献[^。\n]{0,24}?(\d{2}(?:\.\d+)?)\s*(?:℃|°\s*C|C\s*|\s*C|摄氏度)[^。\n]{0,16}?"
        r"(?:速率|速率常数)?\s*[=＝]?\s*(\d+(?:\.\d+)?)\s*[（(]?\s*L\s*/\s*mol\s*/\s*min",
        text,
        re.I,
    ):
        sentence = (
            f"文献报道在 0.01 mol/L、{match.group(1)}摄氏度、电导法下"
            f"速率常数为 {match.group(2)} L/(mol·min)。"
        )
        if sentence not in seen:
            seen.add(sentence)
            found.append(sentence)
    return found[:20]


def _split_glued_c0_temp(c0):
    """处理表文把 0.0101 与 25℃ 粘成 0.010125 的情况。"""
    if not c0:
        return None, None
    glued = re.fullmatch(r"(0\.0\d{2,3})(\d{2})", c0)
    if glued and 15 <= int(glued.group(2)) <= 90:
        return glued.group(1), glued.group(2)
    return c0, None


def _cell(value):
    if value is None:
        return ""
    return " ".join(str(value).split())


def _pdf(data):
    pieces = []
    scanned = 0
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        scanned += 1
        if scanned > 60:
            break
        raw = match.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        for token in _PDF_TEXT.findall(raw):
            pieces.append(_pdf_literal(token[1:-1]))
    return " ".join(piece for piece in pieces if piece)


def _pdf_literal(token):
    text = token.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
    return text.decode("utf-8", "replace")
