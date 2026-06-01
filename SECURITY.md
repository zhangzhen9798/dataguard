# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in DataGuard, please report it responsibly.

**Do not open a public GitHub issue.**

Instead, email: zhangzhen9798@users.noreply.github.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

## Response Time

- Acknowledgment within 48 hours
- Initial assessment within 5 business days
- Patch or mitigation within 14 business days for confirmed vulnerabilities

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.5.x   | Yes       |
| < 0.5   | No        |

## Known Security Considerations

### SQL Injection (Mitigated)

The SQL validation engine uses **parameterized queries** via SQLAlchemy `text()`
bind parameters for all user-provided values (check parameters like min/max values,
regex patterns, in_set values). Column and table names are validated with
`_validate_identifier()` to reject suspicious characters.

**Remaining considerations:**
- Column/table names use string interpolation (cannot be parameterized in SQL).
  The `_validate_identifier()` check only allows alphanumeric, underscores, dots,
  and hyphens. If you need to use identifiers with special characters, pass a
  pre-quoted SQLAlchemy Engine object.
- Only connect to databases with **read-only** user accounts as an additional
  defense-in-depth measure.

### Database Credential Exposure (Mitigated)

CLI `--sql` parameter accepts connection strings. To avoid credential exposure
in shell history and process listings:

- Use the `DQGUARD_DB_URL` environment variable instead of `--sql`
- Or pass a pre-created SQLAlchemy Engine object programmatically
- Connection strings are never logged

### PII Leakage (Mitigated)

Validation reports include `sample_failures` which contain actual data values.
To protect Personally Identifiable Information (PII):

- Use the `sensitive_columns` parameter when creating DataGuard:
  ```python
  guardian = DataGuard(df, sensitive_columns={"email", "phone", "ssn"})
  # or
  guardian = DataGuard.from_sql(engine, "users", sensitive_columns={"email", "phone"})
  ```
- Sensitive column values in `sample_failures` are automatically masked
  (e.g., `"alice@secret.com"` → `"a***m"`)
- Profile stats (min/max/mean/std) are suppressed for sensitive columns
- CLI: use `--sensitive email,phone,ssn` to specify sensitive columns
- Report files are written with owner-only permissions (0600 on Unix)

### ReDoS — Regular Expression Denial of Service (Mitigated)

`regex_match()` includes built-in protection against catastrophic backtracking:

- Nested quantifiers: `(a+)+`, `(a+)*` — **blocked**
- Overlapping alternations with quantifiers: `(a|a)+` — **blocked**
- Excessive repetition counts: `a{300,}` — **blocked** (max: 256)
- Invalid regex patterns — **rejected at creation time**

This is a heuristic check and may not catch all dangerous patterns. For
additional safety, consider using the `re2` library or Python 3.11+'s
`re.compile(pattern, re.TIMEOUT)`.

### SQLAlchemy Engine Lifecycle (Mitigated)

Engines created from connection strings are cached and automatically disposed
via `atexit` handler when the Python process exits. To manually dispose:

```python
from dataguard.sql_engine import _engines
for engine in _engines.values():
    engine.dispose()
```

For long-running processes, prefer passing pre-created Engine objects and
managing their lifecycle yourself.

### Custom Check Functions — Arbitrary Code Execution

`custom()` wraps an arbitrary Python function. This is by design, but:

- **Never** use `custom()` with functions from untrusted sources
- `from_dict()` does **not** support custom checks — only built-in checks
  can be loaded from configuration files
- Spark UDFs serialize and execute check functions on the cluster — ensure
  all check functions are trusted

### TLS/SSL for Database Connections

DataGuard does not enforce TLS/SSL for database connections. To ensure
encrypted connections:

- MySQL: Use `mysql+ pymysql://user:pass@host/db?ssl=true`
- PostgreSQL: Use `postgresql://user:pass@host/db?sslmode=require`
- Always verify your connection string includes SSL parameters

### Configuration File Injection (Mitigated)

`RuleSet.from_dict()` validates:
- Only known check names are allowed (whitelist)
- Only known keys (`check`, `params`, `threshold`) are accepted in check definitions
- Invalid parameters raise `ValueError` (prevents `**kwargs` injection)

### Error Messages

Error messages for missing columns use generic placeholders (`[COLUMN_NOT_FOUND]`)
instead of exposing column names, to prevent information leakage in SQL contexts.
