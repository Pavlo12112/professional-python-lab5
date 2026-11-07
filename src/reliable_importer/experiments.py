"""Experiments of the laboratory work (run: python -m reliable_importer.experiments)."""

import csv
import json
import logging
import tempfile
import tracemalloc
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path
from time import perf_counter

from reliable_importer.config import load_config
from reliable_importer.exceptions import ApplicationError, RecordValidationError
from reliable_importer.exporters import JsonExporter
from reliable_importer.models import (
    AppConfig,
    LoggingConfig,
    ProcessingConfig,
    Student,
)
from reliable_importer.services import (
    ImportStatistics,
    filter_by_grade,
    import_students,
    run_import,
)
from reliable_importer.validators import parse_student

HEADER = ["student_id", "first_name", "last_name", "group", "average_grade"]
GROUPS = ("FeP-31", "FeP-32", "FeP-33s", "FeP-34")


def write_dataset(path: Path, valid: int, invalid: int = 0) -> None:
    """CSV with ``valid`` correct rows and ``invalid`` broken rows spread among them."""
    step = max(1, valid // invalid) if invalid else 0
    broken = 0

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)

        for i in range(1, valid + 1):
            writer.writerow([i, f"Name{chr(97 + i % 26)}", f"Surname{chr(97 + i % 26)}",
                             GROUPS[i % 4], round(40 + (i * 37) % 6000 / 100, 2)])
            if step and i % step == 0 and broken < invalid:
                writer.writerow([f"bad{i}", "", "X", GROUPS[0], "abc"])
                broken += 1


def make_config(directory: Path, input_path: Path, *, skip_invalid: bool,
                minimum: float = 60.0, errors: bool = False) -> AppConfig:
    return AppConfig(
        input_path=input_path,
        output_path=directory / "out.json",
        errors_path=directory / "errors.csv" if errors else None,
        processing=ProcessingConfig(minimum_grade=minimum, skip_invalid=skip_invalid),
        logging=LoggingConfig(level="ERROR", path=directory / "app.log"),
    )


# ---------------------------------------------------------------- experiment 1
def experiment_strict_vs_tolerant() -> None:
    print("== Experiment 1. Strict vs tolerant (1000 valid + 10 invalid) ==")

    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        source = directory / "students.csv"
        write_dataset(source, valid=1000, invalid=10)
        rows = []

        for mode, skip in (("Strict", False), ("Tolerant", True)):
            config = make_config(directory, source, skip_invalid=skip, minimum=0)
            config.output_path.unlink(missing_ok=True)
            statistics = ImportStatistics()
            exported = 0
            outcome = "finished normally"

            try:
                students = import_students(source, skip_invalid=skip, statistics=statistics)
                selected = filter_by_grade(students, 0)
                exported = JsonExporter().export(selected, config.output_path)
            except RecordValidationError as error:
                outcome = f"aborted (exit 1): line {error.line_number}, {error}"

            rows.append((mode, statistics, exported, outcome, config.output_path.exists()))

        print(f"{'':10}{'processed':>10}{'valid':>8}{'invalid':>9}{'exported':>10}  output file  finish")
        for mode, st, exported, outcome, exists in rows:
            print(f"{mode:10}{st.total:>10}{st.valid:>8}{st.invalid:>9}{exported:>10}  "
                  f"{'created' if exists else 'not created':12}  {outcome}")


# ---------------------------------------------------------------- experiment 2
def eager_import(source: Path, target: Path, minimum: float) -> int:
    """Eager variant: everything is kept in lists."""
    with source.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    students = [parse_student(row, line_number=i) for i, row in enumerate(rows, start=2)]
    selected = [s.to_dict() for s in students if s.average_grade >= minimum]
    with target.open("w", encoding="utf-8") as out:
        json.dump(selected, out, ensure_ascii=False, indent=2)
    return len(selected)


def streaming_import(source: Path, target: Path, minimum: float) -> int:
    """Streaming variant: records pass through the generator pipeline one by one."""
    students = import_students(source, skip_invalid=True, statistics=ImportStatistics())
    return JsonExporter().export(filter_by_grade(students, minimum), target)


def _peak_mib(function: Callable[[Path, Path, float], int], source: Path, target: Path) -> float:
    tracemalloc.start()
    function(source, target, 60.0)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1024 / 1024


def _seconds(function: Callable[[Path, Path, float], int], source: Path, target: Path) -> float:
    start = perf_counter()
    function(source, target, 60.0)
    return perf_counter() - start


