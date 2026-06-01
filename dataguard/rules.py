"""
Rule definitions for DataGuard.
"""

from typing import Any, Callable, Dict, List, Optional, Union
from dataclasses import dataclass, field

from dataguard.checks import (
    not_null,
    unique,
    in_range,
    regex_match,
    in_set,
    min_length,
    max_length,
    custom,
)

# Map check names to factory functions for from_dict()
_CHECK_REGISTRY: Dict[str, Callable] = {
    "not_null": not_null,
    "unique": unique,
    "in_range": in_range,
    "regex_match": regex_match,
    "in_set": in_set,
    "min_length": min_length,
    "max_length": max_length,
}


@dataclass
class Rule:
    """A single validation rule bound to a column."""

    column: str
    check: Callable
    check_name: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    threshold: float = 1.0  # Pass rate threshold (0.0 - 1.0), 1.0 = 100% must pass

    def __post_init__(self):
        # Validate threshold range first (must always run)
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError(
                f"threshold must be between 0.0 and 1.0, got {self.threshold}"
            )

        if self.check_name:
            return
        name = getattr(self.check, "__name__", "custom")
        if name == "_check":
            name = getattr(self.check, "__qualname__", "custom")
            if "." in name:
                name = "custom"
        self.check_name = name


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

    @classmethod
    def from_dict(cls, config: Dict[str, List[Dict[str, Any]]]) -> "RuleSet":
        """Create a RuleSet from a dictionary config.

        Args:
            config: Mapping of column names to lists of check definitions.
                Each check definition is a dict with a "check" key (name)
                and optional "params", "threshold" keys.

        Example:
            {
                "age": [
                    {"check": "not_null"},
                    {"check": "in_range", "params": {"min_val": 0, "max_val": 120}},
                ],
                "email": [
                    {"check": "regex_match", "params": {"pattern": r"^[\\w.-]+@[\\w.-]+\\.\\w+$"}},
                ],
            }

        Raises:
            ValueError: If a check name is not found in the registry,
                or if the config contains unknown keys (parameter injection prevention).
        """
        ruleset = cls()
        for column, checks in config.items():
            for check_def in checks:
                name = check_def["check"]
                if name not in _CHECK_REGISTRY:
                    raise ValueError(
                        f"Unknown check '{name}'. Available: {list(_CHECK_REGISTRY.keys())}"
                    )
                # Only allow known keys to prevent parameter injection
                allowed_keys = {"check", "params", "threshold"}
                unknown_keys = set(check_def.keys()) - allowed_keys
                if unknown_keys:
                    raise ValueError(
                        f"Unknown keys in check definition: {unknown_keys}. "
                        f"Allowed keys: {allowed_keys}"
                    )
                factory = _CHECK_REGISTRY[name]
                params = check_def.get("params", {})
                threshold = check_def.get("threshold", 1.0)
                try:
                    check_fn = factory(**params)
                except TypeError as e:
                    raise ValueError(
                        f"Invalid params for check '{name}': {e}"
                    ) from e
                ruleset.add(column, check_fn, threshold=threshold)
        return ruleset
