"""
Pandas-based validation engine.
"""

from typing import Any, Dict, List
import pandas as pd
import numpy as np

from dataguard.rules import Rule, RuleSet
from dataguard.report import ValidationResult


def validate_pandas(df: pd.DataFrame, rules: RuleSet) -> List[ValidationResult]:
    """
    Validate a Pandas DataFrame against a RuleSet.

    Returns a list of ValidationResult objects.
    """
    results = []
    unique_checks = _collect_unique_checks(rules)

    for rule in rules.rules:
        result = _validate_rule(df, rule, unique_checks)
        results.append(result)

    return results


def _collect_unique_checks(rules: RuleSet) -> Dict[str, bool]:
    """Identify columns that have uniqueness checks."""
    unique_cols = {}
    for rule in rules.rules:
        if rule.check_name == "unique":
            unique_cols[rule.column] = True
    return unique_cols


def _validate_rule(df: pd.DataFrame, rule: Rule, unique_checks: Dict[str, bool]) -> ValidationResult:
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
            sample_failures=[f"Column '{rule.column}' not found"],
        )

    column_data = df[rule.column]
    total_rows = len(df)

    # Handle uniqueness check at column level
    if rule.check_name == "unique":
        duplicated = column_data.duplicated(keep="first")
        failed_rows = int(duplicated.sum())
        passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        sample_failures = column_data[duplicated].head(5).tolist()
    else:
        # Row-level check
        check_results = column_data.apply(lambda v: rule.check(v))
        passed_rows = int(check_results.sum())
        failed_rows = total_rows - passed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        sample_failures = column_data[~check_results].head(5).tolist()

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


def profile_pandas(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Generate a data profile for all columns in a Pandas DataFrame."""
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

        # Numeric stats
        if pd.api.types.is_numeric_dtype(col_data):
            col_profile["min"] = float(col_data.min()) if not pd.isna(col_data.min()) else None
            col_profile["max"] = float(col_data.max()) if not pd.isna(col_data.max()) else None
            col_profile["mean"] = float(col_data.mean()) if not pd.isna(col_data.mean()) else None
            col_profile["std"] = float(col_data.std()) if not pd.isna(col_data.std()) else None

        profile[col] = col_profile

    return profile
