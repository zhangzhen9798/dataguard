"""
SQL-based validation engine for DataGuard.

Supports MySQL, Hive, Flink SQL, Doris, and SelectDB via SQLAlchemy.
Uses parameterized queries to prevent SQL injection.
"""

from __future__ import annotations

import atexit
import logging
import re
import warnings
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from dataguard.rules import Rule, RuleSet
from dataguard.report import ValidationResult
from dataguard.sql_dialects import (
    Dialect,
    get_dialect,
    quote_id,
    check_to_condition,
)
from dataguard.utils import CheckSpec, mask_value, base_check_name, validate_identifier

logger = logging.getLogger(__name__)

# ─── Engine Management ─────────────────────────────────────────

_engines: dict[int, Engine] = {}  # id(engine) -> engine for atexit cleanup


def _cleanup_engines() -> None:
    """Dispose all cached SQLAlchemy engines on process exit."""
    for _, eng in list(_engines.items()):
        try:
            eng.dispose()
            logger.debug("Disposed SQLAlchemy engine id=%d", id(eng))
        except Exception:
            pass
    _engines.clear()


atexit.register(_cleanup_engines)


def _get_sa_engine(connection: Any) -> Engine:
    """Accept a SQLAlchemy Engine, connection string, or connection object.

    Caches created engines and registers them for cleanup on exit.
    """
    try:
        from sqlalchemy import create_engine  # noqa: PLC0415
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
        _engines[id(engine)] = engine
        return engine
    # Maybe it's a raw connection or something else with execute()
    if hasattr(connection, "execute") and hasattr(connection, "connect"):
        return connection  # type: ignore[no-any-return]
    raise TypeError(
        f"Expected SQLAlchemy Engine, connection string, or Engine-like object, "
        f"got {type(connection).__name__}"
    )


def _exec_query(
    engine: Engine, sql: str, params: dict[str, object] | None = None
) -> list[dict[str, Any]]:
    """Execute a SQL query and return rows as dicts.

    Uses parameterized queries via SQLAlchemy text() bindings to prevent
    SQL injection. All user-provided values MUST be passed via params.
    """
    with engine.connect() as conn:
        stmt = text(sql)
        result = conn.execute(stmt, params or {})
        cols = result.keys()
        return [dict(zip(cols, row)) for row in result.fetchall()]


def _detect_flink_version(engine: Engine) -> tuple[int, int] | None:
    """Detect Flink version from the engine.

    Returns (major, minor) or None if detection fails.
    """
    try:
        row = _exec_query(engine, "SELECT VERSION() AS v")[0]
        version_str = str(row.get("v", ""))
        # Parse "1.14.0" or "1.16.0"
        m = re.search(r"(\d+)\.(\d+)", version_str)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception as exc:
        logger.warning("Could not detect Flink version: %s", exc)
    return None


def _upgrade_flink_dialect(engine: Engine, dialect: Dialect) -> Dialect:
    """Upgrade Flink dialect to use REGEXP_PATTERN if version >= 1.14."""
    if dialect.name != "flink":
        return dialect
    version = _detect_flink_version(engine)
    if version and version >= (1, 14):
        logger.info(
            "Flink %s detected — upgrading regex_op to REGEXP_PATTERN",
            ".".join(str(v) for v in version),
        )
        # Return a shallow copy with upgraded fields
        from dataclasses import replace  # noqa: PLC0415

        return replace(
            dialect,
            regex_op="REGEXP_PATTERN",
            regex_pattern_fn="REGEXP_PATTERN",
        )
    # Flink < 1.14: keep REGEXP_EXTRACT workaround, emit warning
    warnings.warn(
        "Flink version < 1.14 detected (or unknown). "
        "regex_match uses REGEXP_EXTRACT workaround and may be unreliable. "
        "Consider upgrading Flink or using a custom check.",
        UserWarning,
        stacklevel=4,
    )
    return dialect


# ─── Public API ──────────────────────────────────────────────────


