"""
Validation report and result models.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import json


@dataclass
class ValidationResult:
    """Result of a single rule validation."""

    column: str
    check_name: str
    passed: bool
    total_rows: int
    passed_rows: int
    failed_rows: int
    pass_rate: float
    threshold: float
    sample_failures: List[Any] = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {self.column}.{self.check_name} | "
            f"pass_rate={self.pass_rate:.2%} (threshold={self.threshold:.0%}) | "
            f"{self.passed_rows}/{self.total_rows} rows passed"
        )


@dataclass
class ValidationReport:
    """Aggregated report of all validation results."""

    results: List[ValidationResult]
    engine: str = "pandas"

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def is_valid(self) -> bool:
        return self.failed_count == 0

    def failed_results(self) -> List[ValidationResult]:
        """Return only failed results."""
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        """Return a human-readable summary."""
        lines = [
            f"DataGuard Validation Report",
            f"Engine: {self.engine}",
            f"Total Rules: {self.total_count} | Passed: {self.passed_count} | Failed: {self.failed_count}",
            f"Overall Status: {'VALID' if self.is_valid else 'INVALID'}",
            "-" * 60,
        ]
        for r in self.results:
            lines.append(str(r))
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "engine": self.engine,
            "total": self.total_count,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "is_valid": self.is_valid,
            "results": [
                {
                    "column": r.column,
                    "check": r.check_name,
                    "passed": r.passed,
                    "pass_rate": r.pass_rate,
                    "threshold": r.threshold,
                    "total_rows": r.total_rows,
                    "passed_rows": r.passed_rows,
                    "failed_rows": r.failed_rows,
                    "sample_failures": r.sample_failures[:5],
                }
                for r in self.results
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert report to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)
