"""Own context managers."""

import logging
import shutil
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from time import perf_counter
from typing import TextIO

from reliable_importer.exceptions import DataExportError

logger = logging.getLogger(__name__)


@contextmanager
def logged_operation(operation: str) -> Iterator[None]:
    """Log start, duration and failure of an operation."""
    logger.info("%s started", operation)
    start = perf_counter()

    try:
        yield
    except Exception:
        logger.exception("%s failed", operation)
        raise
    else:
        logger.info("%s finished in %.6f s", operation, perf_counter() - start)


def _discard(path: Path) -> None:
    """Remove a temporary file; a failed cleanup must not hide the real error."""
    with suppress(OSError):
        path.unlink(missing_ok=True)


@contextmanager
def atomic_writer(path: Path, *, backup: bool = False) -> Iterator[TextIO]:
    """Transaction-like file write.

    Data is written to ``<name>.tmp``. Only if the block finishes without
    an error, the temporary file replaces the real one (optionally the old
    file is saved as ``<name>.bak``). Otherwise the temporary file is removed
    and the previous output stays untouched.
    """
    temporary = path.with_name(path.name + ".tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with temporary.open("w", encoding="utf-8", newline="") as file:
            yield file

        if backup and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))

        temporary.replace(path)
    except OSError as error:
        _discard(temporary)
        raise DataExportError(f"Cannot write {path}") from error
    except BaseException:
        _discard(temporary)
        raise
