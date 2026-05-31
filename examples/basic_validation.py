"""
Example: Data Quality Validation for a User Dataset
"""

import pandas as pd
from dataguard import DataGuard, RuleSet, not_null, in_range, in_set, regex_match, unique


def main():
    # Simulate a user dataset with quality issues
    df = pd.DataFrame({
        "user_id": [1, 2, 3, 4, 4],            # duplicate id=4
        "name": ["Alice", "Bob", None, "Dana", "Eve"],  # one null
        "age": [25, 30, -5, 40, 150],           # -5 and 150 are invalid
        "email": [
            "alice@example.com",
            "invalid-email",
            "charlie@example.com",
            "dana@example.com",
            "eve@example.com",
        ],
        "status": ["active", "active", "inactive", "active", "unknown"],  # "unknown" invalid
    })

    # Define validation rules
    rules = RuleSet()
    rules.add("user_id", not_null())
    rules.add("user_id", unique())
    rules.add("name", not_null())
    rules.add("age", not_null())
    rules.add("age", in_range(0, 120))
    rules.add("email", regex_match(r"^[\w.-]+@[\w.-]+\.\w+$"))
    rules.add("status", in_set(["active", "inactive"]))

    # Run validation
    guardian = DataGuard(df)
    report = guardian.validate(rules)

    # Print report
    print(report.summary())
    print()

    # Print JSON for CI/CD
    print("JSON Report:")
    print(report.to_json())
    print()

    # Data profiling
    print("Data Profile:")
    profile = guardian.profile()
    for col, stats in profile.items():
        print(f"  {col}: {stats['distinct_count']} distinct, "
              f"{stats['null_rate']:.0%} nulls, "
              f"dtype={stats['dtype']}")


if __name__ == "__main__":
    main()
