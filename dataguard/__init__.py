"""
DataGuard - Lightweight Data Quality Validation Framework for Big Data Pipelines
"""

from __future__ import annotations

__version__ = "0.6.0"
__author__ = "Zhang Zhen (zhangzhen9798@users.noreply.github.com)"

from dataguard.core import DataGuard
from dataguard.rules import Rule, RuleSet
from dataguard.checks import (
    not_null,
    unique,
    in_range,
    regex_match,
    in_set,
    min_length,
    max_length,
    is_numeric,
    is_email,
    is_date,
    not_empty_string,
    max_value,
    min_value,
    custom,
)
from dataguard.report import ValidationReport
from dataguard.utils import CheckLevel, CheckSpec, EngineType

__all__ = [
    "DataGuard",
    "Rule",
    "RuleSet",
    "not_null",
    "unique",
    "in_range",
    "regex_match",
    "in_set",
    "min_length",
    "max_length",
    "is_numeric",
    "is_email",
    "is_date",
    "not_empty_string",
    "max_value",
    "min_value",
    "custom",
    "CheckSpec",
    "CheckLevel",
    "EngineType",
    "ValidationReport",
]
