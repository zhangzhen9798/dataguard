"""
Tests for the HTML report functionality (ValidationReport.to_html()).
"""

import os
import re
from datetime import datetime

import pandas as pd
import pytest

from dataguard import DataGuard, RuleSet, not_null, in_range, min_length
from dataguard.report import ValidationReport, ValidationResult


# ── Fixtures ─────────────────────────────────────

@pytest.fixture()
def sample_report():
    """Create a ValidationReport with a mix of PASS and FAIL results."""
    results = [
        ValidationResult(
            column="email",
            check_name="not_null",
            passed=True,
            total_rows=100,
            passed_rows=98,
            failed_rows=2,
            pass_rate=0.98,
            threshold=1.0,
            sample_failures=["[SKIPPED] not_null check"],
        ),
        ValidationResult(
            column="age",
            check_name="in_range(0, 120)",
            passed=False,
            total_rows=100,
            passed_rows=95,
            failed_rows=5,
            pass_rate=0.95,
            threshold=1.0,
            sample_failures=[125, -3, 150, 999, -10],
        ),
        ValidationResult(
            column="name",
            check_name="not_empty_string()",
            passed=True,
            total_rows=100,
            passed_rows=100,
            failed_rows=0,
            pass_rate=1.0,
            threshold=0.95,
            sample_failures=[],
        ),
    ]
    return ValidationReport(results=results, engine="pandas")


# ── HTML Output Tests ─────────────────────────────

class TestToHtmlOutput:
    """Verify the generated HTML contains expected structural elements."""

    def test_returns_string(self, sample_report):
        html = sample_report.to_html()
        assert isinstance(html, str)
        assert len(html) > 500

    def test_contains_doctype(self, sample_report):
        html = sample_report.to_html()
        assert "<!DOCTYPE html>" in html or "<!doctype html>" in html

    def test_contains_title(self, sample_report):
        html = sample_report.to_html(title="My Custom Report")
        assert "My Custom Report" in html

    def test_contains_dataguard_branding(self, sample_report):
        html = sample_report.to_html()
        assert "DataGuard" in html

    def test_contains_stats_cards(self, sample_report):
        html = sample_report.to_html()
        # Should contain stat values
        assert "3" in html  # total rules
        assert "2" in html  # passed

    def test_contains_progress_ring(self, sample_report):
        html = sample_report.to_html()
        assert "dg-ring-fg" in html
        assert "progGrad" in html

    def test_contains_results_table(self, sample_report):
        html = sample_report.to_html()
        assert "<table" in html
        assert "not_null" in html
        assert "in_range" in html

    def test_contains_status_badges(self, sample_report):
        html = sample_report.to_html()
        assert "PASS" in html
        assert "FAIL" in html

    def test_contains_failure_samples(self, sample_report):
        html = sample_report.to_html()
        # Failed sample values should appear masked or raw
        assert "125" in html

    def test_file_output(self, sample_report, tmp_path):
        out = tmp_path / "report.html"
        html = sample_report.to_html(output_path=str(out))
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "DataGuard" in content
        # Returned HTML should match file content
        assert html == content

    def test_xss_escaping(self, sample_report):
        """Title should be HTML-escaped to prevent XSS."""
        html = sample_report.to_html(title='<script>alert("xss")</script>')
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html or "alert" in html

    def test_sensitive_column_masking(self):
        """Sensitive columns should have masked values in HTML."""
        df = pd.DataFrame({
            "email": ["alice@example.com", None, "bad", "bob@example.com", "eve@example.com"],
            "ssn": ["111-22-3333", "444-55-6666", None, "777-88-9999", "000-00-0000"],
        })
        rules = RuleSet()
        rules.add("email", not_null())
        rules.add("ssn", not_null())
        dg = DataGuard(df, sensitive_columns={"ssn"})
        report = dg.validate(rules)
        html = report.to_html()
        # Masked values should NOT appear as raw
        assert "111-22-3333" not in html
        # The masked value should show as partially masked (e.g., "N***e" for None)
        # Just check that some masking is happening
        assert "***" in html

    def test_valid_report_has_valid_status(self):
        results = [
            ValidationResult(
                column="a", check_name="not_null",
                passed=True, total_rows=10, passed_rows=10,
                failed_rows=0, pass_rate=1.0, threshold=1.0,
            )
        ]
        report = ValidationReport(results=results)
        html = report.to_html()
        assert "VALID" in html

    def test_invalid_report_has_invalid_status(self, sample_report):
        html = sample_report.to_html()
        assert "INVALID" in html

    def test_footer_version(self, sample_report):
        html = sample_report.to_html()
        assert "0.6.0" in html
        assert "DataGuard" in html

    def test_contains_svg_defs(self, sample_report):
        html = sample_report.to_html()
        assert "<svg" in html
        assert "icon-list-check" in html  # SVG icon defs

    def test_contains_js_animation(self, sample_report):
        html = sample_report.to_html()
        assert "requestAnimationFrame" in html or "requestAnimationFrame" in html

    def test_no_external_dependencies(self, sample_report):
        """The HTML should be self-contained — no CDN or external links."""
        html = sample_report.to_html()
        assert "cdn.jsdelivr" not in html
        assert "fonts.googleapis" not in html
        # Only possible inline data URIs — no http(s) links in CSS/JS
        http_links = re.findall(r'https?://[^\s"\'>]+', html)
        # Allow data: URIs but not http
        for link in http_links:
            assert link.startswith("data:"), f"External link found: {link}"

    def test_glassmorphism_css(self, sample_report):
        html = sample_report.to_html()
        assert "backdrop-filter" in html or "backdrop-filter" in html
        assert "rgba(" in html  # Glass color format

    def test_dark_theme_colors(self, sample_report):
        html = sample_report.to_html()
        assert "#020617" in html or "#0F172A" in html  # Dark background
        assert "#38BDF8" in html or "#E2E8F0" in html  # Blue / text colors


class TestToHtmlIntegration:
    """Integration tests with real DataGuard validation."""

    def test_pandas_html_output(self):
        df = pd.DataFrame({
            "name": ["Alice", "Bob", "Charlie", None],  # None will fail not_null
            "age": [25, 130, 30, 25],  # 130 fails in_range(0, 120)
        })
        rules = RuleSet()
        rules.add("name", not_null())
        rules.add("age", in_range(0, 120))
        # Add a check that will pass
        rules.add("name", min_length(3))  # All names have length >= 3
        report = DataGuard(df).validate(rules)
        html = report.to_html()
        assert "DataGuard" in html
        assert "INVALID" in html  # Overall report is invalid
        assert "PASS" in html    # min_length check passes
        assert "FAIL" in html    # not_null and in_range fail

    def test_all_passed_html(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        rules = RuleSet()
        rules.add("a", in_range(0, 10))
        report = DataGuard(df).validate(rules)
        html = report.to_html()
        assert "VALID" in html
        assert "FAIL" not in html
