"""
Pandas-based validation engine.

Uses vectorized operations for performance instead of row-by-row apply().
Supports sensitive column masking for PII protection.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from dataguard.rules import Rule, RuleSet
from dataguard.report import ValidationResult
from dataguard.utils import CheckSpec, mask_value, collect_unique_checks

logger = logging.getLogger(__name__)


def validate_pandas(
    df: pd.DataFrame,
    rules: RuleSet,
    sensitive_columns: set[str] | None = None,
) -> list[ValidationResult]:
    """Validate a Pandas DataFrame against a RuleSet.

    Args:
        df: Pandas DataFrame to validate.
        rules: RuleSet with validation rules.
        sensitive_columns: Set of column names containing PII —
            sample_failures will be masked in results.

    Returns a list of ValidationResult objects.
    """
    sensitive = sensitive_columns or set()
    results: list[ValidationResult] = []
    unique_checks = collect_unique_checks(rules)

    for rule in rules.rules:
        result = _validate_rule(df, rule, unique_checks, sensitive)
        results.append(result)

    return results


def _validate_rule(
    df: pd.DataFrame,
    rule: Rule,
    unique_checks: dict[str, bool],
    sensitive_columns: set[str],
) -> ValidationResult:
    """Validate a single rule against the DataFrame."""
    if rule.column not in df.columns:
        return ValidationResult(
            column=rule.column,
            check_name=rule.check_name,
            passed=False,
            total_rows=len(df),
            passed_rows=0,
            failed_rows=len(df),
            pass_rate=0.0,
            threshold=rule.threshold,
            sample_failures=["[COLUMN_NOT_FOUND]"],
        )

    column_data = df[rule.column]
    total_rows = len(df)
    is_sensitive = rule.column in sensitive_columns

    # Handle uniqueness check at column level
    if rule.check.is_column_level:
        return _validate_column_level(column_data, rule, total_rows, is_sensitive)

    # Row-level checks
    check_results = _vectorized_check(column_data, rule)
    passed_rows = int(check_results.sum())
    failed_rows = total_rows - passed_rows
    pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
    raw_failures = column_data[~check_results].head(5).tolist()
    sample_failures = (
        [mask_value(v) for v in raw_failures] if is_sensitive else raw_failures
    )

    passed = pass_rate >= rule.threshold

    return ValidationResult(
        column=rule.column,
        check_name=rule.check_name,
        passed=passed,
        total_rows=total_rows,
        passed_rows=passed_rows,
        failed_rows=failed_rows,
        pass_rate=pass_rate,
        threshold=rule.threshold,
        sample_failures=sample_failures,
    )


def _validate_column_level(
    column_data: pd.Series,
    rule: Rule,
    total_rows: int,
    is_sensitive: bool,
) -> ValidationResult:
    """Handle column-level checks (unique, max_value, min_value)."""
    check_name = rule.check_name
    spec: CheckSpec = rule.check
    params = spec.sql_params or {}

    if "unique" in check_name:
        duplicated = column_data.duplicated(keep="first")
        failed_rows = int(duplicated.sum())
        passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        raw_failures = column_data[duplicated].head(5).tolist()
    elif "max_value" in check_name:
        max_val = params.get("max_val")
        col_numeric = pd.to_numeric(column_data, errors="coerce")
        actual_max = col_numeric.max()
        failed_rows = (
            int((col_numeric > max_val).sum()) if pd.notna(actual_max) else total_rows
        )
        passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        raw_failures = (
            column_data[col_numeric > max_val].head(5).tolist()
            if pd.notna(max_val)
            else []
        )
    elif "min_value" in check_name:
        min_val = params.get("min_val")
        col_numeric = pd.to_numeric(column_data, errors="coerce")
        actual_min = col_numeric.min()
        failed_rows = (
            int((col_numeric < min_val).sum()) if pd.notna(actual_min) else total_rows
        )
        passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        raw_failures = (
            column_data[col_numeric < min_val].head(5).tolist()
            if pd.notna(min_val)
            else []
        )
    else:
        return ValidationResult(
            column=rule.column,
            check_name=check_name,
            passed=False,
            total_rows=total_rows,
            passed_rows=0,
            failed_rows=total_rows,
            pass_rate=0.0,
            threshold=rule.threshold,
            sample_failures=[f"[UNKNOWN_COLUMN_CHECK: {check_name}]"],
        )

    sample_failures = (
        [mask_value(v) for v in raw_failures] if is_sensitive else raw_failures
    )
    passed = pass_rate >= rule.threshold

    return ValidationResult(
        column=rule.column,
        check_name=check_name,
        passed=passed,
        total_rows=total_rows,
        passed_rows=passed_rows,
        failed_rows=failed_rows,
        pass_rate=pass_rate,
        threshold=rule.threshold,
        sample_failures=sample_failures,
    )


def _vectorized_check(column_data: pd.Series, rule: Rule) -> pd.Series:
    """Apply a check function using vectorized ops when possible.

    Falls back to apply() for custom or unrecognized checks.
    """
    base_name = rule.check_name.split("(")[0].strip()
    spec: CheckSpec = rule.check
    params = spec.sql_params

    if base_name == "not_null":
        return column_data.notna()

    if base_name == "is_numeric":
        # None/NaN pass (use notna mask to preserve None as pass)
        not_null_mask = column_data.notna()
        # pd.to_numeric coerce: non-numeric → NaN
        numeric_check = pd.to_numeric(column_data, errors="coerce").notna()
        # Reject bool values (bool is subclass of int in Python/pandas)
        if column_data.dtype == "bool":
            numeric_check = pd.Series(False, index=column_data.index)
        elif column_data.dtype == "object":
            # For object columns, reject string "True"/"False"
            numeric_check = numeric_check & ~column_data.astype(str).str.lower().isin(
                {"true", "false"}
            )
        # None passes: combine with not_null_mask negated
        return numeric_check | ~not_null_mask

    if base_name == "is_email":
        import re

        email_re = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
        not_null_mask = column_data.notna()
        try:
            return (
                column_data.astype(str).str.match(email_re.pattern, na=False)
                | ~not_null_mask
            )
        except Exception:
            return column_data.apply(
                lambda v: bool(email_re.match(str(v))) if v is not None else True
            )

    if base_name == "is_date":
        not_null_mask = column_data.notna()
        fmt = params.get("format_str") if params else None
        try:
            if fmt:
                parsed = pd.to_datetime(column_data, format=fmt, errors="coerce")
            else:
                parsed = pd.to_datetime(column_data, errors="coerce")
            return parsed.notna() | ~not_null_mask
        except Exception:
            return pd.Series(True, index=column_data.index)

    if base_name == "not_empty_string":
        not_null_mask = column_data.notna()
        try:
            stripped = column_data.astype(str).str.strip()
            return (stripped != "") | ~not_null_mask
        except Exception:
            return column_data.apply(lambda v: v is not None and str(v).strip() != "")

    if base_name == "in_range" and params is not None:
        min_val = params.get("min_val")
        max_val = params.get("max_val")
        not_null_mask = column_data.notna()
        result = pd.Series(True, index=column_data.index)
        if min_val is not None:
            try:
                result = result & (column_data >= min_val)
            except TypeError:
                return column_data.apply(rule.check)
        if max_val is not None:
            try:
                result = result & (column_data <= max_val)
            except TypeError:
                return column_data.apply(rule.check)
        return result | ~not_null_mask

    if base_name == "in_set" and params is not None:
        allowed = params.get("allowed_values", [])
        if not allowed:
            return pd.Series(False, index=column_data.index)
        not_null_mask = column_data.notna()
        try:
            return column_data.isin(allowed) | ~not_null_mask
        except TypeError:
            return column_data.apply(rule.check)

    if base_name == "regex_match" and params is not None:
        pattern = params.get("pattern", "")
        not_null_mask = column_data.notna()
        try:
            return column_data.astype(str).str.match(pattern, na=False) | ~not_null_mask
        except Exception:
            return column_data.apply(rule.check)

    if base_name == "min_length" and params is not None:
        n = params.get("min_len", 0)
        not_null_mask = column_data.notna()
        try:
            return (column_data.astype(str).str.len() >= n) | ~not_null_mask
        except Exception:
            return column_data.apply(rule.check)

    if base_name == "max_length" and params is not None:
        n = params.get("max_len", 0)
        not_null_mask = column_data.notna()
        try:
            return (column_data.astype(str).str.len() <= n) | ~not_null_mask
        except Exception:
            return column_data.apply(rule.check)

    # Fallback for custom or unrecognized checks
    return column_data.apply(lambda v: rule.check(v))


def profile_pandas(
    df: pd.DataFrame,
    sensitive_columns: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate a data profile for all columns in a Pandas DataFrame.

    Args:
        df: Pandas DataFrame to profile.
        sensitive_columns: Set of column names containing PII —
            min/max/mean/std stats will be suppressed for these columns.
    """
    sensitive = sensitive_columns or set()
    profile: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        col_data = df[col]
        null_count = int(col_data.isna().sum())
        distinct_count = int(col_data.nunique())

        col_profile: dict[str, Any] = {
            "dtype": str(col_data.dtype),
            "total_rows": len(col_data),
            "null_count": null_count,
            "null_rate": null_count / len(col_data) if len(col_data) > 0 else 0.0,
            "distinct_count": distinct_count,
        }

        # Numeric stats — suppress for sensitive columns
        if col in sensitive:
            col_profile["min"] = None
            col_profile["max"] = None
            col_profile["mean"] = None
            col_profile["std"] = None
        elif pd.api.types.is_numeric_dtype(col_data):
            col_profile["min"] = (
                float(col_data.min()) if not pd.isna(col_data.min()) else None
            )
            col_profile["max"] = (
                float(col_data.max()) if not pd.isna(col_data.max()) else None
            )
            col_profile["mean"] = (
                float(col_data.mean()) if not pd.isna(col_data.mean()) else None
            )
            col_profile["std"] = (
                float(col_data.std()) if not pd.isna(col_data.std()) else None
            )

        profile[col] = col_profile

    return profile
