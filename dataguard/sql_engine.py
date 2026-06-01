"""
SQL-based validation engine for DataGuard.

Supports MySQL, Hive, Flink SQL, Doris, and SelectDB via SQLAlchemy.
Uses parameterized queries to prevent SQL injection.
"""

import atexit
import logging
import warnings
from typing import Any, Dict, List, Optional, Set

from dataguard.rules import Rule, RuleSet
from dataguard.report import ValidationResult
from dataguard.sql_dialects import (
    Dialect, DIALECTS, get_dialect, quote_id,
    check_to_condition, _MYSQL_PROTOCOL_DIALECTS,
)

logger = logging.getLogger(__name__)

# ─── Engine Cache ──────────────────────────────────────────────────

_engine_cache: Dict[int, Any] = set()  # track created engine ids for cleanup
_engines: Dict[int, Any] = {}  # id(engine) -> engine for atexit cleanup


def _cleanup_engines():
    """Dispose all cached SQLAlchemy engines on process exit."""
    for eid, eng in list(_engines.items()):
        try:
            eng.dispose()
            logger.debug("Disposed SQLAlchemy engine id=%d", eid)
        except Exception:
            pass
    _engines.clear()


atexit.register(_cleanup_engines)


def _get_sa_engine(connection):
    """Accept a SQLAlchemy Engine, connection string, or connection object.

    Caches created engines and registers them for cleanup on exit.
    """
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
        engine = create_engine(connection)
        # Cache for atexit cleanup
        eid = id(engine)
        _engines[eid] = engine
        return engine
    # Maybe it's a raw connection or something else with execute()
    if hasattr(connection, "execute") and hasattr(connection, "connect"):
        return connection
    raise TypeError(
        f"Expected SQLAlchemy Engine, connection string, or Engine-like object, "
        f"got {type(connection).__name__}"
    )