def validate_sql(
    connection,
    table: str,
    rules: RuleSet,
    dialect: str = "mysql",
    schema: str | None = None,
    sensitive_columns: set[str] | None = None,
) -> list[ValidationResult]:
    """Validate a SQL table against a RuleSet.

    Args:
        connection: SQLAlchemy Engine or connection string.
        table: Table name to validate.
        rules: RuleSet with validation rules.
        dialect: SQL dialect name (mysql, hive, flink, doris, selectdb).
        schema: Optional schema/database name.
        sensitive_columns: Set of column names containing PII —
            their sample_failures will be masked in the report.
    """
    d = get_dialect(dialect)
    engine = _get_sa_engine(connection)
    sensitive = sensitive_columns or set()

    # Validate identifiers early
    validate_identifier(table)
    if schema:
        validate_identifier(schema)

    # Upgrade Flink dialect if needed
    d = _upgrade_flink_dialect(engine, d)

    # Build full table reference
    if schema:
        full_table = f"{quote_id(schema, d)}.{quote_id(table, d)}"
    else:
        full_table = quote_id(table, d)

    # Cache total_rows — only query once per validate call
    total_rows = _exec_query(engine, f"SELECT COUNT(*) AS cnt FROM {full_table}")[0][
        "cnt"
    ]

    results: list[ValidationResult] = []
    for rule in rules.rules:
        result = _validate_sql_rule(engine, full_table, rule, total_rows, d, sensitive)
        results.append(result)

    return results


