"""Unit tests of reliable_importer."""

import json
import logging
import tempfile
import unittest
from pathlib import Path

from reliable_importer.config import build_config, load_config
from reliable_importer.exceptions import (
    ApplicationError,
    ConfigurationError,
    DataError,
    DataExportError,
    DataImportError,
    RecordValidationError,
)
from reliable_importer.exporters import ErrorReport, JsonExporter, JsonLinesExporter, get_exporter
from reliable_importer.main import main
from reliable_importer.models import Student
from reliable_importer.readers import get_importer
from reliable_importer.services import ImportStatistics, filter_by_grade, import_students, run_import
from reliable_importer.utils import atomic_writer, logged_operation
from reliable_importer.validators import parse_student

HEADER = "student_id,first_name,last_name,group,average_grade\n"
GOOD = {"student_id": "1", "first_name": "Anna", "last_name": "Koval",
        "group": "FeP-21", "average_grade": "91.5"}


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # runs before the directory is removed: Windows cannot delete an open log file
        self.addCleanup(self._close_log_handlers)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    @staticmethod
    def _close_log_handlers() -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()

    def csv(self, body: str, name: str = "in.csv") -> Path:
        path = self.dir / name
        path.write_text(HEADER + body, encoding="utf-8")
        return path


class ExceptionTest(unittest.TestCase):
    def test_hierarchy(self) -> None:
        self.assertTrue(issubclass(RecordValidationError, DataError))
        self.assertTrue(issubclass(DataError, ApplicationError))
        self.assertTrue(issubclass(ConfigurationError, ApplicationError))

    def test_record_error_carries_context(self) -> None:
        error = RecordValidationError("bad", line_number=7, field="group")
        self.assertEqual((error.line_number, error.field, str(error)), (7, "group", "bad"))


