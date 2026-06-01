"""
Example: Config-driven Validation with RuleSet.from_dict()
"""

import pandas as pd
from dataguard import DataGuard, RuleSet


def main():
    df = pd.DataFrame({
        "name": ["Alice", "Bob", None, "Dana", "Eve"],
        "age": [25, 30, -5, 40, 150],
        "email": [
            "alice@example.com",
            "invalid-email",
            "charlie@example.com",
            "dana@example.com",
            "eve@example.com",
        ],
        "status": ["active", "active", "inactive", "active", "unknown"],
    })

    # Define rules as a dictionary — useful for YAML/JSON config files
    config = {
        "name": [{"check": "not_null"}],
        "age": [
            {"check": "not_null"},
            {"check": "in_range", "params": {"min_val": 0, "max_val": 120}},
        ],
        "email": [
            {"check": "regex_match", "params": {"pattern": r"^[\w.-]+@[\w.-]+\.\w+$"}},
        ],
        "status": [
            {"check": "in_set", "params": {"allowed_values": ["active", "inactive"]}},
        ],
    }

    rules = RuleSet.from_dict(config)
    report = DataGuard(df).validate(rules)

    print(report.summary())
    print()
    print(f"JSON Report:\n{report.to_json()}")


if __name__ == "__main__":
    main()
