"""
Example: SQL-based Data Quality Validation
"""

from sqlalchemy import create_engine
from dataguard import DataGuard, RuleSet, not_null, in_range, in_set, regex_match, unique


def main():
    # Use an in-memory SQLite database for demo
    engine = create_engine("sqlite:///:memory:")

    # Create a test table
    import pandas as pd
    df = pd.DataFrame({
        "user_id": [1, 2, 3, 4, 4],
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
    df.to_sql("users", engine, index=False, if_exists="replace")

    # Define validation rules
    rules = RuleSet()
    rules.add("user_id", not_null())
    rules.add("user_id", unique())
    rules.add("name", not_null())
    rules.add("age", in_range(0, 120))
    rules.add("email", regex_match(r"^[\w.-]+@[\w.-]+\.\w+$"))
    rules.add("status", in_set(["active", "inactive"]))

    # Validate against the SQL table
    guardian = DataGuard.from_sql(engine, "users", dialect="mysql")
    report = guardian.validate(rules)

    print(report.summary())
    print()

    # Profile the SQL table
    print("Data Profile:")
    profile = guardian.profile()
    for col, stats in profile.items():
        null_pct = stats.get("null_rate", 0)
        dtype = stats.get("dtype", "unknown")
        print(f"  {col}: {stats.get('distinct_count', '?')} distinct, "
              f"{null_pct:.0%} nulls, dtype={dtype}")


if __name__ == "__main__":
    main()