def _validate_sql_rule(
    engine: Engine,
    table: str,
    rule: Rule,
    total_rows: int,
    dialect: Dialect,
    sensitive_columns: set[str],
) -> ValidationResult:
    """Validate a single rule against a SQL table."""
    validate_identifier(rule.column)
    col = quote_id(rule.column, dialect)
    base_name = base_check_name(rule.check_name)
    spec: CheckSpec = rule.check

    # Get SQL params from the CheckSpec
    sql_params = spec.sql_params

    if sql_params is None:
        # custom() check — can't translate to SQL, mark as FAILED
        logger.warning(
            "Check '%s' on column '%s' cannot be translated to SQL, skipping.",
            rule.check_name,
            rule.column,
        )
        warnings.warn(
            f"Check '{rule.check_name}' on column '{rule.column}' cannot be "
            f"translated to SQL and will be skipped (treated as failed).",
            UserWarning,
            stacklevel=2,
        )
        return ValidationResult(
            column=rule.column,
            check_name=rule.check_name,
            passed=False,  # Skipped = not validated, treated as failed
            total_rows=total_rows,
            passed_rows=0,
            failed_rows=total_rows,
            pass_rate=0.0,
            threshold=rule.threshold,
            sample_failures=["[SKIPPED] Custom check not translatable to SQL"],
        )

    # ── Column-level checks: unique, max_value, min_value ──────
    if spec.is_column_level or base_name in {"unique", "max_value", "min_value"}:
        if base_name == "unique":
            return _validate_unique_sql(
                engine,
                table,
                col,
                rule,
                total_rows,
                dialect,
                sensitive_columns,
            )
        if base_name == "max_value":
            return _validate_max_value_sql(
                engine,
                table,
                col,
                rule,
                total_rows,
                dialect,
                sensitive_columns,
            )
        if base_name == "min_value":
            return _validate_min_value_sql(
                engine,
                table,
                col,
                rule,
                total_rows,
                dialect,
                sensitive_columns,
            )

    # ── Row-level checks ──────────────────────────────────────
    result = check_to_condition(base_name, sql_params, col, dialect)

    if result is None:
        logger.warning(
            "Check '%s' cannot be translated to SQL, skipping.",
            rule.check_name,
        )
        warnings.warn(
            f"Check '{rule.check_name}' cannot be translated to SQL, skipping.",
            UserWarning,
            stacklevel=2,
        )
        return ValidationResult(
            column=rule.column,
            check_name=rule.check_name,
            passed=False,
            total_rows=total_rows,
            passed_rows=0,
            failed_rows=total_rows,
            pass_rate=0.0,
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
            sample_failures: list[Any] = [mask_value(v) for v in raw_failures]
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
    engine: Engine,
    table: str,
    col: str,
    rule: Rule,
    total_rows: int,
    dialect: Dialect,
    sensitive_columns: set[str],
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
            sample_failures: list[Any] = [mask_value(v) for v in raw_failures]
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


def _validate_max_value_sql(
    engine: Engine,
    table: str,
    col: str,
    rule: Rule,
    total_rows: int,
    dialect: Dialect,
    sensitive_columns: set[str],
) -> ValidationResult:
    """Handle max_value column-level check with SQL aggregate."""
    params = rule.check.sql_params or {}
    max_val = params.get("max_val")

    # Query actual MAX(col)
    max_sql = f"SELECT MAX({col}) AS max_val FROM {table}"
    row = _exec_query(engine, max_sql)[0]
    actual_max = row["max_val"]

    # Query count of rows exceeding max_val
    if actual_max is None:
        failed_rows = total_rows
        passed_rows = 0
        pass_rate = 0.0
    else:
        failed_rows = total_rows - int(
            _exec_query(
                engine,
                f"SELECT SUM(CASE WHEN {col} <= :dv THEN 1 ELSE 0 END) AS passed FROM {table}",
                {"dv": max_val},
            )[0]["passed"]
            or 0
        )
        passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0

    # Sample failures: rows where col > max_val
    sample_sql = (
        f"SELECT {col} AS val FROM {table} "
        f"WHERE {col} > :dv "
        f"{dialect.limit_fmt.format(n=5)}"
    )
    try:
        sample_rows = _exec_query(engine, sample_sql, {"dv": max_val})
        raw_failures = [r["val"] for r in sample_rows[:5]]
        if rule.column in sensitive_columns:
            sample_failures: list[Any] = [mask_value(v) for v in raw_failures]
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


def _validate_min_value_sql(
    engine: Engine,
    table: str,
    col: str,
    rule: Rule,
    total_rows: int,
    dialect: Dialect,
    sensitive_columns: set[str],
) -> ValidationResult:
    """Handle min_value column-level check with SQL aggregate."""
    params = rule.check.sql_params or {}
    min_val = params.get("min_val")

    # Query actual MIN(col)
    min_sql = f"SELECT MIN({col}) AS min_val FROM {table}"
    row = _exec_query(engine, min_sql)[0]
    actual_min = row["min_val"]

    # Query count of rows below min_val
    if actual_min is None:
        failed_rows = total_rows
        passed_rows = 0
        pass_rate = 0.0
    else:
        failed_rows = total_rows - int(
            _exec_query(
                engine,
                f"SELECT SUM(CASE WHEN {col} >= :dv THEN 1 ELSE 0 END) AS passed FROM {table}",
                {"dv": min_val},
            )[0]["passed"]
            or 0
        )
        passed_rows = total_rows - failed_rows
        pass_rate = passed_rows / total_rows if total_rows > 0 else 1.0

    # Sample failures: rows where col < min_val
    sample_sql = (
        f"SELECT {col} AS val FROM {table} "
        f"WHERE {col} < :dv "
        f"{dialect.limit_fmt.format(n=5)}"
    )
    try:
        sample_rows = _exec_query(engine, sample_sql, {"dv": min_val})
        raw_failures = [r["val"] for r in sample_rows[:5]]
        if rule.column in sensitive_columns:
            sample_failures: list[Any] = [mask_value(v) for v in raw_failures]
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


# ─── Profiling ──────────────────────────────────────────────────


def profile_sql(
    connection,
    table: str,
    dialect: str = "mysql",
    schema: str | None = None,
    sensitive_columns: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
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
    validate_identifier(table)
    if schema:
        validate_identifier(schema)

    if schema:
        full_table = f"{quote_id(schema, d)}.{quote_id(table, d)}"
    else:
        full_table = quote_id(table, d)

    # Get column names via LIMIT 1
    col_sql = f"SELECT * FROM {full_table} {d.limit_fmt.format(n=1)}"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(col_sql))
            columns = list(result.keys())
    except Exception as exc:
        logger.warning("Failed to get columns via SELECT LIMIT 1: %s", exc)
        return _profile_via_info_schema(engine, table, schema, d)

    # Get total rows once
    total_rows = _exec_query(engine, f"SELECT COUNT(*) AS cnt FROM {full_table}")[0][
        "cnt"
    ]

    profile: dict[str, dict[str, Any]] = {}

    # Build a single merged query for null_count + distinct_count across all columns
    # to eliminate N per-column round-trips
    stats_parts: list[str] = []
    for col_name in columns:
        validate_identifier(col_name)
        qcol = quote_id(col_name, d)
        stats_parts.append(
            f"SUM(CASE WHEN {qcol} IS NULL THEN 1 ELSE 0 END) AS null_count_{col_name}"
        )
        stats_parts.append(f"COUNT(DISTINCT {qcol}) AS distinct_count_{col_name}")
    merged_stats_sql = f"SELECT {', '.join(stats_parts)} FROM {full_table}"
    merged_stats = _exec_query(engine, merged_stats_sql)[0]

    for col_name in columns:
        qcol = quote_id(col_name, d)
        col_profile: dict[str, Any] = {
            "total_rows": total_rows,
        }

        # Read from merged stats query
        null_count = int(merged_stats.get(f"null_count_{col_name}", 0) or 0)
        distinct_count = int(merged_stats.get(f"distinct_count_{col_name}", 0) or 0)

        col_profile["null_count"] = null_count
        col_profile["null_rate"] = null_count / total_rows if total_rows > 0 else 0.0
        col_profile["distinct_count"] = distinct_count

        is_sensitive = col_name in sensitive

        # Numeric stats — suppress for sensitive columns
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
                    f"MIN({qcol}) AS min_val, MAX({qcol}) AS max_val, "
                    f"AVG({qcol}) AS mean_val "
                    f"FROM {full_table} "
                    f"WHERE {qcol} IS NOT NULL"
                )
                num_row = _exec_query(engine, num_sql)[0]
                if num_row["min_val"] is not None:
                    col_profile["dtype"] = "numeric"
                    col_profile["min"] = float(num_row["min_val"])
                    col_profile["max"] = float(num_row["max_val"])
                    col_profile["mean"] = float(num_row["mean_val"])
                    try:
                        std_sql = f"SELECT STDDEV({qcol}) AS std_val FROM {full_table} WHERE {qcol} IS NOT NULL"
                        std_row = _exec_query(engine, std_sql)[0]
                        col_profile["std"] = (
                            float(std_row["std_val"])
                            if std_row["std_val"] is not None
                            else None
                        )
                    except Exception:
                        col_profile["std"] = None
                else:
                    col_profile["dtype"] = "string"
            except Exception:
                col_profile["dtype"] = "string"

        profile[col_name] = col_profile

    return profile


