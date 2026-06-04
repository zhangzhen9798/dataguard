"""
PySpark-based validation engine.

Supports sensitive column masking for PII protection.
Uses native Spark SQL expressions for built-in checks (better than UDFs
in terms of Catalyst optimization and serialization cost).
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from dataguard.rules import Rule, RuleSet
from dataguard.report import ValidationResult
from dataguard.utils import CheckSpec, mask_value, collect_unique_checks

if TYPE_CHECKING:
    from pyspark.sql import DataFrame as SparkDataFrame

logger = logging.getLogger(__name__)


def _check_spark_available() -> bool:
    """Check if PySpark is available."""
    try:
        import pyspark  # noqa: F401

        return True
    except ImportError:
        return False


def validate_spark(
    df: SparkDataFrame,
    rules: RuleSet,
    sensitive_columns: set[str] | None = None,
) -> list[ValidationResult]:
    """Validate a PySpark DataFrame against a RuleSet.

    Args:
        df: A PySpark DataFrame.
        rules: A RuleSet containing validation rules.
        sensitive_columns: Set of column names containing PII —
            sample_failures will be masked in results.

    Returns:
        A list of ValidationResult objects.
    """
    if not _check_spark_available():
        raise ImportError(
            "PySpark is required for Spark engine. "
            "Install it with: pip install dataguard[spark]"
        )

    from pyspark.sql import functions as F

    sensitive = sensitive_columns or set()
    results: list[ValidationResult] = []
    unique_checks = collect_unique_checks(rules)

    # Cache total_rows to avoid repeated df.count() per rule
    total_rows = df.count()

    for rule in rules.rules:
        result = _validate_spark_rule(df, rule, total_rows, unique_checks, F, sensitive)
        results.append(result)

    return results


def _validate_spark_rule(
    df: SparkDataFrame,
    rule: Rule,
    total_rows: int,
    unique_checks: dict[str, bool],
    F,
    sensitive_columns: set[str],
) -> ValidationResult:
    """Validate a single rule against a Spark DataFrame.

    Uses native Spark SQL expressions for built-in checks instead of
    Python UDFs for better performance and Catalyst optimization.
    """
    is_sensitive = rule.column in sensitive_columns
    spec: CheckSpec = rule.check

    if rule.column not in df.columns:
        return ValidationResult(
            column=rule.column,
            check_name=rule.check_name,
            passed=False,
            total_rows=total_rows,
            passed_rows=0,
            failed_rows=total_rows,
            pass_rate=0.0,
            threshold=rule.threshold,
            sample_failures=["[COLUMN_NOT_FOUND]"],
        )

    if spec.is_column_level:
        return _validate_spark_column_level(df, rule, total_rows, F, is_sensitive)

    # Row-level checks — native expression preferred
    check_col = f"__dg_check_{rule.column}_{_safe_col_name(rule.check_name)}"
    base_name = rule.check_name.split("(")[0].strip()
    params = spec.sql_params

    native_expr = _get_native_spark_expr(base_name, params, rule.column, F)
    if native_expr is not None:
        result_df = df.withColumn(check_col, native_expr)
    else:
        # Fallback to Python UDF for custom / unrecognized checks
        from pyspark.sql.types import BooleanType
        from pyspark.sql.functions import udf as spark_udf

        check_udf = spark_udf(rule.check, BooleanType())
        result_df = df.withColumn(check_col, check_udf(F.col(rule.column)))

    passed_rows = result_df.filter(F.col(check_col) == True).count()  # noqa: E712
    failed_rows = total_rows - passed_rows
    pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0

    # Get sample failures
    failures = (
        result_df.filter(F.col(check_col) == False)  # noqa: E712
        .select(rule.column)
        .limit(5)
        .collect()
    )
    raw_failures = [row[0] for row in failures]
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


def _validate_spark_column_level(
    df: SparkDataFrame,
    rule: Rule,
    total_rows: int,
    F,
    is_sensitive: bool,
) -> ValidationResult:
    """Handle column-level checks for Spark (unique, max_value, min_value)."""
    check_name = rule.check_name
    spec: CheckSpec = rule.check
    params = spec.sql_params or {}
    col = F.col(rule.column)

    if "unique" in check_name:
        distinct_count = df.select(rule.column).distinct().count()
        failed_rows = total_rows - distinct_count
        passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0

        # Get sample duplicates
        from pyspark.sql import Window

        window = Window.partitionBy(rule.column).orderBy(F.lit(0))
        duplicated = (
            df.withColumn("_row_num", F.row_number().over(window))
            .filter(F.col("_row_num") > 1)
            .select(rule.column)
            .limit(5)
            .collect()
        )
        raw_failures = [row[0] for row in duplicated]
    elif "max_value" in check_name:
        max_val = params.get("max_val")
        actual_max = df.agg(F.max(col).alias("m")).collect()[0]["m"]
        if actual_max is None:
            failed_rows = total_rows
            passed_rows = 0
        else:
            failed_rows = df.filter(col > max_val).count()
            passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        raw_failures = df.filter(col > max_val).select(rule.column).limit(5).collect()
        raw_failures = [row[0] for row in raw_failures]
    elif "min_value" in check_name:
        min_val = params.get("min_val")
        actual_min = df.agg(F.min(col).alias("m")).collect()[0]["m"]
        if actual_min is None:
            failed_rows = total_rows
            passed_rows = 0
        else:
            failed_rows = df.filter(col < min_val).count()
            passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0
        raw_failures = df.filter(col < min_val).select(rule.column).limit(5).collect()
        raw_failures = [row[0] for row in raw_failures]
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


def _safe_col_name(name: str) -> str:
    """Sanitize a check name for use as a Spark column name."""
    return (
        name.replace("(", "")
        .replace(")", "")
        .replace(",", "_")
        .replace("'", "")
        .replace(" ", "")
    )


def _get_native_spark_expr(
    base_name: str,
    params: dict[str, Any] | None,
    column: str,
    F,
) -> Any:
    """Build a native Spark SQL expression for a built-in check.

    Returns a Column expression or None if the check requires a Python UDF.
    Native expressions are preferred because:
    - They benefit from Catalyst optimizer (predicate pushdown, etc.)
    - They avoid Python UDF serialization overhead
    - They can run in Tungsten's off-heap mode
    """
    if params is None:
        return None  # custom check, fall back to UDF

    col = F.col(column)

    if base_name == "not_null":
        return col.isNotNull()

    if base_name == "is_numeric":
        # Spark: use CAST to double, NULL means not numeric
        return col.isNull() | col.cast("double").isNotNull()

    if base_name == "is_email":
        email_re = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
        return col.isNull() | col.cast("string").rlike(email_re)

    if base_name == "is_date":
        fmt = params.get("format_str")
        if not fmt:
            # Best-effort: try Spark's default date parsing
            return col.isNull() | F.to_date(col.cast("string")).isNotNull()
        # With format: use to_date with format string
        return col.isNull() | F.to_date(col.cast("string"), fmt).isNotNull()

    if base_name == "not_empty_string":
        return col.isNull() | (F.trim(col.cast("string")) != F.lit(""))

    if base_name == "in_range":
        min_val = params.get("min_val")
        max_val = params.get("max_val")
        condition = F.lit(True)
        if min_val is not None:
            condition = condition & (col >= min_val)
        if max_val is not None:
            condition = condition & (col <= max_val)
        return condition | col.isNull()

    if base_name == "in_set":
        allowed = params.get("allowed_values", [])
        if not allowed:
            return F.lit(False)
        return col.isin(allowed) | col.isNull()

    if base_name == "regex_match":
        pattern = params.get("pattern", "")
        return col.isNull() | col.cast("string").rlike(pattern)

    if base_name == "min_length":
        n = params.get("min_len", 0)
        return col.isNull() | (F.length(col.cast("string")) >= n)

    if base_name == "max_length":
        n = params.get("max_len", 0)
        return col.isNull() | (F.length(col.cast("string")) <= n)

    return None  # unrecognized, fall back to UDF


def profile_spark(
    df: SparkDataFrame,
    sensitive_columns: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate a data profile for all columns in a Spark DataFrame.

    Args:
        df: PySpark DataFrame to profile.
        sensitive_columns: Set of column names containing PII —
            min/max/mean/std stats will be suppressed for these columns.
    """
    from pyspark.sql import functions as F

    sensitive = sensitive_columns or set()
    profile: dict[str, dict[str, Any]] = {}
    total_rows = df.count()

    for col_name in df.columns:
        col_type = df.schema[col_name].dataType
        null_count = df.filter(F.col(col_name).isNull()).count()
        distinct_count = df.select(col_name).distinct().count()

        col_profile: dict[str, Any] = {
            "dtype": str(col_type),
            "total_rows": total_rows,
            "null_count": null_count,
            "null_rate": null_count / total_rows if total_rows > 0 else 0.0,
            "distinct_count": distinct_count,
        }

        # Numeric stats — suppress for sensitive columns
        if col_name in sensitive:
            col_profile["min"] = None
            col_profile["max"] = None
            col_profile["mean"] = None
            col_profile["std"] = None
        else:
            from pyspark.sql.types import NumericType

            if isinstance(col_type, NumericType):
                stats = df.select(
                    F.min(col_name).alias("min"),
                    F.max(col_name).alias("max"),
                    F.mean(col_name).alias("mean"),
                    F.stddev(col_name).alias("std"),
                ).collect()[0]

                col_profile["min"] = stats["min"]
                col_profile["max"] = stats["max"]
                col_profile["mean"] = stats["mean"]
                col_profile["std"] = stats["std"]

        profile[col_name] = col_profile

    return profile
