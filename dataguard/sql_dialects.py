"""
SQL dialect definitions for DataGuard.

Each dialect specifies how to generate SQL for different database engines.
All value parameters use SQLAlchemy :bindparam syntax to prevent SQL injection.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


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
    """Quote a SQL identifier (table/column name).

    Validates the identifier to prevent SQL injection before quoting.
    """
    # Validate: only alphanumeric, underscores, dots, hyphens
    cleaned = name.replace(".", "").replace("_", "").replace("-", "")
    if not cleaned.isalnum():
        raise ValueError(f"Invalid SQL identifier: {name}")
    q = dialect.quote
    # Handle schema.table format
    if "." in name:
        parts = name.split(".", 1)
        return f"{q}{parts[0]}{q}.{q}{parts[1]}{q}"
    return f"{q}{name}{q}"


# ─── SQL Condition Generation ─────────────────────────────────────

def check_to_condition(
    check_name: str, params: dict, col: str, dialect: Dialect
) -> Optional[Tuple[str, Dict[str, object]]]:
    """Translate a check into a SQL WHERE condition with parameterized values.

    Returns a tuple of (condition_sql, bind_params) where bind_params
    uses SQLAlchemy :param_name syntax, or None if the check cannot
    be translated to SQL.

    The condition_sql that a PASSING row satisfies.
    """
    if check_name == "not_null":
        return (f"{col} IS NOT NULL", {})

    if check_name == "unique":
        # Unique is handled separately with aggregate queries
        return None

    if check_name == "in_range":
        parts = []
        bind_params: Dict[str, object] = {}
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
        if dialect.name == "flink":
            # Flink SQL: REGEXP_EXTRACT returns NULL on no match.
            # Using it as a boolean is a best-effort approach.
            # For production Flink jobs, consider pre-processing or UDF.
            return (
                f"{col} IS NULL OR REGEXP_EXTRACT({col}, :dg_pattern, 0) IS NOT NULL",
                bind_params,
            )
        return (f"{col} IS NULL OR {col} {dialect.regex_op} :dg_pattern", bind_params)

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
        return (f"({col} IS NULL OR {dialect.length_fn}({col}) >= :dg_min_len)", bind_params)

    if check_name == "max_length":
        n = params.get("max_len", 0)
        bind_params = {"dg_max_len": n}
        return (f"({col} IS NULL OR {dialect.length_fn}({col}) <= :dg_max_len)", bind_params)

    # Unknown / custom checks can't be translated
    return None
