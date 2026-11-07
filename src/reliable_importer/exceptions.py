"""Hierarchy of application exceptions."""


class ApplicationError(Exception):
    """Base application exception."""


class ConfigurationError(ApplicationError):
    """Configuration is missing or invalid."""


class DataError(ApplicationError):
    """Base class of data-related errors."""


class DataImportError(DataError):
    """Input data cannot be read."""


class DataExportError(DataError):
    """Output cannot be written."""


class RecordValidationError(DataError):
    """One record does not satisfy a validation rule."""

    def __init__(
        self,
        message: str,
        *,
        line_number: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.line_number = line_number
        self.field = field
