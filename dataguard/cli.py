"""
CLI entry point for dqguard.

Security notes:
- Database connection strings can be provided via the DQGUARD_DB_URL
  environment variable instead of --sql to avoid credential exposure
  in shell history and process listings.
- Sensitive columns can be specified via --sensitive to mask PII
  in validation reports.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from typing import Any

import pandas as pd

from dataguard.core import DataGuard
from dataguard.rules import RuleSet


def _load_rules(path: str) -> dict[str, Any]:
    """Load rule config from JSON/YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith((".yml", ".yaml")):
            try:
                import yaml

                return yaml.safe_load(f)  # type: ignore[no-any-return]
            except ImportError:
                print(
                    "Error: PyYAML required for YAML config. pip install pyyaml",
                    file=sys.stderr,
                )
                sys.exit(1)
        return json.load(f)  # type: ignore[no-any-return]


def _load_data(path: str) -> pd.DataFrame:
    """Load data from CSV/JSON/Parquet."""
    if path.endswith(".csv"):
        return pd.read_csv(path)
    elif path.endswith(".json"):
        return pd.read_json(path)
    elif path.endswith(".parquet"):
        return pd.read_parquet(path)
    else:
        return pd.read_csv(path)


def _get_sensitive_columns(args: argparse.Namespace) -> set[str]:
    """Parse sensitive columns from comma-separated string."""
    if not args.sensitive:
        return set()
    return set(s.strip() for s in args.sensitive.split(",") if s.strip())


def _write_report_secure(path: str, content: str) -> None:
    """Write report file with restricted permissions (owner-only read/write).

    On Windows, this is best-effort since Unix permissions don't fully apply.
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    # Restrict file permissions to owner-only (Unix)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except (OSError, AttributeError):
        pass  # Best-effort on Windows


def cmd_validate(args: argparse.Namespace) -> None:
    """Run validation against a dataset."""
    rules = RuleSet.from_dict(_load_rules(args.rules))
    sensitive = _get_sensitive_columns(args)

    if args.sql or os.environ.get("DQGUARD_DB_URL"):
        try:
            from sqlalchemy import create_engine  # noqa: F401
        except ImportError:
            print(
                "Error: SQLAlchemy required for SQL mode. pip install dqguard[sql]",
                file=sys.stderr,
            )
            sys.exit(1)

        connection_str = args.sql or os.environ.get("DQGUARD_DB_URL", "")
        if not connection_str:
            print(
                "Error: No SQL connection string provided. "
                "Use --sql or set DQGUARD_DB_URL",
                file=sys.stderr,
            )
            sys.exit(1)

        if not args.table:
            print(
                "Error: --table is required when using SQL mode",
                file=sys.stderr,
            )
            sys.exit(1)

        dialect = args.dialect or "mysql"
        guardian = DataGuard.from_sql(
            connection_str,
            args.table,
            dialect=dialect,
            schema=args.schema,
            sensitive_columns=sensitive,
        )
    else:
        if not args.data:
            print(
                "Error: either --sql/--table or a data file path is required",
                file=sys.stderr,
            )
            sys.exit(1)
        df = _load_data(args.data)
        guardian = DataGuard(df, sensitive_columns=sensitive)

    report = guardian.validate(rules)
    print(report.summary())

    if args.output:
        _write_report_secure(args.output, report.to_json())
        print(f"\nJSON report saved to {args.output}")

    if not report.is_valid:
        sys.exit(1)


def cmd_profile(args: argparse.Namespace) -> None:
    """Profile a dataset."""
    sensitive = _get_sensitive_columns(args)

    if args.sql or os.environ.get("DQGUARD_DB_URL"):
        try:
            from sqlalchemy import create_engine  # noqa: F401
        except ImportError:
            print(
                "Error: SQLAlchemy required for SQL mode. pip install dqguard[sql]",
                file=sys.stderr,
            )
            sys.exit(1)

        connection_str = args.sql or os.environ.get("DQGUARD_DB_URL", "")
        if not connection_str:
            print(
                "Error: No SQL connection string provided. "
                "Use --sql or set DQGUARD_DB_URL",
                file=sys.stderr,
            )
            sys.exit(1)

        if not args.table:
            print(
                "Error: --table is required when using SQL mode",
                file=sys.stderr,
            )
            sys.exit(1)

        dialect = args.dialect or "mysql"
        profile = DataGuard.from_sql(
            connection_str,
            args.table,
            dialect=dialect,
            schema=args.schema,
            sensitive_columns=sensitive,
        ).profile()
    else:
        if not args.data:
            print(
                "Error: either --sql/--table or a data file path is required",
                file=sys.stderr,
            )
            sys.exit(1)
        df = _load_data(args.data)
        profile = DataGuard(df, sensitive_columns=sensitive).profile()

    if args.json:
        print(json.dumps(profile, indent=2, default=str))
    else:
        for col, stats in profile.items():
            null_pct = stats.get("null_rate", 0)
            dtype = stats.get("dtype", "unknown")
            print(
                f"  {col}: {stats.get('distinct_count', '?')} distinct, "
                f"{null_pct:.0%} nulls, dtype={dtype}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dqguard",
        description="Data quality validation from the command line",
    )
    sub = parser.add_subparsers(dest="command")

    # Shared SQL arguments
    def add_common_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--sql",
            help="SQL connection string. For security, prefer the DQGUARD_DB_URL "
            "environment variable instead of passing credentials on the command line.",
        )
        p.add_argument("--table", help="SQL table name (required with --sql)")
        p.add_argument(
            "--dialect",
            help="SQL dialect: mysql, hive, flink, doris, selectdb (default: mysql)",
        )
        p.add_argument("--schema", help="SQL schema/database name")
        p.add_argument(
            "--sensitive",
            help="Comma-separated list of sensitive column names for PII masking "
            "(e.g. --sensitive email,phone,ssn)",
        )

    # validate
    p_val = sub.add_parser("validate", help="Validate a dataset against rules")
    p_val.add_argument("data", nargs="?", help="Path to data file (csv/json/parquet)")
    p_val.add_argument("--rules", required=True, help="Path to rule config (json/yaml)")
    p_val.add_argument(
        "--output",
        "-o",
        help="Save JSON report to file (written with restricted permissions)",
    )
    add_common_args(p_val)
    p_val.set_defaults(func=cmd_validate)

    # profile
    p_prof = sub.add_parser("profile", help="Profile a dataset")
    p_prof.add_argument("data", nargs="?", help="Path to data file (csv/json/parquet)")
    p_prof.add_argument("--json", action="store_true", help="Output as JSON")
    add_common_args(p_prof)
    p_prof.set_defaults(func=cmd_profile)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
