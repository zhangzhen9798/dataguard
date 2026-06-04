"""
Built-in validation check functions for DataGuard.

Each check function returns a CheckSpec — a callable wrapper
that bundles the check logic with structured metadata (SQL params,
check level) instead of using closure-attribute monkey-patching.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Container

from dataguard.utils import CheckSpec, CheckLevel

# ─── ReDoS Protection ──────────────────────────────────────────────

# Comprehensive dangerous regex patterns that can cause catastrophic backtracking:
# 1. Nested quantifiers: (a+)+
# 2. Overlapping alternations with quantifiers: (a|a)+
# 3. Quantified optional groups: (a?){n} with large n
# 4. Adjacent overlapping groups: (a+a+)+
_DANGEROUS_REGEX_PATTERNS = [
    # Nested quantifiers: (x+)+, (x*)+, (x+)*, (x*)*
    re.compile(r"\([^)]*[*+][^)]*\)[*+]"),
    # Overlapping alternations: (a|a)+, (a|b*)+
    re.compile(r"\([^)]*\|[^)]*\)[*+]"),
    # Quantified groups with inner quantifier + outer quantifier
    re.compile(r"\([^)]*\{[^}]*\}[^)]*\)[*+]"),
    # Adjacent quantified overlapping: a+a+
    re.compile(r"(\w+)[*+]\1[*+]"),
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
    rep_match = re.findall(r"\{(\d+),?\d*\}", pattern)
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


def not_null() -> CheckSpec:
    """Check that value is not None/NaN/pd.NA.

    Note: This is a row-level check. For column-level null-rate
    enforcement, use threshold on the rule.
    """
    _has_pandas = False
    _pd_NA = None
    try:
        import pandas as pd  # noqa: F811

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

    return CheckSpec(
        fn=_check,
        name="not_null",
        sql_params={},
        level=CheckLevel.ROW,
    )


def unique() -> CheckSpec:
    """Check that values in a column are unique.

    This is a column-level constraint, not a row-level check.
    Uniqueness is enforced at the engine level by counting duplicates.
    """

    def _check(value: Any) -> bool:
        return True

    return CheckSpec(
        fn=_check,
        name="unique",
        sql_params={},
        level=CheckLevel.COLUMN,
    )


def in_range(min_val: float | None = None, max_val: float | None = None) -> CheckSpec:
    """Check that a numeric value falls within [min_val, max_val].

    At least one bound required.
    """
    if min_val is None and max_val is None:
        raise ValueError("in_range() requires at least one of min_val or max_val")
    if (min_val is not None and max_val is not None) and min_val > max_val:
        raise ValueError(
            f"min_val ({min_val}) cannot be greater than max_val ({max_val})"
        )

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

    return CheckSpec(
        fn=_check,
        name=f"in_range({min_val}, {max_val})",
        sql_params={"min_val": min_val, "max_val": max_val},
        level=CheckLevel.ROW,
    )


def regex_match(pattern: str) -> CheckSpec:
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

    return CheckSpec(
        fn=_check,
        name=f"regex_match('{pattern}')",
        sql_params={"pattern": pattern},
        level=CheckLevel.ROW,
    )


def in_set(allowed_values: Container) -> CheckSpec:
    """Check that a value is in the allowed set.

    Elements must be hashable. For unhashable types (lists, dicts),
    wrap them in tuples first.
    """
    if not hasattr(allowed_values, "__contains__") and not hasattr(
        allowed_values, "__iter__"
    ):
        raise TypeError(
            f"in_set() requires an iterable, got {type(allowed_values).__name__}"
        )
    try:
        allowed: set[Any] = set(allowed_values)  # type: ignore[call-overload]
    except TypeError:
        # Unhashable elements — fall back to list
        allowed = list(allowed_values)  # type: ignore[call-overload]

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return value in allowed

    return CheckSpec(
        fn=_check,
        name=f"in_set({allowed_values})",
        sql_params={
            "allowed_values": (
                list(allowed_values)  # type: ignore[call-overload]
                if isinstance(allowed, set)
                else allowed_values
            ),
        },
        level=CheckLevel.ROW,
    )


def min_length(min_len: int) -> CheckSpec:
    """Check that a string value has at least min_len characters."""
    if not isinstance(min_len, int) or min_len < 0:
        raise ValueError(
            f"min_length() requires a non-negative integer, got {min_len!r}"
        )

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return len(str(value)) >= min_len

    return CheckSpec(
        fn=_check,
        name=f"min_length({min_len})",
        sql_params={"min_len": min_len},
        level=CheckLevel.ROW,
    )


def max_length(max_len: int) -> CheckSpec:
    """Check that a string value has at most max_len characters."""
    if not isinstance(max_len, int) or max_len < 0:
        raise ValueError(
            f"max_length() requires a non-negative integer, got {max_len!r}"
        )

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return len(str(value)) <= max_len

    return CheckSpec(
        fn=_check,
        name=f"max_length({max_len})",
        sql_params={"max_len": max_len},
        level=CheckLevel.ROW,
    )


def custom(func: Callable[[Any], bool], name: str = "") -> CheckSpec:
    """Wrap a custom validation function. Cannot be translated to SQL.

    WARNING: Custom functions execute arbitrary Python code. Do not
    use with functions from untrusted sources.
    """

    def _check(value: Any) -> bool:
        return func(value)

    check_name = name or getattr(func, "__name__", "custom")

    return CheckSpec(
        fn=_check,
        name=check_name,
        sql_params=None,  # custom checks cannot be translated to SQL
        level=CheckLevel.ROW,
    )


# ─── Email regex (RFC 5322 subset, practical) ────────────────
_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_numeric() -> CheckSpec:
    """Check that value is a valid number (int or float, bool excluded).

    Notes:
    - ``True``/``False`` (bool) are **rejected** because ``bool`` is a
      subclass of ``int`` in Python; use an explicit ``in_range()`` if
      you want to accept them.
    - ``None`` / ``NaN`` pass (use ``not_null()`` together if needed).
    """
    _has_pandas = False
    try:
        import pandas as pd  # noqa: F401

        _has_pandas = True
    except ImportError:
        pass

    def _check(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, bool):
            return False
        if _has_pandas and str(type(value)).startswith("<class 'pandas"):
            # pandas NA / NaT etc.
            import pandas as pd

            if pd.isna(value):
                return True
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    return CheckSpec(
        fn=_check,
        name="is_numeric",
        sql_params={},
        level=CheckLevel.ROW,
    )


def is_email() -> CheckSpec:
    """Check that value looks like a valid email address.

    Uses a practical regex (RFC 5322 subset).  ``None`` passes.
    """
    return CheckSpec(
        fn=lambda v: True if v is None else bool(_EMAIL_REGEX.match(str(v))),
        name="is_email",
        sql_params={"pattern": _EMAIL_REGEX.pattern},
        level=CheckLevel.ROW,
    )


def is_date(format_str: str | None = None) -> CheckSpec:
    """Check that value can be parsed as a date.

    Parameters
    ----------
    format_str :
        Optional Python ``strptime`` format string, e.g. ``"%Y-%m-%d"``.
        When *None* a best-effort auto-detection is used (Pandas engine only;
        for SQL engines *format_str* is **required**).
    """
    if format_str is not None:
        # Validate the format string at definition time by compiling it
        import datetime

        try:
            datetime.datetime.strptime("2000-01-01", format_str)
        except ValueError as e:
            raise ValueError(f"Invalid format string for is_date(): {e}") from e

    def _check(value: Any) -> bool:
        if value is None:
            return True
        s = str(value)
        if format_str is not None:
            import datetime

            try:
                datetime.datetime.strptime(s, format_str)
                return True
            except ValueError:
                return False
        # Best-effort auto-detect
        try:
            import pandas as pd

            parsed = pd.to_datetime(s, errors="coerce")
            return bool(not pd.isna(parsed))
        except ImportError:
            # Fallback: try a few common formats
            import datetime

            for fmt in (
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%m/%d/%Y",
                "%d-%m-%Y",
                "%Y%m%d",
            ):
                try:
                    datetime.datetime.strptime(s, fmt)
                    return True
                except ValueError:
                    continue
            return False

    params: dict[str, Any] = {}
    if format_str is not None:
        params["format_str"] = format_str

    return CheckSpec(
        fn=_check,
        name=f"is_date({format_str})" if format_str else "is_date()",
        sql_params=params or None,
        level=CheckLevel.ROW,
    )


def not_empty_string() -> CheckSpec:
    """Check that value is a non-empty string after trimming whitespace.

    ``None`` passes (use ``not_null()`` together if needed).
    Numbers / other types are cast to ``str`` then checked.
    """
    import re as _re

    _ws_only = _re.compile(r"^\s*$")

    def _check(value: Any) -> bool:
        if value is None:
            return True
        return not bool(_ws_only.match(str(value)))

    return CheckSpec(
        fn=_check,
        name="not_empty_string",
        sql_params={},
        level=CheckLevel.ROW,
    )


def max_value(max_val: float) -> CheckSpec:
    """Column-level check: the maximum value in the column must ≤ *max_val*.

    This is a **column-level** check — the pass/fail decision is made on
    the whole column, not row-by-row.  ``None``/``NaN`` values are
    ignored.

    SQL translation uses ``SELECT MAX(col)``.
    """
    if not isinstance(max_val, (int, float)):
        raise ValueError(
            f"max_value() requires a numeric argument, got {type(max_val).__name__}"
        )

    def _check(value: Any) -> bool:
        # Row-level stub — real logic is in the engine layer
        return True

    return CheckSpec(
        fn=_check,
        name=f"max_value({max_val})",
        sql_params={"max_val": max_val},
        level=CheckLevel.COLUMN,
    )


def min_value(min_val: float) -> CheckSpec:
    """Column-level check: the minimum value in the column must ≥ *min_val*.

    This is a **column-level** check — the pass/fail decision is made on
    the whole column, not row-by-row.  ``None``/``NaN`` values are
    ignored.

    SQL translation uses ``SELECT MIN(col)``.
    """
    if not isinstance(min_val, (int, float)):
        raise ValueError(
            f"min_value() requires a numeric argument, got {type(min_val).__name__}"
        )

    def _check(value: Any) -> bool:
        # Row-level stub — real logic is in the engine layer
        return True

    return CheckSpec(
        fn=_check,
        name=f"min_value({min_val})",
        sql_params={"min_val": min_val},
        level=CheckLevel.COLUMN,
    )
