"""
Built-in validation check functions for DataGuard.

Each check function takes a value and returns True if valid, False otherwise.
These are designed to be composable and reusable.
"""

import math
import re
from typing import Any, Callable, Container, Optional, Pattern, Set


# ─── ReDoS Protection ──────────────────────────────────────────────

# Comprehensive dangerous regex patterns that can cause catastrophic backtracking:
# 1. Nested quantifiers: (a+)+
# 2. Overlapping alternations with quantifiers: (a|a)+
# 3. Quantified optional groups: (a?){n} with large n
# 4. Adjacent overlapping groups: (a+a+)+
_DANGEROUS_REGEX_PATTERNS = [
    # Nested quantifiers: (x+)+, (x*)+, (x+)*, (x*)*
    re.compile(r'\([^)]*[*+][^)]*\)[*+]'),
    # Overlapping alternations: (a|a)+, (a|b*)+
    re.compile(r'\([^)]*\|[^)]*\)[*+]'),
    # Quantified groups with inner quantifier + outer quantifier
    re.compile(r'\([^)]*\{[^}]*\}[^)]*\)[*+]'),
    # Adjacent quantified overlapping: a+a+
    re.compile(r'(\w+)[*+]\1[*+]'),
]

# Maximum allowed repetition count in regex to prevent DoS
_MAX_REGEX_REPETITION = 256


def _validate_regex_pattern(pattern: str) -> None:
    """Validate a regex pattern for potential ReDoS attacks.

    Raises ValueError if the pattern appears dangerous.
    """
    for dangerous_re in _DANGEROUS_REGEX_PATTERNS:
        if dangerous_re.search(pattern):
            raise ValueError(
                f"Regex pattern may cause catastrophic backtracking: '{pattern}'. "
                f"Patterns with nested or overlapping quantifiers are not allowed."
            )

    # Check for excessive repetition counts {n,m} or {n,}
    rep_match = re.findall(r'\{(\d+),?\d*\}', pattern)
    for rep in rep_match:
        if int(rep) > _MAX_REGEX_REPETITION:
            raise ValueError(
                f"Regex pattern contains excessive repetition {{{rep},...}}: '{pattern}'. "
                f"Maximum allowed repetition count is {_MAX_REGEX_REPETITION}."
            )

    # Try to compile to catch invalid patterns
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e


def not_null():
    """Check that value is not None/NaN/pd.NA.

    Note: This is a row-level check. For column-level null-rate
    enforcement, use threshold on the rule.
    """
    # Pre-check pandas availability once at function creation time
    _has_pandas = False
    _pd_NA = None
    try:
        import pandas as pd
        _has_pandas = True
        _pd_NA = pd.NA
    except ImportError:
        pass

    def _check(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, float) and math.isnan(value):
            return False
        if _has_pandas and value is _pd_NA:
            return False
        return True
    _check.__name__ = "not_null"
    _check._sql_params = {}
    return _check


def unique():
    """Check that values in a column are unique.

    This is a column-level constraint, not a row-level check.
    The check function always returns True at row level — uniqueness
    is enforced at the engine level by counting duplicates.

    For row-level uniqueness validation, the engine handles this
    separately (see pandas_engine._validate_rule and sql_engine).
    """
    def _check(value: Any) -> bool:
        # Uniqueness is a set-level property, not testable per row.
        # Engines handle this specially by checking the whole column.
        # Returning True here avoids misleading single-row results.
        return True
    _check.__name__ = "unique"
    _check._sql_params = {}
    _check._is_column_level = True
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
    """Check that a string value matches the given regex pattern.

    The pattern is validated against known ReDoS (Regular Expression
    Denial of Service) patterns. Patterns with nested quantifiers or
    excessive repetition counts are rejected.
    """
    _validate_regex_pattern(pattern)
    compiled = re.compile(pattern)

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return bool(compiled.match(str(value)))
    _check.__name__ = f"regex_match('{pattern}')"
    _check._sql_params = {"pattern": pattern}
    return _check


def in_set(allowed_values: Container):
    """Check that a value is in the allowed set.

    Elements must be hashable. For unhashable types (lists, dicts),
    wrap them in tuples first.
    """
    if not hasattr(allowed_values, '__contains__') and not hasattr(allowed_values, '__iter__'):
        raise TypeError(
            f"in_set() requires an iterable, got {type(allowed_values).__name__}"
        )
    try:
        allowed: Set = set(allowed_values)
    except TypeError:
        # Unhashable elements — fall back to list
        allowed = list(allowed_values)

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return value in allowed
    _check.__name__ = f"in_set({allowed_values})"
    _check._sql_params = {"allowed_values": list(allowed_values) if isinstance(allowed, set) else allowed_values}
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
    """Wrap a custom validation function. Cannot be translated to SQL.

    WARNING: Custom functions execute arbitrary Python code. Do not
    use with functions from untrusted sources.
    """
    def _check(value: Any) -> bool:
        return func(value)
    _check.__name__ = name or getattr(func, "__name__", "custom")
    _check._sql_params = None  # custom checks cannot be translated to SQL
    return _check
