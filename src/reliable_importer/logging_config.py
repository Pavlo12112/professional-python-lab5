"""Logging setup with file rotation."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(
    level: str,
    path: Path,
    *,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            RotatingFileHandler(
                path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
        force=True,
    )
