"""Import pipeline: read -> validate -> filter -> export."""

import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from reliable_importer.exceptions import RecordValidationError
from reliable_importer.exporters import ErrorReport, get_exporter
from reliable_importer.models import AppConfig, Student
from reliable_importer.readers import get_importer
from reliable_importer.utils import logged_operation
from reliable_importer.validators import parse_student

logger = logging.getLogger(__name__)


@dataclass
class ImportStatistics:
    total: int = 0
    valid: int = 0
    invalid: int = 0
    invalid_by_field: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RunReport:
    statistics: ImportStatistics
    exported: int

    def summary(self) -> str:
        s = self.statistics
        return (
            f"Total={s.total}, valid={s.valid}, invalid={s.invalid}, "
            f"exported={self.exported}"
        )


def import_students(
    path: Path,
    *,
    skip_invalid: bool,
    statistics: ImportStatistics,
    on_error: Callable[[RecordValidationError], None] | None = None,
) -> Iterator[Student]:
    """Streaming import: valid objects are created one by one.

    Tolerant mode (skip_invalid=True) logs and skips an invalid record,
    strict mode re-raises the first validation error.
    """
    for line_number, row in get_importer(path).read(path):
        statistics.total += 1

        try:
            student = parse_student(row, line_number=line_number)
        except RecordValidationError as error:
            statistics.invalid += 1
            key = error.field or "unknown"
            statistics.invalid_by_field[key] = statistics.invalid_by_field.get(key, 0) + 1
            logger.warning("Invalid record at line %s: %s", error.line_number, error)

            if on_error is not None:
                on_error(error)

            if skip_invalid:
                continue

            raise

        statistics.valid += 1
        yield student


def filter_by_grade(
    students: Iterable[Student], minimum_grade: float
) -> Iterator[Student]:
    for student in students:
        if student.average_grade >= minimum_grade:
            yield student


def run_import(config: AppConfig) -> RunReport:
    """Whole use case; in strict mode an error produces no output at all."""
    statistics = ImportStatistics()

    with logged_operation("Student import/export"):
        with ErrorReport(config.errors_path) as errors:
            students = import_students(
                config.input_path,
                skip_invalid=config.processing.skip_invalid,
                statistics=statistics,
                on_error=errors.add,
            )
            selected = filter_by_grade(students, config.processing.minimum_grade)
            exported = get_exporter(config.output_path).export(
                selected, config.output_path
            )

    report = RunReport(statistics, exported)
    logger.info(report.summary())
    return report
