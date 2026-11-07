"""Loading, environment override and validation of the YAML configuration."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from reliable_importer.exceptions import ConfigurationError
from reliable_importer.models import AppConfig, LoggingConfig, ProcessingConfig

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

ENV_MINIMUM_GRADE = "IMPORTER_MINIMUM_GRADE"
ENV_SKIP_INVALID = "IMPORTER_SKIP_INVALID"
ENV_LOG_LEVEL = "IMPORTER_LOG_LEVEL"


def _read_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file)
    except FileNotFoundError as error:
        raise ConfigurationError(f"Configuration file not found: {path}") from error
    except yaml.YAMLError as error:
        raise ConfigurationError(f"Invalid YAML in {path}") from error
    except OSError as error:
        raise ConfigurationError(f"Cannot read configuration file: {path}") from error


def _parse_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
        return value.lower() in ("true", "1")
    raise ConfigurationError(f"{name} must be true or false, got {value!r}")


def _parse_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigurationError(f"{name} must be a number, got {value!r}")
    try:
        return float(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number, got {value!r}") from error


def build_config(
    raw: Any, environ: Mapping[str, str] | None = None
) -> AppConfig:
    """Convert a raw YAML structure into AppConfig (environment variables win)."""
    env = os.environ if environ is None else environ

    if not isinstance(raw, dict):
        raise ConfigurationError("Configuration must be a mapping at the top level")

    try:
        input_path = Path(raw["input"]["path"])
        output_path = Path(raw["output"]["path"])
        errors_raw = raw["output"].get("errors_path")
        minimum = env.get(ENV_MINIMUM_GRADE, raw["processing"]["minimum_grade"])
        skip = env.get(ENV_SKIP_INVALID, raw["processing"]["skip_invalid"])
        level = env.get(ENV_LOG_LEVEL, raw["logging"]["level"])

        config = AppConfig(
            input_path=input_path,
            output_path=output_path,
            errors_path=Path(errors_raw) if errors_raw else None,
            processing=ProcessingConfig(
                minimum_grade=_parse_number(minimum, "processing.minimum_grade"),
                skip_invalid=_parse_bool(skip, "processing.skip_invalid"),
            ),
            logging=LoggingConfig(
                level=str(level).upper(),
                path=Path(raw["logging"]["path"]),
            ),
        )
    except KeyError as error:
        raise ConfigurationError(f"Missing configuration key: {error}") from error
    except (TypeError, AttributeError) as error:
        raise ConfigurationError("Configuration structure is invalid") from error

    return config


def validate_config(config: AppConfig) -> None:
    """Fail-fast checks, executed before any processing starts."""
    if not 0 <= config.processing.minimum_grade <= 100:
        raise ConfigurationError("minimum_grade must be between 0 and 100")

    if config.logging.level not in LOG_LEVELS:
        raise ConfigurationError(f"Unknown logging level: {config.logging.level}")

    if not config.input_path.is_file():
        raise ConfigurationError(f"Input file not found: {config.input_path}")

    if config.output_path.is_dir():
        raise ConfigurationError(f"Output path is a directory: {config.output_path}")


def load_config(
    path: Path, environ: Mapping[str, str] | None = None
) -> AppConfig:
    config = build_config(_read_yaml(path), environ)
    validate_config(config)
    return config
