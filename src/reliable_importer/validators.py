"""Validation of one record; low-level errors become RecordValidationError."""

import math
import re

from reliable_importer.exceptions import RecordValidationError
from reliable_importer.models import Student

NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[-' ][^\W\d_]+)*$")
GROUP_PATTERN = re.compile(r"^\S{1,20}$")


def _name(row: dict[str, str], field: str, line_number: int) -> str:
    value = (row.get(field) or "").strip()

    if not value:
        raise RecordValidationError(
            f"{field} is empty", line_number=line_number, field=field
        )

    if not NAME_PATTERN.match(value):
        raise RecordValidationError(
            f"{field} contains invalid characters: {value!r}",
            line_number=line_number,
            field=field,
        )

    return value


def parse_student(row: dict[str, str], *, line_number: int) -> Student:
    try:
        student_id = int(row["student_id"])
    except (KeyError, TypeError, ValueError) as error:
        raise RecordValidationError(
            "Invalid student_id", line_number=line_number, field="student_id"
        ) from error

    if student_id <= 0:
        raise RecordValidationError(
            "student_id must be positive", line_number=line_number, field="student_id"
        )

    first_name = _name(row, "first_name", line_number)
    last_name = _name(row, "last_name", line_number)

    group = (row.get("group") or "").strip()
    if not group:
        raise RecordValidationError(
            "group is empty", line_number=line_number, field="group"
        )
    if not GROUP_PATTERN.match(group):
        raise RecordValidationError(
            f"Invalid group: {group!r}", line_number=line_number, field="group"
        )

    try:
        grade = float(row["average_grade"].replace(",", "."))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise RecordValidationError(
            "average_grade must be numeric",
            line_number=line_number,
            field="average_grade",
        ) from error

    if not math.isfinite(grade) or not 0 <= grade <= 100:
        raise RecordValidationError(
            "average_grade must be between 0 and 100",
            line_number=line_number,
            field="average_grade",
        )

    return Student(student_id, first_name, last_name, group, grade)
