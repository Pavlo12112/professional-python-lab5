"""Application entry point."""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from reliable_importer.config import load_config
from reliable_importer.exceptions import ApplicationError
from reliable_importer.logging_config import configure_logging
from reliable_importer.services import run_import

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Reliable student data importer")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        configure_logging(config.logging.level, config.logging.path)
        run_import(config)
    except ApplicationError as error:
        logger.error("Application error: %s", error)
        raise SystemExit(1) from error
    except Exception as error:
        logger.exception("Unexpected failure")
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
