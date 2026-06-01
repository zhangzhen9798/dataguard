"""
Pandas-based validation engine.

Uses vectorized operations for performance instead of row-by-row apply().
Supports sensitive column masking for PII protection.
"""

import logging
from typing import Any, Dict, List, Optional, Set

import pandas as pd
import numpy as np

from dataguard.rules import Rule, RuleSet
from dataguard.report import ValidationResult

logger = logging.getLogger(__name__)


def _mask_value(value: Any) -> str:
    """Mask a sensitive value for PII protection."""
    s = str(value)
    if len(s) <= 2:
        return "***"
    return s[0] + "***" + s[-1]


def validate_pandas(
    df: pd.DataFrame,
    rules: RuleSet,
    sensitive_columns: Optional[Set[str]] = None,
) -> List[ValidationResult]:
    """Validate a Pandas DataFrame against a RuleSet.

    Args:
        df: Pandas DataFrame to validate.
        rules: RuleSet with validation rules.
        sensitive_columns: Set of column names containing PII —
            sample_failures will be masked in results.

    Returns a list of ValidationResult objects.
    """
    sensitive = sensitive_columns or set()
    results = []
    unique_checks = _collect_unique_checks(rules)

    for rule in rules.rules:
        result = _validate_rule(df, rule, unique_checks, sensitive)
        results.append(result)

    return results


def _collect_unique_checks(rules: RuleSet) -> Dict[str, bool]:
    """Identify columns that have uniqueness checks."""
    unique_cols = {}
    for rule in rules.rules:
        if rule.check_name == "unique":
            unique_cols[rule.column] = True
    return unique_cols


def _validate_rule(
    df: pd.DataFrame,
    rule: Rule,
    unique_checks: Dict[str, bool],
    sensitive_columns: Set[str],
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
    if rule.check_name == "unique":
        duplicated = column_data.duplicated(keep="first")
        failed_rows = int(duplicated.sum())
        passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        raw_failures = column_data[duplicated].head(5).tolist()
        sample_failures = [_mask_value(v) for v in raw_failures] if is_sensitive else raw_failures
    else:
        # Try vectorized check first, fall back to apply
        check_results = _vectorized_check(column_data, rule)
        passed_rows = int(check_results.sum())
        failed_rows = total_rows - passed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        raw_failures = column_data[~check_results].head(5).tolist()
        sample_failures = [_mask_value(v) for v in raw_failures] if is_sensitive else raw_failures

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


def _vectorized_check(column_data: pd.Series, rule: Rule) -> pd.Series:
    """Apply a check function using vectorized ops when possible.

    Falls back to apply() for custom or unrecognized checks.
    """
    base_name = rule.check_name.split("(")[0].strip()
    params = getattr(rule.check, "_sql_params", None)

    if base_name == "not_null":
        result = column_data.notna()
        # Also handle pd.NA
        try:
            result = result & ~(column_data.isna())
        except TypeError:
            pass
        return result

    if base_name == "in_range" and params is not None:
        min_val = params.get("min_val")
        max_val = params.get("max_val")
        not_null = column_data.notna()
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
        return result | ~not_null  # nulls pass range checks

    if base_name == "in_set" and params is not None:
        allowed = params.get("allowed_values", [])
        if not allowed:
            return pd.Series(False, index=column_data.index)
        not_null = column_data.notna()
        try:
            return column_data.isin(allowed) | ~not_null
        except TypeError:
            return column_data.apply(rule.check)

    if base_name == "regex_match" and params is not None:
        pattern = params.get("pattern", "")
        not_null = column_data.notna()
        try:
            return column_data.astype(str).str.match(pattern, na=False) | ~not_null
        except Exception:
            return column_data.apply(rule.check)

    if base_name == "min_length" and params is not None:
        n = params.get("min_len", 0)
        not_null = column_data.notna()
        try:
            return (column_data.astype(str).str.len() >= n) | ~not_null
        except Exception:
            return column_data.apply(rule.check)

    if base_name == "max_length" and params is not None:
        n = params.get("max_len", 0)
        not_null = column_data.notna()
        try:
            return (column_data.astype(str).str.len() <= n) | ~not_null
        except Exception:
            return column_data.apply(rule.check)

    # Fallback for custom or unrecognized checks
    return column_data.apply(lambda v: rule.check(v))


def profile_pandas(
    df: pd.DataFrame,
    sensitive_columns: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Generate a data profile for all columns in a Pandas DataFrame.

    Args:
        df: Pandas DataFrame to profile.
        sensitive_columns: Set of column names containing PII —
            min/max/mean/std stats will be suppressed for these columns.
    """
    sensitive = sensitive_columns or set()
    profile = {}
    for col in df.columns:
        col_data = df[col]
        null_count = int(col_data.isna().sum())
        distinct_count = int(col_data.nunique())

        col_profile: Dict[str, Any] = {
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
            col_profile["min"] = float(col_data.min()) if not pd.isna(col_data.min()) else None
            col_profile["max"] = float(col_data.max()) if not pd.isna(col_data.max()) else None
            col_profile["mean"] = float(col_data.mean()) if not pd.isna(col_data.mean()) else None
            col_profile["std"] = float(col_data.std()) if not pd.isna(col_data.std()) else None

        profile[col] = col_profile

    return profile
