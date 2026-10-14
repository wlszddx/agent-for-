import csv
from pathlib import Path


def write_rows(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cell(row[key]) for key in fieldnames})


def read_rows(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        loaded = []
        for row in csv.DictReader(handle):
            loaded.append({key: _coerce(key, value) for key, value in row.items()})
    return loaded


def public_rows(rows):
    table = []
    for row in rows:
        table.append({key: _public(value) for key, value in row.items()})
    return table


def _cell(value):
    if isinstance(value, float):
        return f"{value:.16g}"
    return value


def _public(value):
    if isinstance(value, float):
        return float(f"{value:.8g}")
    return value


def _coerce(key, value):
    text = value.strip()
    if key == "run_id" or key.endswith("_id"):
        return int(text)
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer() and "e" not in text.lower() and "." not in text:
        return int(number)
    return number