def _profile_via_info_schema(
    engine: Engine,
    table: str,
    schema: str | None,
    dialect: Dialect,
) -> dict[str, dict[str, Any]]:
    """Fallback profiling using INFORMATION_SCHEMA.

    Retrieves column names and types when SELECT LIMIT 1 fails.
    Now returns actual column metadata instead of empty dict.
    """
    logger.warning(
        "Falling back to INFORMATION_SCHEMA for table '%s'. "
        "Only column metadata will be available.",
        table,
    )
    warnings.warn(
        f"Could not profile table '{table}' via SELECT: "
        f"falling back to INFORMATION_SCHEMA for column metadata only.",
        UserWarning,
        stacklevel=3,
    )

    profile: dict[str, dict[str, Any]] = {}
    try:
        db_name = schema or "default"
        info_sql = (
            "SELECT COLUMN_NAME, DATA_TYPE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = :table_schema AND TABLE_NAME = :table_name"
        )
        rows = _exec_query(
            engine,
            info_sql,
            {
                "table_schema": db_name,
                "table_name": table,
            },
        )
        for row in rows:
            col_name = row["COLUMN_NAME"]
            profile[col_name] = {
                "dtype": row.get("DATA_TYPE", "unknown"),
                "total_rows": 0,
                "null_count": 0,
                "null_rate": 0.0,
                "distinct_count": 0,
            }
    except Exception as exc:
        logger.warning("INFORMATION_SCHEMA fallback also failed: %s", exc)

    return profile