def experiment_streaming_vs_eager() -> None:
    print("\n== Experiment 2. Eager vs streaming import ==")
    print(f"{'records':>9}{'eager s':>10}{'stream s':>10}{'eager MiB':>11}{'stream MiB':>12}")

    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        for size in (10_000, 100_000, 500_000):
            source = directory / f"students_{size}.csv"
            write_dataset(source, valid=size)
            target = directory / "out.json"
            eager_t = _seconds(eager_import, source, target)
            stream_t = _seconds(streaming_import, source, target)
            eager_m = _peak_mib(eager_import, source, target)
            stream_m = _peak_mib(streaming_import, source, target)
            print(f"{size:>9}{eager_t:>10.3f}{stream_t:>10.3f}{eager_m:>11.1f}{stream_m:>12.2f}")


# ---------------------------------------------------------------- experiment 3
def experiment_chaining() -> None:
    print("\n== Experiment 3. Exception chaining ==")
    row = {"student_id": "1", "first_name": "Anna", "last_name": "Koval",
           "group": "FeP-21", "average_grade": "wrong"}

    try:
        parse_student(row, line_number=2)
    except RecordValidationError as error:
        print("".join(traceback.format_exception(error)).rstrip())
        print("\n__cause__:", repr(error.__cause__))
        print("line_number:", error.line_number, "| field:", error.field)


# ---------------------------------------------------------------- experiment 4
def _failing_students() -> Iterator[Student]:
    yield Student(1, "Anna", "Koval", "FeP-21", 90.0)
    yield Student(2, "Oleh", "Melnyk", "FeP-21", 80.0)
    raise RuntimeError("simulated failure during export")


def experiment_atomic_output() -> None:
    print("\n== Experiment 4. Atomic output ==")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "students.json"
        good = [Student(1, "Valid", "Previous", "FeP-21", 99.0)]
        JsonExporter().export(good, target)
        before = target.read_text(encoding="utf-8")

        try:
            JsonExporter().export(_failing_students(), target)
        except RuntimeError as error:
            print("exception during export:", error)

        print("previous output unchanged:", target.read_text(encoding="utf-8") == before)
        print(".tmp file removed:", not target.with_name(target.name + ".tmp").exists())
        print("files in directory:", sorted(p.name for p in Path(tmp).iterdir()))


# ---------------------------------------------------------------- experiment 5
def experiment_configuration_errors() -> None:
    print("\n== Experiment 5. Configuration errors ==")
    good = ("input:\n  path: {src}\noutput:\n  path: {out}\nprocessing:\n"
            "  minimum_grade: {minimum}\n  skip_invalid: true\nlogging:\n  level: INFO\n  path: {log}\n")

    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        source = directory / "in.csv"
        write_dataset(source, valid=3)
        args = {"src": source.as_posix(), "out": (directory / "out" / "r.json").as_posix(),
                "minimum": 60, "log": (directory / "a.log").as_posix()}

        cases: list[tuple[str, Path]] = []

        cases.append(("missing config.yaml", directory / "nope.yaml"))

        broken = directory / "broken.yaml"
        broken.write_text("input: [unclosed\n  path: x", encoding="utf-8")
        cases.append(("invalid YAML", broken))

        no_input = directory / "no_input.yaml"
        no_input.write_text("output:\n  path: x.json\n", encoding="utf-8")
        cases.append(("no key 'input'", no_input))

        bad_grade = directory / "bad_grade.yaml"
        bad_grade.write_text(good.format(**{**args, "minimum": 150}), encoding="utf-8")
        cases.append(("minimum_grade = 150", bad_grade))

        missing_input = directory / "missing_input.yaml"
        missing_input.write_text(good.format(**{**args, "src": (directory / "none.csv").as_posix()}),
                                 encoding="utf-8")
        cases.append(("input file is absent", missing_input))

        ok = directory / "ok.yaml"
        ok.write_text(good.format(**args), encoding="utf-8")
        cases.append(("output directory does not exist", ok))

        for title, path in cases:
            try:
                config = load_config(path, {})
                run_import(config)
                created = (directory / "out" / "r.json").exists()
                print(f"{title:34} -> OK, directory created automatically, output exists: {created}")
            except ApplicationError as error:
                cause = f" (cause: {type(error.__cause__).__name__})" if error.__cause__ else ""
                print(f"{title:34} -> {type(error).__name__}: {error}{cause}")


def main() -> None:
    logging.disable(logging.CRITICAL)  # keep the experiment output readable
    experiment_strict_vs_tolerant()
    experiment_streaming_vs_eager()
    experiment_chaining()
    experiment_atomic_output()
    experiment_configuration_errors()


if __name__ == "__main__":
    main()
