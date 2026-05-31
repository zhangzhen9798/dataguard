"""
Built-in validation check functions for DataGuard.

Each check function takes a value and returns True if valid, False otherwise.
These are designed to be composable and reusable.
"""

import re
from typing import Any, Callable, Container, Optional, Pattern


def not_null():
    """Check that value is not None/NaN."""
    def _check(value: Any) -> bool:
        if value is None:
            return False
        # Handle pandas NaN
        try:
            import math
            if isinstance(value, float) and math.isnan(value):
                return False
        except (TypeError, ValueError):
            pass
        return True
    _check.__name__ = "not_null"
    return _check


def unique():
    """
    Check that values in a column are unique.

    Note: This is a column-level check. The engine handles deduplication logic.
    This check function marks values for uniqueness validation.
    """
    def _check(value: Any) -> bool:
        return True  # Actual uniqueness is checked at engine level
    _check.__name__ = "unique"
    return _check


def in_range(min_val: Optional[float] = None, max_val: Optional[float] = None):
    """
    Check that a numeric value falls within [min_val, max_val].

    Args:
        min_val: Minimum allowed value (inclusive). None = no lower bound.
        max_val: Maximum allowed value (inclusive). None = no upper bound.
    """
    def _check(value: Any) -> bool:
        if value is None:
            return True  # Use not_null() for null checks
        try:
            num = float(value)
        except (TypeError, ValueError):
            return False
        if min_val is not None and num < min_val:
            return False
        if max_val is not None and num > max_val:
            return False
        return True
    _check.__name__ = f"in_range({min_val}, {max_val})"
    return _check


def regex_match(pattern: str):
    """
    Check that a string value matches the given regex pattern.

    Args:
        pattern: Regular expression pattern string.
    """
    compiled = re.compile(pattern)

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return bool(compiled.match(str(value)))
    _check.__name__ = f"regex_match('{pattern}')"
    return _check


def in_set(allowed_values: Container):
    """
    Check that a value is in the allowed set.

    Args:
        allowed_values: A set, list, or tuple of allowed values.
    """
    allowed = set(allowed_values)

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return value in allowed
    _check.__name__ = f"in_set({allowed_values})"
    return _check


def min_length(min_len: int):
    """Check that a string value has at least min_len characters."""
    def _check(value: Any) -> bool:
        if value is None:
            return True
        return len(str(value)) >= min_len
    _check.__name__ = f"min_length({min_len})"
    return _check


def max_length(max_len: int):
    """Check that a string value has at most max_len characters."""
    def _check(value: Any) -> bool:
        if value is None:
            return True
        return len(str(value)) <= max_len
    _check.__name__ = f"max_length({max_len})"
    return _check


def custom(func: Callable[[Any], bool], name: str = ""):
    """
    Wrap a custom validation function.

    Args:
        func: A callable that takes a value and returns bool.
        name: Optional name for the check.
    """
    def _check(value: Any) -> bool:
        return func(value)
    _check.__name__ = name or getattr(func, "__name__", "custom")
    return _check