def _exec_query(engine, sql: str, params: Optional[dict] = None) -> List[dict]:
    """Execute a SQL query and return rows as dicts.

    Uses parameterized queries via SQLAlchemy text() bindings to prevent
    SQL injection. All user-provided values MUST be passed via params.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        stmt = text(sql)
        result = conn.execute(stmt, params or {})
        cols = result.keys()
        return [dict(zip(cols, row)) for row in result.fetchall()]


def _validate_identifier(name: str) -> None:
    """Validate a SQL identifier to prevent injection.

    Raises ValueError if the name contains suspicious characters.
    Only allows alphanumeric, underscores, dots (schema.table), and hyphens.
    """
    cleaned = name.replace(".", "").replace("_", "").replace("-", "")
    if not cleaned.isalnum():
        raise ValueError(f"Invalid SQL identifier: {name}")


def validate_sql(
    connection,
    table: str,
    rules: RuleSet,
    dialect: str = "mysql",
    schema: Optional[str] = None,
    sensitive_columns: Optional[Set[str]] = None,
) -> List[ValidationResult]:
    """Validate a SQL table against a RuleSet.

    Args:
        connection: SQLAlchemy Engine or connection string.
        table: Table name to validate.
        rules: RuleSet with validation rules.
        dialect: SQL dialect name (mysql, hive, flink, doris, selectdb).
        schema: Optional schema/database name.
        sensitive_columns: Set of column names containing PII — their
            sample_failures will be masked in the report.
    """
    d = get_dialect(dialect)
    engine = _get_sa_engine(connection)
    sensitive = sensitive_columns or set()

    # Validate identifiers early
    _validate_identifier(table)
    if schema:
        _validate_identifier(schema)

    # Build full table reference
    if schema:
        full_table = f"{quote_id(schema, d)}.{quote_id(table, d)}"
    else:
        full_table = quote_id(table, d)

    results = []
    for rule in rules.rules:
        result = _validate_sql_rule(engine, full_table, rule, d, sensitive)
        results.append(result)

    return results


def _base_check_name(check_name: str) -> str:
    """Extract the base check name without parameters.

    'in_range(0, 120)' -> 'in_range'
    'not_null' -> 'not_null'
    """
    return check_name.split("(")[0].strip()


def _mask_value(value: Any) -> str:
    """Mask a sensitive value for PII protection."""
    s = str(value)
    if len(s) <= 2:
        return "***"
    return s[0] + "***" + s[-1]


def _validate_sql_rule(
    engine, table: str, rule: Rule, dialect: Dialect,
    sensitive_columns: Set[str],
) -> ValidationResult:
    """Validate a single rule against a SQL table."""
    _validate_identifier(rule.column)
    col = quote_id(rule.column, dialect)
    base_name = _base_check_name(rule.check_name)

    # Get total row count
    total_rows = _exec_query(engine, f"SELECT COUNT(*) AS cnt FROM {table}")[0]["cnt"]

    # Get SQL params from the check function
    params = getattr(rule.check, "_sql_params", None)
    if params is None:
        # custom() check — can't translate to SQL
        logger.warning(
            "Check '%s' on column '%s' cannot be translated to SQL, skipping.",
            rule.check_name, rule.column,
        )
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

    # Generate SQL condition (now returns tuple with bind params)
    result = check_to_condition(base_name, params, col, dialect)

    if result is None and base_name == "unique":
        # Unique check — special aggregate query
        return _validate_unique_sql(
            engine, table, col, rule, total_rows, dialect, sensitive_columns,
        )

    if result is None:
        logger.warning(
            "Check '%s' cannot be translated to SQL, skipping.", rule.check_name,
        )
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

    condition, bind_params = result

    # Count passed rows — use parameterized query
    count_sql = (
        f"SELECT SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) AS passed "
        f"FROM {table}"
    )
    row = _exec_query(engine, count_sql, bind_params)[0]
    passed_rows = int(row["passed"] or 0)
    failed_rows = total_rows - passed_rows
    pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0

    # Get sample failures — also parameterized
    neg_condition = f"NOT ({condition})"
    sample_sql = (
        f"SELECT {col} AS val FROM {table} "
        f"WHERE {neg_condition} {dialect.limit_fmt.format(n=5)}"
    )
    try:
        sample_rows = _exec_query(engine, sample_sql, bind_params)
        raw_failures = [r["val"] for r in sample_rows[:5]]
        # Mask sensitive columns
        if rule.column in sensitive_columns:
            sample_failures: List[Any] = [_mask_value(v) for v in raw_failures]
        else:
            sample_failures = raw_failures
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
    engine, table: str, col: str, rule: Rule, total_rows: int,
    dialect: Dialect, sensitive_columns: Set[str],
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
        f"SELECT {col} AS val FROM {table} "
        f"GROUP BY {col} HAVING COUNT(*) > 1 "
        f"{dialect.limit_fmt.format(n=5)}"
    )
    try:
        sample_rows = _exec_query(engine, sample_sql)
        raw_failures = [r["val"] for r in sample_rows[:5]]
        if rule.column in sensitive_columns:
            sample_failures: List[Any] = [_mask_value(v) for v in raw_failures]
        else:
            sample_failures = raw_failures
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
    sensitive_columns: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Generate a data profile for a SQL table.

    Args:
        connection: SQLAlchemy Engine or connection string.
        table: Table name to validate.
        dialect: SQL dialect name.
        schema: Optional schema/database name.
        sensitive_columns: Set of column names containing PII —
            min/max/mean stats will be suppressed for these columns.
    """
    d = get_dialect(dialect)
    engine = _get_sa_engine(connection)
    sensitive = sensitive_columns or set()

    # Validate identifiers
    _validate_identifier(table)
    if schema:
        _validate_identifier(schema)

    if schema:
        full_table = f"{quote_id(schema, d)}.{quote_id(table, d)}"
    else:
        full_table = quote_id(table, d)

    # Get column names via LIMIT 1
    col_sql = f"SELECT * FROM {full_table} {d.limit_fmt.format(n=1)}"
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text(col_sql))
            columns = list(result.keys())
    except Exception as exc:
        logger.warning("Failed to get columns via SELECT LIMIT 1: %s", exc)
        return _profile_via_info_schema(engine, table, schema, d)

    # Get total rows
    total_rows = _exec_query(engine, f"SELECT COUNT(*) AS cnt FROM {full_table}")[0]["cnt"]

    profile = {}
    for col_name in columns:
        _validate_identifier(col_name)
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

        is_sensitive = col_name in sensitive

        # Try numeric stats — suppress for sensitive columns
        if is_sensitive:
            col_profile["dtype"] = "[REDACTED]"
            col_profile["min"] = None
            col_profile["max"] = None
            col_profile["mean"] = None
            col_profile["std"] = None
        else:
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
    logger.warning(
        "INFORMATION_SCHEMA profiling not fully implemented. "
        "Returning empty profile for table '%s'.", table,
    )
    warnings.warn(
        f"Could not profile table '{table}': SELECT LIMIT 1 failed and "
        f"INFORMATION_SCHEMA fallback is not implemented.",
        UserWarning,
        stacklevel=3,
    )
    return {}
