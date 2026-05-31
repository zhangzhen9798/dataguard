"""
Built-in validation check functions for DataGuard.

Each check function takes a value and returns True if valid, False otherwise.
These are designed to be composable and reusable.
"""

import re
from typing import Any, Callable, Container, Optional, Pattern


def not_null():
    """Check that value is not None/NaN/pd.NA.

    Returns:
        A check function returning True for non-null values.
    """
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
        # Handle pd.NA (Pandas 1.0+)
        try:
            import pandas as pd
            if value is pd.NA:
                return False
        except (ImportError, AttributeError):
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

    Raises:
        ValueError: If both min_val and max_val are None, or if min_val > max_val.
    """
    if min_val is None and max_val is None:
        raise ValueError("in_range() requires at least one of min_val or max_val")
    if (min_val is not None and max_val is not None) and min_val > max_val:
        raise ValueError(f"in_range(): min_val ({min_val}) cannot be greater than max_val ({max_val})")

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

    Raises:
        re.error: If the provided pattern is not a valid regular expression.
    """
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e

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
    """
    Check that a string value has at least min_len characters.

    Args:
        min_len: Minimum number of characters (must be >= 0).

    Raises:
        ValueError: If min_len is negative.
    """
    if not isinstance(min_len, int) or min_len < 0:
        raise ValueError(f"min_length() requires a non-negative integer, got {min_len!r}")

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return len(str(value)) >= min_len
    _check.__name__ = f"min_length({min_len})"
    return _check


def max_length(max_len: int):
    """
    Check that a string value has at most max_len characters.

    Args:
        max_len: Maximum number of characters (must be >= 0).

    Raises:
        ValueError: If max_len is negative.
    """
    if not isinstance(max_len, int) or max_len < 0:
        raise ValueError(f"max_length() requires a non-negative integer, got {max_len!r}")

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
