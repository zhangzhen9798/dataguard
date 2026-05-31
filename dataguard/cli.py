"""
CLI entry point for dqguard.
"""

import argparse
import json
import sys

import pandas as pd

from dataguard.core import DataGuard
from dataguard.rules import RuleSet


def _load_rules(path: str) -> dict:
    """Load rule config from JSON/YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith((".yml", ".yaml")):
            try:
                import yaml
                return yaml.safe_load(f)
            except ImportError:
                print("Error: PyYAML required for YAML config. pip install pyyaml", file=sys.stderr)
                sys.exit(1)
        return json.load(f)


def _load_data(path: str) -> pd.DataFrame:
    """Load data from CSV/JSON/Parquet."""
    if path.endswith(".csv"):
        return pd.read_csv(path)
    elif path.endswith(".json"):
        return pd.read_json(path)
    elif path.endswith(".parquet"):
        return pd.read_parquet(path)
    else:
        # default to CSV
        return pd.read_csv(path)


def cmd_validate(args):
    """Run validation against a dataset."""
    df = _load_data(args.data)
    config = _load_rules(args.rules)
    rules = RuleSet.from_dict(config)

    report = DataGuard(df).validate(rules)
    print(report.summary())

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report.to_json())
        print(f"\nJSON report saved to {args.output}")

    if not report.is_valid:
        sys.exit(1)


def cmd_profile(args):
    """Profile a dataset."""
    df = _load_data(args.data)
    profile = DataGuard(df).profile()

    if args.json:
        print(json.dumps(profile, indent=2, default=str))
    else:
        for col, stats in profile.items():
            null_pct = stats.get("null_rate", 0)
            print(f"  {col}: {stats['distinct_count']} distinct, {null_pct:.0%} nulls, dtype={stats['dtype']}")


def main():
    parser = argparse.ArgumentParser(
        prog="dqguard",
        description="Data quality validation from the command line",
    )
    sub = parser.add_subparsers(dest="command")

    # validate
    p_val = sub.add_parser("validate", help="Validate a dataset against rules")
    p_val.add_argument("data", help="Path to data file (csv/json/parquet)")
    p_val.add_argument("--rules", required=True, help="Path to rule config (json/yaml)")
    p_val.add_argument("--output", "-o", help="Save JSON report to file")
    p_val.set_defaults(func=cmd_validate)

    # profile
    p_prof = sub.add_parser("profile", help="Profile a dataset")
    p_prof.add_argument("data", help="Path to data file (csv/json/parquet)")
    p_prof.add_argument("--json", action="store_true", help="Output as JSON")
    p_prof.set_defaults(func=cmd_profile)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
