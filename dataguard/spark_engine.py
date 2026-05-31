"""
PySpark-based validation engine.
"""

from typing import Any, Dict, List

from dataguard.rules import Rule, RuleSet
from dataguard.report import ValidationResult


def _check_spark_available():
    """Check if PySpark is available."""
    try:
        import pyspark  # noqa: F401
        return True
    except ImportError:
        return False


def validate_spark(df, rules: RuleSet) -> List[ValidationResult]:
    """
    Validate a PySpark DataFrame against a RuleSet.

    Args:
        df: A PySpark DataFrame.
        rules: A RuleSet containing validation rules.

    Returns:
        A list of ValidationResult objects.
    """
    if not _check_spark_available():
        raise ImportError(
            "PySpark is required for Spark engine. "
            "Install it with: pip install dataguard[spark]"
        )

    from pyspark.sql import functions as F

    results = []
    unique_checks = _collect_unique_checks(rules)

    for rule in rules.rules:
        result = _validate_spark_rule(df, rule, unique_checks, F)
        results.append(result)

    return results


def _collect_unique_checks(rules: RuleSet) -> Dict[str, bool]:
    """Identify columns that have uniqueness checks."""
    unique_cols = {}
    for rule in rules.rules:
        if rule.check_name == "unique":
            unique_cols[rule.column] = True
    return unique_cols


def _validate_spark_rule(df, rule: Rule, unique_checks: Dict[str, bool], F) -> ValidationResult:
    """Validate a single rule against a Spark DataFrame."""
    total_rows = df.count()

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
            sample_failures=[f"Column '{rule.column}' not found"],
        )

    if rule.check_name == "unique":
        # Uniqueness check at column level
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
        sample_failures = [row[0] for row in duplicated]
    else:
        # Row-level check using UDF
        from pyspark.sql.types import BooleanType
        from pyspark.sql.functions import udf as spark_udf

        check_udf = spark_udf(rule.check, BooleanType())
        check_col = f"__dataguard_check_{rule.column}_{rule.check_name}"
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
        sample_failures = [row[0] for row in failures]

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


def profile_spark(df) -> Dict[str, Dict[str, Any]]:
    """Generate a data profile for all columns in a Spark DataFrame."""
    from pyspark.sql import functions as F

    profile = {}
    total_rows = df.count()

    for col_name in df.columns:
        col_type = df.schema[col_name].dataType
        null_count = df.filter(F.col(col_name).isNull()).count()
        distinct_count = df.select(col_name).distinct().count()

        col_profile: Dict[str, Any] = {
            "dtype": str(col_type),
            "total_rows": total_rows,
            "null_count": null_count,
            "null_rate": null_count / total_rows if total_rows > 0 else 0.0,
            "distinct_count": distinct_count,
        }

        # Numeric stats
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
