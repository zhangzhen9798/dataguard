"""
SQL-based validation engine for DataGuard.

Supports MySQL, Hive, Flink SQL, Doris, and SelectDB via SQLAlchemy.
"""

import warnings
from typing import Any, Dict, List, Optional

from dataguard.rules import Rule, RuleSet
from dataguard.report import ValidationResult
from dataguard.sql_dialects import (
    Dialect, DIALECTS, get_dialect, quote_id, sql_value,
    check_to_condition, _MYSQL_PROTOCOL_DIALECTS,
)


def _get_sa_engine(connection):
    """Accept a SQLAlchemy Engine, connection string, or connection object."""
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import Engine
    except ImportError:
        raise ImportError(
            "SQLAlchemy is required for SQL engine. "
            "Install it with: pip install dqguard[sql]"
        )

    if isinstance(connection, Engine):
        return connection
    if isinstance(connection, str):
        return create_engine(connection)
    # Maybe it's a raw connection or something else with execute()
    if hasattr(connection, "execute") and hasattr(connection, "connect"):
        return connection
    raise TypeError(
        f"Expected SQLAlchemy Engine, connection string, or Engine-like object, "
        f"got {type(connection).__name__}"
    )


def _exec_query(engine, sql: str) -> List[dict]:
    """Execute a SQL query and return rows as dicts."""
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(text(sql))
        cols = result.keys()
        return [dict(zip(cols, row)) for row in result.fetchall()]


def validate_sql(
    connection,
    table: str,
    rules: RuleSet,
    dialect: str = "mysql",
    schema: Optional[str] = None,
) -> List[ValidationResult]:
    """Validate a SQL table against a RuleSet.

    Args:
        connection: SQLAlchemy Engine or connection string.
        table: Table name to validate.
        rules: RuleSet with validation rules.
        dialect: SQL dialect name (mysql, hive, flink, doris, selectdb).
        schema: Optional schema/database name.
    """
    d = get_dialect(dialect)
    engine = _get_sa_engine(connection)

    # Build full table reference
    if schema:
        full_table = f"{quote_id(schema, d)}.{quote_id(table, d)}"
    else:
        full_table = quote_id(table, d)

    results = []
    for rule in rules.rules:
        result = _validate_sql_rule(engine, full_table, rule, d)
        results.append(result)

    return results


def _base_check_name(check_name: str) -> str:
    """Extract the base check name without parameters.

    'in_range(0, 120)' -> 'in_range'
    'not_null' -> 'not_null'
    """
    return check_name.split("(")[0].strip()


def _validate_sql_rule(
    engine, table: str, rule: Rule, dialect: Dialect
) -> ValidationResult:
    """Validate a single rule against a SQL table."""
    col = quote_id(rule.column, dialect)
    base_name = _base_check_name(rule.check_name)

    # Get total row count
    total_rows = _exec_query(engine, f"SELECT COUNT(*) AS cnt FROM {table}")[0]["cnt"]

    # Check if column exists
    # (We let the database complain if column doesn't exist — same behavior as pandas engine)

    # Get SQL params from the check function
    params = getattr(rule.check, "_sql_params", None)
    if params is None:
        # custom() check — can't translate to SQL
        warnings.warn(
            f"Check '{rule.check_name}' on column '{rule.column}' cannot be "
            f"translated to SQL and will be skipped.",
            UserWarning,
            stacklevel=2,
        )
        return ValidationResult(
            column=rule.column,
            check_name=rule.check_name,
            passed=True,  # skip = pass by default
            total_rows=total_rows,
            passed_rows=total_rows,
            failed_rows=0,
            pass_rate=1.0,
            threshold=rule.threshold,
            sample_failures=["[SKIPPED] Custom check not translatable to SQL"],
        )

    # Generate SQL condition
    condition = check_to_condition(base_name, params, col, dialect)

    if condition is None and base_name == "unique":
        # Unique check — special aggregate query
        return _validate_unique_sql(engine, table, col, rule, total_rows, dialect)

    if condition is None:
        warnings.warn(
            f"Check '{rule.check_name}' cannot be translated to SQL, skipping.",
            UserWarning,
            stacklevel=2,
        )
        return ValidationResult(
            column=rule.column,
            check_name=rule.check_name,
            passed=True,
            total_rows=total_rows,
            passed_rows=total_rows,
            failed_rows=0,
            pass_rate=1.0,
            threshold=rule.threshold,
            sample_failures=["[SKIPPED]"],
        )

    # Count passed rows
    count_sql = f"SELECT SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) AS passed FROM {table}"
    row = _exec_query(engine, count_sql)[0]
    passed_rows = int(row["passed"] or 0)
    failed_rows = total_rows - passed_rows
    pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0

    # Get sample failures
    neg_condition = f"NOT ({condition})"
    sample_sql = (
        f"SELECT {rule.column} AS val FROM {table} "
        f"WHERE {neg_condition} {dialect.limit_fmt.format(n=5)}"
    )
    try:
        sample_rows = _exec_query(engine, sample_sql)
        sample_failures = [r["val"] for r in sample_rows[:5]]
    except Exception:
        sample_failures = []

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


