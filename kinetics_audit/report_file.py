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
        text = _pdf(path.read_bytes())
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


def _pdf(data):
    pieces = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
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
