"""
Custom exceptions for DataGuard.
"""

from __future__ import annotations

from dataguard.report import ValidationReport


class ValidationError(Exception):
    """Raised when validation fails and raise_on_error=True."""

    def __init__(self, report: ValidationReport):
        self.report = report
        super().__init__(
            f"Validation failed: {report.failed_count} of {report.total_count} "
            f"rules failed. Use .report to see details."
        )
