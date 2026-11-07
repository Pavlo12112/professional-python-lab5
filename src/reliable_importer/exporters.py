"""Exporters: atomic JSON / JSON Lines output and the error report."""

import csv
import json
import textwrap
from collections.abc import Iterable
from contextlib import ExitStack
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

from reliable_importer.exceptions import DataExportError, RecordValidationError
from reliable_importer.models import Student
from reliable_importer.utils import atomic_writer


class Exporter(Protocol):
    def export(self, students: Iterable[Student], path: Path) -> int: ...


class JsonExporter:
    """Streaming JSON array: records are written one by one."""

    def __init__(self, *, backup: bool = False) -> None:
        self._backup = backup

    def export(self, students: Iterable[Student], path: Path) -> int:
        count = 0

        try:
            with atomic_writer(path, backup=self._backup) as file:
                file.write("[\n")
                for student in students:
                    if count:
                        file.write(",\n")
                    text = json.dumps(student.to_dict(), ensure_ascii=False, indent=2)
                    file.write(textwrap.indent(text, "  "))
                    count += 1
                file.write("\n]\n")
        except TypeError as error:
            raise DataExportError(f"Data cannot be serialized to JSON: {path}") from error

        return count


class JsonLinesExporter:
    """JSON Lines: one object per line, convenient for huge outputs."""

    def __init__(self, *, backup: bool = False) -> None:
        self._backup = backup

    def export(self, students: Iterable[Student], path: Path) -> int:
        count = 0

        try:
            with atomic_writer(path, backup=self._backup) as file:
                for student in students:
                    file.write(json.dumps(student.to_dict(), ensure_ascii=False) + "\n")
                    count += 1
        except TypeError as error:
            raise DataExportError(f"Data cannot be serialized to JSON: {path}") from error

        return count


def get_exporter(path: Path, *, backup: bool = False) -> Exporter:
    """Choose an exporter by file extension."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return JsonExporter(backup=backup)
    if suffix in (".jsonl", ".ndjson"):
        return JsonLinesExporter(backup=backup)
    raise DataExportError(f"Unsupported output format: {suffix or path.name}")


class ErrorReport:
    """Context manager writing invalid records to a separate CSV file.

    ``None`` as a path disables the report. The file is written atomically,
    so a failed run leaves no partial report.
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._stack: ExitStack | None = None
        self._writer: Any = None

    def __enter__(self) -> "ErrorReport":
        if self._path is not None:
            self._stack = ExitStack()
            file = self._stack.enter_context(atomic_writer(self._path))
            self._writer = csv.writer(file)
            self._writer.writerow(["line_number", "field", "message"])
        return self

    def add(self, error: RecordValidationError) -> None:
        if self._writer is not None:
            self._writer.writerow([error.line_number, error.field, str(error)])

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if self._stack is not None:
            return bool(self._stack.__exit__(exc_type, exc_value, traceback))
        return False