class ValidatorTest(unittest.TestCase):
    def test_valid_record(self) -> None:
        student = parse_student(GOOD, line_number=2)
        self.assertEqual(student, Student(1, "Anna", "Koval", "FeP-21", 91.5))

    def test_decimal_comma(self) -> None:
        row = {**GOOD, "average_grade": "88,5"}
        self.assertEqual(parse_student(row, line_number=2).average_grade, 88.5)

    def test_invalid_fields(self) -> None:
        cases = {
            "student_id": "abc", "first_name": "", "last_name": "R2D2",
            "group": "", "average_grade": "105",
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaises(RecordValidationError) as ctx:
                parse_student({**GOOD, field: value}, line_number=5)
            self.assertEqual(ctx.exception.field, field)
            self.assertEqual(ctx.exception.line_number, 5)

    def test_non_finite_and_negative(self) -> None:
        for value in ("nan", "inf", "-1"):
            with self.subTest(value=value), self.assertRaises(RecordValidationError):
                parse_student({**GOOD, "average_grade": value}, line_number=2)

    def test_exception_chaining_keeps_cause(self) -> None:
        with self.assertRaises(RecordValidationError) as ctx:
            parse_student({**GOOD, "average_grade": "wrong"}, line_number=2)
        self.assertIsInstance(ctx.exception.__cause__, ValueError)

    def test_missing_key_is_validation_error(self) -> None:
        with self.assertRaises(RecordValidationError):
            parse_student({"student_id": "1"}, line_number=2)


class ReaderTest(TempDirCase):
    def test_csv_streaming_and_line_numbers(self) -> None:
        path = self.csv("1,A,B,G,50\n2,C,D,G,60\n")
        rows = list(get_importer(path).read(path))
        self.assertEqual([n for n, _ in rows], [2, 3])

    def test_missing_columns_fail_fast(self) -> None:
        path = self.dir / "bad.csv"
        path.write_text("student_id,name\n1,x\n", encoding="utf-8")
        with self.assertRaises(DataImportError):
            list(get_importer(path).read(path))

    def test_missing_file(self) -> None:
        path = self.dir / "none.csv"
        with self.assertRaises(DataImportError) as ctx:
            list(get_importer(path).read(path))
        self.assertIsInstance(ctx.exception.__cause__, FileNotFoundError)

    def test_bad_encoding(self) -> None:
        path = self.dir / "latin.csv"
        path.write_bytes(HEADER.encode() + "1,\xe9,B,G,50\n".encode("latin-1"))
        with self.assertRaises(DataImportError):
            list(get_importer(path).read(path))

    def test_jsonl(self) -> None:
        path = self.dir / "in.jsonl"
        path.write_text(json.dumps(GOOD) + "\n\n" + json.dumps({**GOOD, "student_id": 2}) + "\n",
                        encoding="utf-8")
        rows = list(get_importer(path).read(path))
        self.assertEqual([r["student_id"] for _, r in rows], ["1", "2"])

    def test_invalid_jsonl_and_unknown_extension(self) -> None:
        path = self.dir / "bad.jsonl"
        path.write_text("{oops\n", encoding="utf-8")
        with self.assertRaises(DataImportError) as ctx:
            list(get_importer(path).read(path))
        self.assertIsInstance(ctx.exception.__cause__, json.JSONDecodeError)
        with self.assertRaises(DataImportError):
            get_importer(self.dir / "data.xml")


class ServiceTest(TempDirCase):
    BODY = "1,A,Bb,G1,90\n2,,Cc,G1,80\n3,D,Ee,G2,70\nx,F,Gg,G2,60\n4,H,Ii,G2,50\n"

    def test_tolerant_mode_counts_and_skips(self) -> None:
        stats = ImportStatistics()
        collected: list[RecordValidationError] = []
        students = list(import_students(self.csv(self.BODY), skip_invalid=True,
                                        statistics=stats, on_error=collected.append))
        self.assertEqual((stats.total, stats.valid, stats.invalid), (5, 3, 2))
        self.assertEqual([s.student_id for s in students], [1, 3, 4])
        self.assertEqual([e.line_number for e in collected], [3, 5])
        self.assertEqual(stats.invalid_by_field, {"first_name": 1, "student_id": 1})

    def test_strict_mode_stops_at_first_error(self) -> None:
        stats = ImportStatistics()
        with self.assertRaises(RecordValidationError):
            list(import_students(self.csv(self.BODY), skip_invalid=False, statistics=stats))
        self.assertEqual((stats.total, stats.valid, stats.invalid), (2, 1, 1))

    def test_filter_by_grade(self) -> None:
        students = [Student(1, "A", "B", "G", 59.9), Student(2, "C", "D", "G", 60.0)]
        self.assertEqual([s.student_id for s in filter_by_grade(students, 60)], [2])


class ExportTest(TempDirCase):
    STUDENTS = [Student(1, "Олена", "Коваль", "FeP-21", 91.5), Student(2, "Oleh", "Melnyk", "FeP-21", 84.0)]

    def test_json_export_is_valid_and_keeps_unicode(self) -> None:
        path = self.dir / "out" / "r.json"
        self.assertEqual(JsonExporter().export(self.STUDENTS, path), 2)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["first_name"], "Олена")
        self.assertEqual(len(data), 2)

    def test_empty_export_is_valid_json(self) -> None:
        path = self.dir / "empty.json"
        JsonExporter().export([], path)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [])

    def test_jsonl_export(self) -> None:
        path = self.dir / "r.jsonl"
        JsonLinesExporter().export(self.STUDENTS, path)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["student_id"] for x in lines], [1, 2])

    def test_exporter_selected_by_extension(self) -> None:
        self.assertIsInstance(get_exporter(Path("a.json")), JsonExporter)
        self.assertIsInstance(get_exporter(Path("a.jsonl")), JsonLinesExporter)
        with self.assertRaises(DataExportError):
            get_exporter(Path("a.xml"))

    def test_atomic_failure_keeps_previous_output(self) -> None:
        path = self.dir / "r.json"
        JsonExporter().export(self.STUDENTS, path)
        before = path.read_text(encoding="utf-8")

        def broken():  # type: ignore[no-untyped-def]
            yield self.STUDENTS[0]
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            JsonExporter().export(broken(), path)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertFalse(path.with_name("r.json.tmp").exists())

    def test_backup_of_existing_output(self) -> None:
        path = self.dir / "r.json"
        JsonExporter().export(self.STUDENTS[:1], path)
        JsonExporter(backup=True).export(self.STUDENTS, path)
        backup = json.loads(path.with_name("r.json.bak").read_text(encoding="utf-8"))
        self.assertEqual(len(backup), 1)

    def test_write_error_becomes_export_error(self) -> None:
        blocker = self.dir / "file"
        blocker.write_text("x", encoding="utf-8")
        with self.assertRaises(DataExportError) as ctx:
            JsonExporter().export(self.STUDENTS, blocker / "r.json")
        self.assertIsInstance(ctx.exception.__cause__, OSError)

    def test_error_report(self) -> None:
        path = self.dir / "errors.csv"
        with ErrorReport(path) as report:
            report.add(RecordValidationError("bad grade", line_number=4, field="average_grade"))
        self.assertIn("4,average_grade,bad grade", path.read_text(encoding="utf-8"))
        with ErrorReport(None) as report:  # disabled report is a no-op
            report.add(RecordValidationError("ignored"))

    def test_error_report_is_removed_on_failure(self) -> None:
        path = self.dir / "errors.csv"
        with self.assertRaises(RuntimeError):
            with ErrorReport(path):
                raise RuntimeError("stop")
        self.assertFalse(path.exists())
        self.assertFalse(path.with_name("errors.csv.tmp").exists())


