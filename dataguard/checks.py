"""
Built-in validation check functions for DataGuard.

Each check function takes a value and returns True if valid, False otherwise.
These are designed to be composable and reusable.
"""

import re
from typing import Any, Callable, Container, Optional, Pattern


def not_null():
    """Check that value is not None/NaN/pd.NA."""
    def _check(value: Any) -> bool:
        if value is None:
            return False
        try:
            import math
            if isinstance(value, float) and math.isnan(value):
                return False
        except (TypeError, ValueError):
            pass
        try:
            import pandas as pd
            if value is pd.NA:
                return False
        except (ImportError, AttributeError):
            pass
        return True
    _check.__name__ = "not_null"
    _check._sql_params = {}
    return _check


def unique():
    """Check that values in a column are unique (handled at engine level)."""
    def _check(value: Any) -> bool:
        return True
    _check.__name__ = "unique"
    _check._sql_params = {}
    return _check


def in_range(min_val: Optional[float] = None, max_val: Optional[float] = None):
    """Check that a numeric value falls within [min_val, max_val].

    At least one bound required.
    """
    if min_val is None and max_val is None:
        raise ValueError("in_range() requires at least one of min_val or max_val")
    if (min_val is not None and max_val is not None) and min_val > max_val:
        raise ValueError(f"min_val ({min_val}) cannot be greater than max_val ({max_val})")

    def _check(value: Any) -> bool:
        if value is None:
            return True
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
    _check._sql_params = {"min_val": min_val, "max_val": max_val}
    return _check


def regex_match(pattern: str):
    """Check that a string value matches the given regex pattern."""
    _dangerous_re = re.compile(r'\([^)]*[*+][^)]*\)[*+]')
    if _dangerous_re.search(pattern):
        raise ValueError(
            f"Regex pattern may cause catastrophic backtracking: '{pattern}'"
        )
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return bool(compiled.match(str(value)))
    _check.__name__ = f"regex_match('{pattern}')"
    _check._sql_params = {"pattern": pattern}
    return _check


def in_set(allowed_values: Container):
    """Check that a value is in the allowed set."""
    if not hasattr(allowed_values, '__contains__') and not hasattr(allowed_values, '__iter__'):
        raise TypeError(
            f"in_set() requires an iterable, got {type(allowed_values).__name__}"
        )
    allowed = set(allowed_values)

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return value in allowed
    _check.__name__ = f"in_set({allowed_values})"
    _check._sql_params = {"allowed_values": list(allowed_values)}
    return _check


def min_length(min_len: int):
    """Check that a string value has at least min_len characters."""
    if not isinstance(min_len, int) or min_len < 0:
        raise ValueError(f"min_length() requires a non-negative integer, got {min_len!r}")

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return len(str(value)) >= min_len
    _check.__name__ = f"min_length({min_len})"
    _check._sql_params = {"min_len": min_len}
    return _check


def max_length(max_len: int):
    """Check that a string value has at most max_len characters."""
    if not isinstance(max_len, int) or max_len < 0:
        raise ValueError(f"max_length() requires a non-negative integer, got {max_len!r}")

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return len(str(value)) <= max_len
    _check.__name__ = f"max_length({max_len})"
    _check._sql_params = {"max_len": max_len}
    return _check


def custom(func: Callable[[Any], bool], name: str = ""):
    """Wrap a custom validation function. Cannot be translated to SQL."""
    def _check(value: Any) -> bool:
        return func(value)
    _check.__name__ = name or getattr(func, "__name__", "custom")
    _check._sql_params = None  # custom checks cannot be translated to SQL
    return _check