def _validate_unique_sql(
    engine, table: str, col: str, rule: Rule, total_rows: int, dialect: Dialect
) -> ValidationResult:
    """Handle unique check with SQL aggregate."""
    count_sql = f"SELECT COUNT(DISTINCT {col}) AS distinct_cnt FROM {table}"
    row = _exec_query(engine, count_sql)[0]
    distinct_count = int(row["distinct_cnt"] or 0)
    failed_rows = total_rows - distinct_count
    passed_rows = total_rows - failed_rows
    pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0

    # Sample duplicates
    sample_sql = (
        f"SELECT {rule.column} AS val FROM {table} "
        f"GROUP BY {col} HAVING COUNT(*) > 1 "
        f"{dialect.limit_fmt.format(n=5)}"
    )
    try:
        sample_rows = _exec_query(engine, sample_sql)
        sample_failures = [r["val"] for r in sample_rows[:5]]
    except Exception:
        sample_failures = []

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


def profile_sql(
    connection,
    table: str,
    dialect: str = "mysql",
    schema: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Generate a data profile for a SQL table."""
    d = get_dialect(dialect)
    engine = _get_sa_engine(connection)

    if schema:
        full_table = f"{quote_id(schema, d)}.{quote_id(table, d)}"
    else:
        full_table = quote_id(table, d)

    # Get column names
    col_sql = f"SELECT * FROM {full_table} {d.limit_fmt.format(n=0)}"
    # Most DBs don't support LIMIT 0 for this, use LIMIT 1 and ignore data
    col_sql = f"SELECT * FROM {full_table} {d.limit_fmt.format(n=1)}"
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text(col_sql))
            columns = list(result.keys())
    except Exception:
        # Fallback: try INFORMATION_SCHEMA
        return _profile_via_info_schema(engine, table, schema, d)

    # Get total rows
    total_rows = _exec_query(engine, f"SELECT COUNT(*) AS cnt FROM {full_table}")[0]["cnt"]

    profile = {}
    for col_name in columns:
        col = quote_id(col_name, d)
        col_profile: Dict[str, Any] = {
            "total_rows": total_rows,
        }

        # Null count and distinct count
        stats_sql = (
            f"SELECT "
            f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null_count, "
            f"COUNT(DISTINCT {col}) AS distinct_count "
            f"FROM {full_table}"
        )
        row = _exec_query(engine, stats_sql)[0]
        null_count = int(row["null_count"] or 0)
        distinct_count = int(row["distinct_count"] or 0)

        col_profile["null_count"] = null_count
        col_profile["null_rate"] = null_count / total_rows if total_rows > 0 else 0.0
        col_profile["distinct_count"] = distinct_count

        # Try numeric stats (will fail gracefully for non-numeric)
        try:
            num_sql = (
                f"SELECT "
                f"MIN({col}) AS min_val, MAX({col}) AS max_val, "
                f"AVG({col}) AS mean_val "
                f"FROM {full_table} "
                f"WHERE {col} IS NOT NULL"
            )
            num_row = _exec_query(engine, num_sql)[0]
            if num_row["min_val"] is not None:
                col_profile["dtype"] = "numeric"
                col_profile["min"] = float(num_row["min_val"])
                col_profile["max"] = float(num_row["max_val"])
                col_profile["mean"] = float(num_row["mean_val"])
                # Try to get stddev — not all DBs support it
                try:
                    std_sql = f"SELECT STDDEV({col}) AS std_val FROM {full_table} WHERE {col} IS NOT NULL"
                    std_row = _exec_query(engine, std_sql)[0]
                    col_profile["std"] = float(std_row["std_val"]) if std_row["std_val"] is not None else None
                except Exception:
                    col_profile["std"] = None
            else:
                col_profile["dtype"] = "string"
        except Exception:
            col_profile["dtype"] = "string"

        profile[col_name] = col_profile

    return profile


def _profile_via_info_schema(engine, table, schema, dialect):
    """Fallback profiling using INFORMATION_SCHEMA."""
    # Simplified — just return basic info
    return {}
