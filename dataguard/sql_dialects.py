"""
SQL dialect definitions for DataGuard.

Each dialect specifies how to generate SQL for different database engines.
All value parameters use SQLAlchemy :bindparam syntax to prevent SQL injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Dialect:
    """SQL dialect configuration."""

    name: str
    # Regex operator: "REGEXP" (MySQL/Doris), "RLIKE" (Hive),
    #   "REGEXP_PATTERN" (Flink 1.14+), "REGEXP_EXTRACT" (Flink <1.14)
    regex_op: str = "REGEXP"
    # Function that accepts a literal pattern (no bind param needed):
    #   empty → use  col {regex_op} :param   (MySQL/Hive/Doris)
    #   non-empty → use  func(:param)             (Flink 1.14+)
    regex_pattern_fn: str = ""
    length_fn: str = "CHAR_LENGTH"
    # SQL fragment that returns TRUE when the column value is a valid date
    #   (using a bind parameter :dg_date_val for the sample value).
    #   MySQL/Doris: "STR_TO_DATE({col}, :dg_date_fmt) IS NOT NULL"
    #   Hive:      "to_date(from_unixtime(unix_timestamp({col}, :dg_date_fmt))) IS NOT NULL"
    #   Flink:      "TO_DATE({col}, :dg_date_fmt) IS NOT NULL"
    date_test_sql: str = "STR_TO_DATE({col}, :dg_date_fmt) IS NOT NULL"
    quote: str = "`"
    supports_filter: bool = True
    limit_fmt: str = "LIMIT {n}"


# Built-in dialect definitions
DIALECTS: dict[str, Dialect] = {
    "mysql": Dialect(
        name="mysql",
        regex_op="REGEXP",
        length_fn="CHAR_LENGTH",
        date_test_sql="STR_TO_DATE({col}, :dg_date_fmt) IS NOT NULL",
        quote="`",
    ),
    "hive": Dialect(
        name="hive",
        regex_op="RLIKE",
        length_fn="LENGTH",
        date_test_sql=(
            "to_date(from_unixtime("
            "  unix_timestamp({col}, :dg_date_fmt)"
            ")) IS NOT NULL"
        ),
        quote="`",
    ),
    "flink": Dialect(
        name="flink",
        # Will be upgraded to "REGEXP_PATTERN" when Flink >= 1.14 is detected
        regex_op="REGEXP_EXTRACT",
        regex_pattern_fn="",
        length_fn="CHAR_LENGTH",
        date_test_sql="TO_DATE({col}, :dg_date_fmt) IS NOT NULL",
        quote="`",
    ),
    "doris": Dialect(
        name="doris",
        regex_op="REGEXP",
        length_fn="CHAR_LENGTH",
        date_test_sql="STR_TO_DATE({col}, :dg_date_fmt) IS NOT NULL",
        quote="`",
    ),
    "selectdb": Dialect(
        name="selectdb",
        regex_op="REGEXP",
        length_fn="CHAR_LENGTH",
        date_test_sql="STR_TO_DATE({col}, :dg_date_fmt) IS NOT NULL",
        quote="`",
    ),
}


def get_dialect(name: str) -> Dialect:
    """Get a dialect by name (case-insensitive)."""
    key = name.lower().strip()
    if key not in DIALECTS:
        supported = ", ".join(DIALECTS.keys())
        raise ValueError(f"Unknown dialect '{name}'. Supported: {supported}")
    return DIALECTS[key]


def quote_id(name: str, dialect: Dialect) -> str:
    """Quote a SQL identifier (table/column name).

    Validates the identifier to prevent SQL injection before quoting.
    """
    from dataguard.utils import validate_identifier

    validate_identifier(name)

    q = dialect.quote
    # Handle schema.table format
    if "." in name:
        parts = name.split(".", 1)
        return f"{q}{parts[0]}{q}.{q}{parts[1]}{q}"
    return f"{q}{name}{q}"


# ─── SQL Condition Generation ─────────────────────────────────────

# Numeric detection regex — good enough for most databases.
# Allows optional sign, optional integer part, required digit after dot.
_RE_NUMERIC = r"^[+-]?[0-9]*\.?[0-9]+$"


def check_to_condition(
    check_name: str, params: dict[str, Any], col: str, dialect: Dialect
) -> tuple[str, dict[str, object]] | None:
    """Translate a check into a SQL WHERE condition with parameterized values.

    Returns a tuple of (condition_sql, bind_params) where bind_params
    uses SQLAlchemy :param_name syntax, or None if the check cannot
    be translated to SQL.

    The condition_sql describes rows that PASS the check.
    """
    # ── Row-level checks ──────────────────────────────────────────

    if check_name == "not_null":
        return (f"{col} IS NOT NULL", {})

    if check_name == "unique":
        # Unique is handled separately with aggregate queries
        return None

    if check_name == "in_range":
        parts: list[str] = []
        bind_params: dict[str, object] = {}
        min_val = params.get("min_val")
        max_val = params.get("max_val")
        if min_val is not None:
            bind_params["dg_min_val"] = min_val
            parts.append(f"{col} >= :dg_min_val")
        if max_val is not None:
            bind_params["dg_max_val"] = max_val
            parts.append(f"{col} <= :dg_max_val")
        # Nulls pass range checks (use not_null separately)
        return ("(" + " AND ".join(parts) + f" OR {col} IS NULL)", bind_params)

    if check_name == "regex_match":
        pattern = params.get("pattern", "")
        bind_params = {"dg_pattern": pattern}
        return _regex_condition(col, dialect, bind_params)

    if check_name == "in_set":
        values = params.get("allowed_values", [])
        if not values:
            return ("1=0", {})  # empty set = nothing passes
        bind_params = {f"dg_val_{i}": v for i, v in enumerate(values)}
        placeholders = ", ".join(f":dg_val_{i}" for i in range(len(values)))
        return (f"({col} IS NULL OR {col} IN ({placeholders}))", bind_params)

    if check_name == "min_length":
        n = params.get("min_len", 0)
        bind_params = {"dg_min_len": n}
        return (
            f"({col} IS NULL OR {dialect.length_fn}({col}) >= :dg_min_len)",
            bind_params,
        )

    if check_name == "max_length":
        n = params.get("max_len", 0)
        bind_params = {"dg_max_len": n}
        return (
            f"({col} IS NULL OR {dialect.length_fn}({col}) <= :dg_max_len)",
            bind_params,
        )

    # ── New checks (v0.6) ──────────────────────────────────────

    if check_name == "is_numeric":
        # Use CAST to REAL (works on MySQL, SQLite, Hive, Doris, Flink)
        # NULLs pass; non-numeric strings become NULL after CAST → IS NOT NULL fails
        return (
            f"({col} IS NULL OR CAST({col} AS REAL) IS NOT NULL)",
            {},
        )

    if check_name == "is_email":
        pattern = params.get(
            "pattern", r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
        )
        bind_params = {"dg_pattern": pattern}
        return _regex_condition(col, dialect, bind_params)

    if check_name == "is_date":
        fmt = params.get("format_str")
        if not fmt:
            # No format string → cannot translate safely
            return None
        # Convert Python strptime format to the SQL dialect's format placeholder
        sql = dialect.date_test_sql.format(col=col)
        return (sql, {"dg_date_fmt": _pyfmt_to_sql(fmt, dialect)})

    if check_name == "not_empty_string":
        # TRIM() removes whitespace; NULLs pass
        return (f"({col} IS NULL OR TRIM({col}) != '')", {})

    # ── Column-level checks (handled by the engine, not here) ─────

    if check_name in {"max_value", "min_value"}:
        # Aggregation queries are built directly in sql_engine.py
        return None

    # Unknown / custom checks can't be translated
    return None


# ─── Helpers ──────────────────────────────────────────────────────


def _regex_condition(
    col: str, dialect: Dialect, bind_params: dict[str, object]
) -> tuple[str, dict[str, object]]:
    """Build a SQL condition for regex matching, dialect-aware."""
    if dialect.regex_pattern_fn:
        # Flink 1.14+:  REGEXP_PATTERN(:dg_pattern)
        fn = dialect.regex_pattern_fn
        return (
            f"{col} IS NULL OR {fn}({col}, :dg_pattern)",
            bind_params,
        )
    if dialect.name == "flink":
        # Flink < 1.14 workaround: REGEXP_EXTRACT returns NULL on no match
        return (
            f"{col} IS NULL OR REGEXP_EXTRACT({col}, :dg_pattern, 0) IS NOT NULL",
            bind_params,
        )
    # MySQL / Hive / Doris / SelectDB
    return (
        f"{col} IS NULL OR {col} {dialect.regex_op} :dg_pattern",
        bind_params,
    )


def _pyfmt_to_sql(fmt: str, dialect: Dialect) -> str:
    """Convert a Python strptime format string to a SQL dialect format string.

    This is a *best-effort* conversion; exotic format codes are left
    as-is (most databases understand ``%Y-%m-%d`` style codes).
    """
    # Fast path: already a SQL-style format
    if "%" not in fmt:
        return fmt
    # Common mappings
    mapping = {
        "%Y": "%Y",
        "%y": "%y",
        "%m": "%m",
        "%d": "%d",
        "%H": "%H",
        "%M": "%M",
        "%S": "%S",
    }
    result = fmt
    for py, sql in mapping.items():
        result = result.replace(py, sql)
    return result