class ContextManagerTest(TempDirCase):
    def test_logged_operation_logs_success_and_failure(self) -> None:
        logging.disable(logging.NOTSET)
        with self.assertLogs("reliable_importer.utils", level="INFO") as ok:
            with logged_operation("Job"):
                pass
        self.assertTrue(any("finished" in m for m in ok.output))
        with self.assertLogs("reliable_importer.utils", level="INFO") as failed:
            with self.assertRaises(ValueError), logged_operation("Job"):
                raise ValueError("x")
        self.assertTrue(any("failed" in m for m in failed.output))

    def test_atomic_writer_commits_only_on_success(self) -> None:
        path = self.dir / "a.txt"
        with atomic_writer(path) as file:
            file.write("ok")
        self.assertEqual(path.read_text(encoding="utf-8"), "ok")
        with self.assertRaises(ValueError), atomic_writer(path) as file:
            file.write("broken")
            raise ValueError
        self.assertEqual(path.read_text(encoding="utf-8"), "ok")


class ConfigTest(TempDirCase):
    def raw(self, source: Path, **processing: object) -> dict:  # type: ignore[type-arg]
        return {
            "input": {"path": str(source)},
            "output": {"path": str(self.dir / "o.json")},
            "processing": {"minimum_grade": 60, "skip_invalid": True, **processing},
            "logging": {"level": "info", "path": str(self.dir / "l.log")},
        }

    def test_valid_configuration(self) -> None:
        config = build_config(self.raw(self.csv("")), {})
        self.assertEqual(config.logging.level, "INFO")
        self.assertIsNone(config.errors_path)

    def test_environment_override(self) -> None:
        env = {"IMPORTER_MINIMUM_GRADE": "75", "IMPORTER_SKIP_INVALID": "false"}
        config = build_config(self.raw(self.csv("")), env)
        self.assertEqual(config.processing.minimum_grade, 75.0)
        self.assertFalse(config.processing.skip_invalid)

    def test_invalid_structures(self) -> None:
        source = self.csv("")
        for broken in (None, [], {"input": {}}, self.raw(source, minimum_grade="x"),
                       self.raw(source, skip_invalid="maybe")):
            with self.subTest(broken=broken), self.assertRaises(ConfigurationError):
                build_config(broken, {})

    def test_load_errors(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            load_config(self.dir / "none.yaml", {})
        self.assertIsInstance(ctx.exception.__cause__, FileNotFoundError)
        bad = self.dir / "bad.yaml"
        bad.write_text("a: [unclosed", encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            load_config(bad, {})

    def test_semantic_validation(self) -> None:
        import yaml
        source = self.csv("")
        for raw in (self.raw(source, minimum_grade=150), self.raw(self.dir / "absent.csv")):
            path = self.dir / "c.yaml"
            path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.subTest(raw=raw), self.assertRaises(ConfigurationError):
                load_config(path, {})


class MainTest(TempDirCase):
    def write_config(self, body: str, skip: bool) -> Path:
        import yaml
        source = self.csv(body)
        config = self.dir / "config.yaml"
        config.write_text(yaml.safe_dump({
            "input": {"path": str(source)},
            "output": {"path": str(self.dir / "out.json"), "errors_path": str(self.dir / "err.csv")},
            "processing": {"minimum_grade": 60, "skip_invalid": skip},
            "logging": {"level": "INFO", "path": str(self.dir / "app.log")},
        }), encoding="utf-8")
        return config

    def test_tolerant_run(self) -> None:
        config = self.write_config("1,A,Bb,G,90\n2,,Cc,G,80\n3,D,Ee,G,40\n", True)
        main(["--config", str(config)])
        data = json.loads((self.dir / "out.json").read_text(encoding="utf-8"))
        self.assertEqual([s["student_id"] for s in data], [1])
        self.assertIn("first_name", (self.dir / "err.csv").read_text(encoding="utf-8"))
        self.assertTrue((self.dir / "app.log").exists())

    def test_strict_run_exits_with_code_1_and_no_output(self) -> None:
        config = self.write_config("1,A,Bb,G,90\n2,,Cc,G,80\n", False)
        with self.assertRaises(SystemExit) as ctx:
            main(["--config", str(config)])
        self.assertEqual(ctx.exception.code, 1)
        self.assertFalse((self.dir / "out.json").exists())
        self.assertFalse((self.dir / "err.csv").exists())

    def test_configuration_error_exits_with_code_1(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--config", str(self.dir / "missing.yaml")])
        self.assertEqual(ctx.exception.code, 1)

    def test_run_import_reports_statistics(self) -> None:
        config = load_config(self.write_config("1,A,Bb,G,90\n2,,Cc,G,80\n", True), {})
        report = run_import(config)
        self.assertEqual((report.statistics.total, report.exported), (2, 1))
        self.assertIn("exported=1", report.summary())


if __name__ == "__main__":
    unittest.main()