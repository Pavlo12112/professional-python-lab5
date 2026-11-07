"""Streaming readers (importers): CSV and JSON Lines."""

import csv
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from reliable_importer.exceptions import DataImportError

REQUIRED_COLUMNS = ("student_id", "first_name", "last_name", "group", "average_grade")

Row = dict[str, str]


class Importer(Protocol):
    """Common interface of all importers: yields (line number, row)."""

    def read(self, path: Path) -> Iterator[tuple[int, Row]]: ...


def _check_columns(columns: list[str] | None, path: Path) -> None:
    missing = [c for c in REQUIRED_COLUMNS if not columns or c not in columns]
    if missing:
        raise DataImportError(f"Missing columns in {path}: {', '.join(missing)}")


def read_csv_rows(path: Path) -> Iterator[tuple[int, Row]]:
    """Stream rows of a CSV file one by one; the file is never read whole."""
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            _check_columns(reader.fieldnames and list(reader.fieldnames), path)

            for line_number, row in enumerate(reader, start=2):
                yield line_number, {k: v or "" for k, v in row.items() if k is not None}
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise DataImportError(f"Cannot read input file: {path}") from error


def read_jsonl_rows(path: Path) -> Iterator[tuple[int, Row]]:
    """Stream a JSON Lines file: one JSON object per line."""
    try:
        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as error:
                    raise DataImportError(
                        f"Invalid JSON at line {line_number} of {path}"
                    ) from error
                if not isinstance(obj, dict):
                    raise DataImportError(f"Line {line_number} is not a JSON object")
                yield line_number, {
                    str(k): "" if v is None else str(v) for k, v in obj.items()
                }
    except (OSError, UnicodeDecodeError) as error:
        raise DataImportError(f"Cannot read input file: {path}") from error


class CsvImporter:
    def read(self, path: Path) -> Iterator[tuple[int, Row]]:
        return read_csv_rows(path)


class JsonLinesImporter:
    def read(self, path: Path) -> Iterator[tuple[int, Row]]:
        return read_jsonl_rows(path)


def get_importer(path: Path) -> Importer:
    """Choose an importer by file extension."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return CsvImporter()
    if suffix in (".jsonl", ".ndjson"):
        return JsonLinesImporter()
    raise DataImportError(f"Unsupported input format: {suffix or path.name}")
