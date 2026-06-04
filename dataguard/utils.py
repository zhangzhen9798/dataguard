"""
Shared utilities for DataGuard engines.

Provides common helper functions and type definitions
used across pandas, spark, and SQL backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    pass


class _HasRules(Protocol):
    """Protocol for objects with a rules list (RuleSet-compatible)."""

    @property
    def rules(self) -> list[Any]:  # list of objects with .column and .check_name attrs
        """Return all rules."""
        ...

    def add(
        self,
        column: str,
        check: CheckSpec,
        check_name: str = "",
        params: dict[str, Any] | None = None,
        threshold: float = 1.0,
    ) -> "_HasRules":
        """Add a rule to the ruleset."""
        ...


# ─── Engine Types ───────────────────────────────────────────────────


class EngineType(str, Enum):
    """Supported validation engine types."""

    PANDAS = "pandas"
    SPARK = "spark"
    SQL = "sql"


# ─── Check Level ────────────────────────────────────────────────────


class CheckLevel(str, Enum):
    """Whether a check operates at row level or column level."""

    ROW = "row"
    COLUMN = "column"


# ─── CheckSpec ─────────────────────────────────────────────────────


@dataclass
class CheckSpec:
    """A callable validation check with structured metadata.

    Replaces the previous closure-attribute monkey-patching
    (_sql_params, _is_column_level) with proper typed fields.

    Examples:
        >>> spec = CheckSpec(lambda x: x > 0, name="positive", sql_params={}, level=CheckLevel.ROW)
        >>> spec(5)
        True
        >>> spec.__name__
        'positive'
    """

    fn: Callable[[Any], bool]
    name: str
    sql_params: dict[str, Any] | None = None
    level: CheckLevel = CheckLevel.ROW

    def __post_init__(self) -> None:
        """Ensure __name__ mirrors .name for backward compatibility."""
        object.__setattr__(self, "__name__", self.name)

    def __call__(self, value: Any) -> bool:
        return self.fn(value)

    @property
    def is_column_level(self) -> bool:
        """Backward-compatible alias."""
        return self.level == CheckLevel.COLUMN


# ─── Value Masking ─────────────────────────────────────────────────


def mask_value(value: Any) -> str:
    """Mask a sensitive value for PII protection.

    Short strings (length <= 2) are fully masked as '***'.
    Longer strings show only first and last characters.
    """
    s = str(value)
    if len(s) <= 2:
        return "***"
    return s[0] + "***" + s[-1]


# ─── Unique Check Detection ────────────────────────────────────────


def collect_unique_checks(rules: _HasRules) -> dict[str, bool]:
    """Identify columns that have uniqueness checks.

    Used by pandas and spark engines to branch on uniqueness
    validation logic.
    """
    return {rule.column: True for rule in rules.rules if rule.check_name == "unique"}


# ─── SQL Identifier Validation ─────────────────────────────────────


def validate_identifier(name: str) -> None:
    """Validate a SQL identifier to prevent injection.

    Raises ValueError if the name contains suspicious characters.
    Only allows alphanumeric, underscores, dots (schema.table), and hyphens.
    Also rejects common SQL keywords used in injection attacks.
    """
    cleaned = name.replace(".", "").replace("_", "").replace("-", "")
    if not cleaned.isalnum():
        raise ValueError(f"Invalid SQL identifier: {name!r}")

    # Block common SQL keywords used in injection
    upper = name.strip().upper()
    dangerous_keywords = {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "EXEC",
        "EXECUTE",
        "UNION",
        "DECLARE",
        "GRANT",
        "REVOKE",
        "--",
        "/*",
        "*/",
    }
    for kw in dangerous_keywords:
        if kw in upper:
            raise ValueError(f"SQL identifier contains disallowed keyword: {name!r}")


# ─── Check Name Helpers ────────────────────────────────────────────


def base_check_name(check_name: str) -> str:
    """Extract the base check name without parameters.

    'in_range(0, 120)' -> 'in_range'
    'not_null' -> 'not_null'
    """
    return check_name.split("(")[0].strip()
