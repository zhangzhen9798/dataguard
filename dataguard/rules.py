"""
Rule definitions for DataGuard.
"""

from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Rule:
    """A single validation rule bound to a column."""

    column: str
    check: Callable
    check_name: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    threshold: float = 1.0  # Pass rate threshold (0.0 - 1.0), 1.0 = 100% must pass

    def __post_init__(self):
        if self.check_name:
            return
        name = getattr(self.check, "__name__", "custom")
        if name == "_check":
            # For closure-based checks from checks.py, try to get the wrapped name
            name = getattr(self.check, "__qualname__", "custom")
            if "." in name:
                name = "custom"
        self.check_name = name

        # Validate threshold range
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError(
                f"threshold must be between 0.0 and 1.0, got {self.threshold}"
            )


class RuleSet:
    """
    A collection of validation rules.

    Example:
        >>> rules = RuleSet()
        >>> rules.add("email", not_null())
        >>> rules.add("age", in_range(0, 120))
        >>> rules.add("status", in_set(["active", "inactive"]))
    """

    def __init__(self):
        self._rules: List[Rule] = []

    def add(
        self,
        column: str,
        check: Callable,
        check_name: str = "",
        params: Optional[Dict[str, Any]] = None,
        threshold: float = 1.0,
    ) -> "RuleSet":
        """
        Add a validation rule for a column.

        Args:
            column: Column name to validate.
            check: Check function (from dataguard.checks).
            check_name: Human-readable name for the check.
            params: Parameters passed to the check.
            threshold: Minimum pass rate (0.0 - 1.0).

        Returns:
            Self for method chaining.
        """
        rule = Rule(
            column=column,
            check=check,
            check_name=check_name,
            params=params or {},
            threshold=threshold,
        )
        self._rules.append(rule)
        return self

    @property
    def rules(self) -> List[Rule]:
        """Return all rules."""
        return self._rules

    def columns(self) -> List[str]:
        """Return unique column names that have rules."""
        return list(dict.fromkeys(r.column for r in self._rules))

    def get_rules_for_column(self, column: str) -> List[Rule]:
        """Return all rules for a specific column."""
        return [r for r in self._rules if r.column == column]

    def __len__(self) -> int:
        return len(self._rules)

    def __repr__(self) -> str:
        return f"RuleSet({len(self._rules)} rules on {len(self.columns())} columns)"
