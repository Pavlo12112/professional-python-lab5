# Reliable Importer

Laboratory work No. 5 for the course "Professional Python":
error handling, files and serialization (variant 1, import and export
of student data).

## Description

Reliable module for import, validation, export and configuration of data:

    config.yaml -> load_config -> validate_config -> streaming CSV reader
                -> parse and validate -> filter -> atomic JSON export

- strict mode (`skip_invalid: false`): the first invalid record aborts the run
  and no output is produced; tolerant mode (`skip_invalid: true`): invalid
  records are logged, counted, written to an error report and skipped;
- custom exception hierarchy with exception chaining;
- own context managers (`logged_operation`, `atomic_writer`, `ErrorReport`);
- logging to a rotating file and to the console;
- importer/exporter `Protocol`s, format chosen by file extension
  (CSV and JSON Lines input, JSON and JSON Lines output);
- environment variable override of the configuration.

## Requirements

Python 3.11+, PyYAML

## Installation

    python -m venv .venv

Activate the virtual environment
(Windows: `.venv\Scripts\activate`, Linux/macOS: `source .venv/bin/activate`).

    python -m pip install -e .

## Run

    python -m reliable_importer.main
    python -m reliable_importer.main --config config.yaml

Exit codes: `0` success, `1` expected application error, `2` unexpected failure.

Environment overrides: `IMPORTER_MINIMUM_GRADE`, `IMPORTER_SKIP_INVALID`,
`IMPORTER_LOG_LEVEL`.

Experiments (strict/tolerant, eager/streaming, chaining, atomic output,
configuration errors):

    python -m reliable_importer.experiments

Tests:

    python -m unittest discover -s tests -v

## Input format

    student_id,first_name,last_name,group,average_grade

## Project structure

- `config.yaml` - configuration.
- `data/students.csv` - example input with valid and invalid records.
- `src/reliable_importer/config.py` - loading, override and validation of configuration.
- `src/reliable_importer/exceptions.py` - exception hierarchy.
- `src/reliable_importer/models.py` - `Student` and configuration dataclasses.
- `src/reliable_importer/readers.py` - streaming importers.
- `src/reliable_importer/validators.py` - validation of one record.
- `src/reliable_importer/exporters.py` - exporters and error report.
- `src/reliable_importer/utils.py` - context managers.
- `src/reliable_importer/logging_config.py` - logging setup.
- `src/reliable_importer/services.py` - import pipeline.
- `src/reliable_importer/experiments.py` - experiments of the laboratory work.

## Author

Student: Tsiastun Pavlo
Group: FeP-33s
