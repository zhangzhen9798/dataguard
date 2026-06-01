"""
SQL dialect definitions for DataGuard.

Each dialect specifies how to generate SQL for different database engines.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Dialect:
    """SQL dialect configuration."""
    name: str
    regex_op: str = "REGEXP"
    length_fn: str = "CHAR_LENGTH"
    quote: str = "`"
    # For Hive/Flink which use different null-coalesce
    supports_filter: bool = True
    # LIMIT syntax
    limit_fmt: str = "LIMIT {n}"


# Built-in dialect definitions
DIALECTS: Dict[str, Dialect] = {
    "mysql": Dialect(
        name="mysql",
        regex_op="REGEXP",
        length_fn="CHAR_LENGTH",
        quote="`",
    ),
    "hive": Dialect(
        name="hive",
        regex_op="RLIKE",
        length_fn="LENGTH",
        quote="`",
    ),
    "flink": Dialect(
        name="flink",
        regex_op="REGEXP_EXTRACT",
        length_fn="CHAR_LENGTH",
        quote="`",
    ),
    "doris": Dialect(
        name="doris",
        regex_op="REGEXP",
        length_fn="CHAR_LENGTH",
        quote="`",
    ),
    "selectdb": Dialect(
        name="selectdb",
        regex_op="REGEXP",
        length_fn="CHAR_LENGTH",
        quote="`",
    ),
}

# Doris and SelectDB speak MySQL protocol
_MYSQL_PROTOCOL_DIALECTS = {"doris", "selectdb"}


def get_dialect(name: str) -> Dialect:
    """Get a dialect by name (case-insensitive)."""
    key = name.lower().strip()
    if key not in DIALECTS:
        supported = ", ".join(DIALECTS.keys())
        raise ValueError(f"Unknown dialect '{name}'. Supported: {supported}")
    return DIALECTS[key]


def quote_id(name: str, dialect: Dialect) -> str:
    """Quote a SQL identifier (table/column name)."""
    # Basic validation to prevent injection
    if not name.replace(".", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid SQL identifier: {name}")
    q = dialect.quote
    # Handle schema.table format
    if "." in name:
        parts = name.split(".", 1)
        return f"{q}{parts[0]}{q}.{q}{parts[1]}{q}"
    return f"{q}{name}{q}"


def sql_value(val) -> str:
    """Convert a Python value to a SQL literal."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    # String — escape single quotes
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"


# ─── SQL Condition Generation ─────────────────────────────────────

def check_to_condition(check_name: str, params: dict, col: str, dialect: Dialect) -> str:
    """Translate a check into a SQL WHERE condition.

    Returns the condition that a PASSING row satisfies.
    """
    if check_name == "not_null":
        return f"{col} IS NOT NULL"

    if check_name == "unique":
        # Unique is handled separately with aggregate queries
        return None

    if check_name == "in_range":
        parts = []
        min_val = params.get("min_val")
        max_val = params.get("max_val")
        if min_val is not None:
            parts.append(f"{col} >= {sql_value(min_val)}")
        if max_val is not None:
            parts.append(f"{col} <= {sql_value(max_val)}")
        # Nulls pass range checks (use not_null separately)
        return "(" + " AND ".join(parts) + f" OR {col} IS NULL)"

    if check_name == "regex_match":
        pattern = params.get("pattern", "")
        if dialect.name == "flink":
            # Flink uses REGEXP_EXTRACT differently, fall back to LIKE for simple patterns
            return f"{col} IS NULL OR REGEXP_EXTRACT({col}, {sql_value(pattern)}, 0) IS NOT NULL"
        return f"{col} IS NULL OR {col} {dialect.regex_op} {sql_value(pattern)}"

    if check_name == "in_set":
        values = params.get("allowed_values", [])
        if not values:
            return "1=0"  # empty set = nothing passes
        vals_str = ", ".join(sql_value(v) for v in values)
        return f"({col} IS NULL OR {col} IN ({vals_str}))"

    if check_name == "min_length":
        n = params.get("min_len", 0)
        return f"({col} IS NULL OR {dialect.length_fn}({col}) >= {n})"

    if check_name == "max_length":
        n = params.get("max_len", 0)
        return f"({col} IS NULL OR {dialect.length_fn}({col}) <= {n})"

    # Unknown / custom checks can't be translated
    return None
