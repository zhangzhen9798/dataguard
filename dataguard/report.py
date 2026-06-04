"""
Validation report and result models.
"""

from __future__ import annotations

import html
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Result of a single rule validation."""

    column: str
    check_name: str
    passed: bool
    total_rows: int
    passed_rows: int
    failed_rows: int
    pass_rate: float
    threshold: float
    sample_failures: list[Any] = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {self.column}.{self.check_name} | "
            f"pass_rate={self.pass_rate:.2%} (threshold={self.threshold:.0%}) | "
            f"{self.passed_rows}/{self.total_rows} rows passed"
        )


@dataclass
class ValidationReport:
    """Aggregated report of all validation results."""

    results: list[ValidationResult]
    engine: str = "pandas"

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def is_valid(self) -> bool:
        return self.failed_count == 0

    def failed_results(self) -> list[ValidationResult]:
        """Return only failed results."""
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        """Return a human-readable summary."""
        lines = [
            "DataGuard Validation Report",
            f"Engine: {self.engine}",
            f"Total Rules: {self.total_count} | Passed: {self.passed_count} | Failed: {self.failed_count}",
            f"Overall Status: {'VALID' if self.is_valid else 'INVALID'}",
            "-" * 60,
        ]
        for r in self.results:
            lines.append(str(r))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "engine": self.engine,
            "total": self.total_count,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "is_valid": self.is_valid,
            "results": [
                {
                    "column": r.column,
                    "check": r.check_name,
                    "passed": r.passed,
                    "pass_rate": r.pass_rate,
                    "threshold": r.threshold,
                    "total_rows": r.total_rows,
                    "passed_rows": r.passed_rows,
                    "failed_rows": r.failed_rows,
                    "sample_failures": r.sample_failures[:5],
                }
                for r in self.results
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert report to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_html(
        self,
        output_path: str | None = None,
        title: str = "DataGuard Validation Report",
    ) -> str:
        """Generate a self-contained HTML report.

        Args:
            output_path: If provided, write HTML to this file path.
            title: Report title shown in the header.

        Returns:
            The complete HTML string.
        """
        escaped_title = _esc(title)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        overall_rate = sum(r.passed_rows for r in self.results) / max(
            sum(r.total_rows for r in self.results), 1
        )
        is_valid = self.is_valid
        status_text = "VALID" if is_valid else "INVALID"
        status_color = "#00E676" if is_valid else "#FF5252"
        status_bg = "rgba(0,230,118,0.08)" if is_valid else "rgba(255,82,82,0.08)"

        # ── Build HTML parts ──────────────────────────────
        parts: list[str] = []

        # <!DOCTYPE + <html>
        parts.append(_HTML_DOCTYPE)
        parts.append('<html lang="en">')
        parts.append("<head>")
        parts.append('<meta charset="UTF-8">')
        parts.append(
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        )
        parts.append(f"<title>{escaped_title} — DataGuard</title>")
        parts.append(_HTML_STYLE)
        parts.append("</head>")
        parts.append("<body>")
        parts.append(f'<div class="dg-root" data-valid="{str(is_valid).lower()}">')

        # ── Header ────────────────────────────────────────
        parts.append('<header class="dg-header">')
        parts.append('<div class="dg-header-left">')
        parts.append('<span class="dg-logo">DG</span>')
        parts.append(f'<span class="dg-title-text">{escaped_title}</span>')
        parts.append("</div>")  # dg-header-left
        parts.append('<div class="dg-header-right">')
        parts.append(f'<span class="dg-engine-badge">{_esc(self.engine)}</span>')
        parts.append(f'<span class="dg-timestamp">{_esc(timestamp)}</span>')
        parts.append("</div>")  # dg-header-right
        # Status bar
        parts.append(
            f'<div class="dg-status-bar" style="background:{status_bg};box-shadow:0 2px 20px {status_color}40;"></div>'
        )
        parts.append("</header>")

        # ── Main content ──────────────────────────────────
        parts.append('<main class="dg-main">')

        # ── Stats cards ─────────────────────────────────
        parts.append('<section class="dg-stats">')

        _card = [
            ("Total Rules", self.total_count, "#38BDF8", "list-check"),
            ("Passed", self.passed_count, "#00E676", "check-circle"),
            ("Failed", self.failed_count, "#FF5252", "x-circle"),
            (status_text, "—", "#818CF8", "shield-check"),
        ]
        card_classes = ["total", "passed", "failed", "status"]
        for i, (label, value, color, icon) in enumerate(_card):
            cls = card_classes[i]
            border = (
                f"1px solid {color}30"
                if cls != "status"
                else f"1px solid {status_color}50"
            )
            value_display = (
                f'<span class="dg-card-value" data-target="{value}">0</span>'
                if isinstance(value, int)
                else f'<span class="dg-card-value" style="color:{status_color}">{value}</span>'
            )
            parts.append(
                f'<div class="dg-card dg-card-{cls}" style="border:{border};">'
            )
            parts.append(
                f'<div class="dg-card-icon" style="background:{color}18;color:{color};">'
            )
            parts.append(
                f'<svg viewBox="0 0 24 24" width="22" height="22"><use href="#icon-{icon}"/></svg>'
            )
            parts.append("</div>")  # dg-card-icon
            parts.append('<div class="dg-card-body">')
            parts.append(f'<div class="dg-card-value">{value_display}</div>')
            parts.append(f'<div class="dg-card-label">{label}</div>')
            parts.append("</div>")  # dg-card-body
            if cls == "status":
                glow_style = (
                    f"box-shadow:0 0 30px {status_color}30;"
                    if is_valid
                    else f"box-shadow:0 0 30px {status_color}30;"
                )
                parts.append(f"<style>.dg-card-status{{{glow_style}}}</style>")
            parts.append("</div>")  # dg-card

        parts.append("</section>")  # dg-stats

        # ── SVG Progress Ring ────────────────────────────
        parts.append('<section class="dg-progress-section">')
        parts.append('<div class="dg-progress-ring">')
        circumference = 2 * 3.1415926535 * 90  # r=90
        offset = circumference * (1 - overall_rate)
        parts.append(
            f'<svg viewBox="0 0 220 220" class="dg-svg-ring">'
            f"<defs>"
            f'<linearGradient id="progGrad" x1="0%" y1="0%" x2="100%" y2="100%">'
            f'<stop offset="0%" stop-color="#38BDF8"/>'
            f'<stop offset="100%" stop-color="#818CF8"/>'
            f"</linearGradient>"
            f"</defs>"
            f'<circle cx="110" cy="110" r="90" class="dg-ring-bg"/>'
            f'<circle cx="110" cy="110" r="90" class="dg-ring-fg" '
            f'stroke-dasharray="{circumference}" '
            f'stroke-dashoffset="{offset}" '
            f'stroke="url(#progGrad)"/>'
            f'<text x="110" y="100" class="dg-ring-pct">{overall_rate:.1%}</text>'
            f'<text x="110" y="125" class="dg-ring-sub">'
            f"{sum(r.passed_rows for r in self.results)} / "
            f"{sum(r.total_rows for r in self.results)} rules passed"
            f"</text>"
            f"</svg>"
        )
        parts.append("</div>")  # dg-progress-ring
        parts.append("</section>")  # dg-progress-section

        # ── Results Table ────────────────────────────────
        parts.append('<section class="dg-results">')
        parts.append('<div class="dg-table-wrap">')
        # Table header
        parts.append('<table class="dg-table">')
        parts.append("<thead><tr>")
        for col_label in [
            "Column",
            "Check",
            "Status",
            "Pass Rate",
            "Passed",
            "Total",
            "Threshold",
        ]:
            parts.append(f"<th>{col_label}</th>")
        parts.append("</tr></thead>")
        # Table body
        parts.append("<tbody>")
        for r in self.results:
            status_cls = "pass" if r.passed else "fail"
            pct = f"{r.pass_rate:.1%}"
            pct_width = int(r.pass_rate * 100)
            pct_color = "#00E676" if r.passed else "#FF5252"
            fail_samples_html: list[str] = []
            if r.sample_failures and not r.passed:
                for sample in r.sample_failures[:5]:
                    fail_samples_html.append(
                        f'<span class="dg-sample-val">{_esc(str(sample))}</span>'
                    )
            details_content = ""
            if fail_samples_html:
                details_content = (
                    '<details class="dg-fail-details"><summary>View failure samples</summary>'
                    '<div class="dg-fail-samples">'
                    + "".join(fail_samples_html)
                    + "</div></details>"
                )
            parts.append(f'<tr class="dg-row-{status_cls}">')
            parts.append(f'<td class="dg-col-name">{_esc(r.column)}</td>')
            parts.append(f'<td class="dg-col-check">{_esc(r.check_name)}</td>')
            # Status badge
            badge_cls = (
                "dg-badge dg-badge-pass" if r.passed else "dg-badge dg-badge-fail"
            )
            badge_text = "PASS" if r.passed else "FAIL"
            parts.append(
                f'<td><span class="{badge_cls}"><span class="dg-dot"></span>{badge_text}</span></td>'
            )
            # Pass rate with mini bar
            parts.append(
                f"<td>"
                f'<div class="dg-mini-bar">'
                f'<div class="dg-mini-fill" style="width:{pct_width}%;background:{pct_color};"></div>'
                f"</div>"
                f'<span class="dg-pct-text">{pct}</span>'
                f"</td>"
            )
            parts.append(f'<td class="dg-col-num">{r.passed_rows}</td>')
            parts.append(f'<td class="dg-col-num">{r.total_rows}</td>')
            parts.append(f'<td class="dg-col-num">{r.threshold:.0%}</td>')
            parts.append("</tr>")
            if details_content:
                parts.append(
                    f'<tr class="dg-row-details"><td colspan="7">{details_content}</td></tr>'
                )
        parts.append("</tbody></table>")
        parts.append("</div>")  # dg-table-wrap
        parts.append("</section>")  # dg-results

        parts.append("</main>")  # dg-main

        # ── Footer ───────────────────────────────────────
        version = "0.6.0"
        parts.append('<footer class="dg-footer">')
        parts.append(
            f"<span>Generated by <strong>DataGuard</strong> v{version} &middot; {timestamp}</span>"
        )
        parts.append("</footer>")

        # ── SVG Icon Definitions ─────────────────────────
        parts.append(_SVG_DEFS)

        # ── Inline JS (animated counters) ─────────────
        parts.append(_HTML_JS)

        parts.append("</div>")  # dg-root
        parts.append("</body>")
        parts.append("</html>")

        html_output = "\n".join(parts)

        if output_path:
            _write_file(output_path, html_output)

        return html_output


# ─── HTML Template Parts ─────────────────────────────

_HTML_DOCTYPE = "<!DOCTYPE html>"

_HTML_STYLE = """<style>
:root{
  --dg-bg:#020617;--dg-surface:rgba(15,23,42,0.6);--dg-border:rgba(255,255,255,0.08);
  --dg-text:#E2E8F0;--dg-text-dim:#64748B;--dg-text-mid:#94A3B8;
  --dg-blue:#38BDF8;--dg-green:#00E676;--dg-red:#FF5252;--dg-purple:#818CF8;
}
*{box-sizing:border-box;margin:0;padding:0;}
html{background:#020617;color:#E2E8F0;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;}
body{min-height:100vh;background:radial-gradient(circle at 20% 30%,#0F172A 0%,#020617 50%,#0A0F1F 100%);
  background-attachment:fixed;}
/* Mesh gradient overlay */
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(circle at 15% 20%,rgba(56,189,248,0.06) 0%,transparent 50%),
    radial-gradient(circle at 85% 80%,rgba(129,140,248,0.05) 0%,transparent 50%),
    radial-gradient(circle at 50% 50%,rgba(0,230,118,0.03) 0%,transparent 50%);
  animation:dgDrift 30s ease-in-out infinite alternate;}
@keyframes dgDrift{0%{opacity:0.6;}100%{opacity:1;}}
.dg-root{position:relative;z-index:1;max-width:1280px;margin:0 auto;padding:0 24px 60px;}
/* Header */
.dg-header{display:flex;align-items:center;justify-content:space-between;
  padding:20px 28px;margin:0 -24px 32px;
  background:rgba(15,23,42,0.6);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-bottom:1px solid var(--dg-border);border-radius:0 0 20px 20px;position:relative;overflow:hidden;}
.dg-header-left{display:flex;align-items:center;gap:14px;}
.dg-logo{display:inline-flex;align-items:center;justify-content:center;
  width:42px;height:42px;border-radius:12px;
  background:linear-gradient(135deg,#38BDF8,#818CF8);color:#fff;font-weight:800;font-size:16px;}
.dg-title-text{font-size:22px;font-weight:800;
  background:linear-gradient(135deg,#38BDF8,#818CF8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.dg-header-right{display:flex;align-items:center;gap:14px;}
.dg-engine-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 14px;border-radius:999px;
  background:rgba(56,189,248,0.12);color:var(--dg-blue);border:1px solid rgba(56,189,248,0.3);font-size:12px;font-weight:600;}
.dg-timestamp{font-size:13px;color:var(--dg-text-dim);}
.dg-status-bar{position:absolute;bottom:0;left:0;right:0;height:4px;border-radius:0 0 20px 20px;
  background:linear-gradient(90deg,var(--dg-green),#69F0AE);background-size:200% 100%;animation:dgShimmer 2s linear infinite;}
@keyframes dgShimmer{0%{background-position:200% 0;}100%{background-position:-200% 0;}}
.dg-root[data-valid="false"] .dg-status-bar{background:linear-gradient(90deg,var(--dg-red),#FF8A80);background-size:200% 100%;animation:dgShimmer 2s linear infinite;}
/* Stats Cards */
.dg-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:24px;margin-bottom:36px;}
@media(max-width:1024px){.dg-stats{grid-template-columns:repeat(2,1fr);}}
@media(max-width:640px){.dg-stats{grid-template-columns:1fr;}}
.dg-card{background:var(--dg-surface);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  border:1px solid var(--dg-border);border-radius:20px;padding:28px 24px;position:relative;overflow:hidden;
  transition:all 0.4s cubic-bezier(0.4,0,0.2,1);cursor:default;}
.dg-card:hover{transform:translateY(-6px);
  box-shadow:0 20px 40px rgba(0,0,0,0.3),0 0 40px rgba(56,189,248,0.08);}
.dg-card::before{content:'';position:absolute;top:18px;right:20px;width:8px;height:8px;border-radius:50%;opacity:0.7;}
.dg-card-total::before{background:var(--dg-blue);}
.dg-card-passed::before{background:var(--dg-green);}
.dg-card-failed::before{background:var(--dg-red);}
.dg-card-status::before{background:var(--dg-purple);}
.dg-card-icon{width:48px;height:48px;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;margin-bottom:18px;}
.dg-card-body{display:flex;flex-direction:column;gap:6px;}
.dg-card-value{font-size:42px;font-weight:800;color:var(--dg-text);line-height:1;}
.dg-card-label{font-size:12px;color:var(--dg-text-dim);text-transform:uppercase;letter-spacing:1.8px;font-weight:600;}
/* Progress Ring */
.dg-progress-section{display:flex;justify-content:center;margin-bottom:44px;}
.dg-progress-ring{padding:20px;}
.dg-svg-ring{width:200px;height:200px;}
.dg-ring-bg{fill:none;stroke:#1E293B;stroke-width:12;}
.dg-ring-fg{fill:none;stroke-width:12;stroke-linecap:round;transform:rotate(-90deg);transform-origin:center;
  transition:stroke-dashoffset 1.5s ease-out;}
.dg-ring-pct{fill:var(--dg-text);font-size:28px;font-weight:800;text-anchor:middle;font-family:system-ui,sans-serif;}
.dg-ring-sub{fill:var(--dg-text-mid);font-size:11px;text-anchor:middle;font-family:system-ui,sans-serif;}
/* Results Table */
.dg-results{margin-bottom:40px;}
.dg-table-wrap{background:var(--dg-surface);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  border:1px solid var(--dg-border);border-radius:20px;overflow:hidden;}
.dg-table{width:100%;border-collapse:collapse;}
.dg-table thead{background:rgba(30,41,59,0.8);}
.dg-table th{padding:16px 20px;font-size:11px;color:var(--dg-text-dim);text-transform:uppercase;
  letter-spacing:2px;font-weight:700;text-align:left;border-bottom:1px solid rgba(255,255,255,0.06);}
.dg-table td{padding:14px 20px;font-size:13.5px;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:middle;}
.dg-table tbody tr{transition:background 0.3s;cursor:pointer;}
.dg-table tbody tr:hover{background:rgba(56,189,248,0.05);}
.dg-row-fail{border-left:4px solid var(--dg-red);}
.dg-row-pass{border-left:4px solid var(--dg-green);}
.dg-row-details td{background:rgba(255,82,82,0.04);border-left:4px solid var(--dg-red);padding:12px 20px;}
.dg-col-name{font-weight:600;color:var(--dg-text);font-family:'JetBrains Mono','Fira Code',monospace;font-size:13px;}
.dg-col-check{color:var(--dg-text-mid);font-family:'JetBrains Mono','Fira Code',monospace;font-size:12.5px;}
.dg-col-num{text-align:right;font-family:'JetBrains Mono','Fira Code',monospace;color:var(--dg-text-mid);}
.dg-badge{display:inline-flex;align-items:center;gap:7px;padding:4px 14px;border-radius:999px;font-size:12px;font-weight:700;}
.dg-badge-pass{background:rgba(0,230,118,0.12);color:var(--dg-green);border:1px solid rgba(0,230,118,0.3);}
.dg-badge-fail{background:rgba(255,82,82,0.12);color:var(--dg-red);border:1px solid rgba(255,82,82,0.3);}
.dg-dot{width:7px;height:7px;border-radius:50%;display:inline-block;}
.dg-badge-pass .dg-dot{background:var(--dg-green);box-shadow:0 0 8px var(--dg-green);}
.dg-badge-fail .dg-dot{background:var(--dg-red);box-shadow:0 0 8px var(--dg-red);}
/* Mini progress bar */
.dg-mini-bar{width:100px;height:6px;background:#1E293B;border-radius:3px;display:inline-block;vertical-align:middle;margin-right:8px;overflow:hidden;}
.dg-mini-fill{height:100%;border-radius:3px;transition:width 1s ease-out;}
.dg-pct-text{font-size:13px;color:var(--dg-text-mid);font-family:'JetBrains Mono',monospace;}
/* Failure samples */
.dg-fail-details{margin:4px 0 0;}
.dg-fail-details summary{cursor:pointer;font-size:12px;color:var(--dg-red);font-weight:600;padding:6px 0;}
.dg-fail-details summary:hover{color:#FF8A80;}
.dg-fail-samples{display:flex;flex-direction:column;gap:5px;padding:10px 0 4px;}
.dg-sample-val{display:inline-block;font-family:'JetBrains Mono','Fira Code',monospace;font-size:12.5px;
  color:var(--dg-red);background:rgba(255,82,82,0.12);padding:3px 10px;border-radius:5px;}
/* Footer */
.dg-footer{text-align:center;padding-top:28px;margin-top:40px;border-top:1px solid rgba(255,255,255,0.06);}
.dg-footer span{font-size:13px;color:var(--dg-text-dim);}
.dg-footer strong{color:var(--dg-text-mid);}
/* Animations */
@keyframes dgFadeInUp{from{opacity:0;transform:translateY(18px);}to{opacity:1;transform:translateY(0);}}
.dg-card{animation:dgFadeInUp 0.6s ease-out both;}
.dg-card:nth-child(2){animation-delay:0.1s;}
.dg-card:nth-child(3){animation-delay:0.2s;}
.dg-card:nth-child(4){animation-delay:0.3s;}
.dg-table tbody tr{animation:dgFadeInUp 0.5s ease-out both;}
</style>"""

_SVG_DEFS = """<svg width="0" height="0" style="position:absolute;">
<defs>
  <symbol id="icon-list-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
  </symbol>
  <symbol id="icon-check-circle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
  </symbol>
  <symbol id="icon-x-circle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
  </symbol>
  <symbol id="icon-shield-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/>
  </symbol>
</defs>
</svg>"""

_HTML_JS = """<script>
// Animated counters for stat cards
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.dg-card-value[data-target]').forEach(el => {
    const target = parseInt(el.dataset.target, 10);
    const duration = 1200;
    const start = performance.now();
    const animate = (now) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(target * eased);
      if (progress < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  });
  // SVG ring animation
  const ring = document.querySelector('.dg-ring-fg');
  if (ring) {
    const target = parseFloat(ring.getAttribute('stroke-dashoffset'));
    ring.setAttribute('stroke-dashoffset', ring.getAttribute('stroke-dasharray').split(' ')[0]);
    requestAnimationFrame(() => {
      ring.setAttribute('stroke-dashoffset', target);
    });
  }
});
</script>"""


# ─── Helpers ────────────────────────────────────────


def _esc(s: str) -> str:
    """HTML-escape a string to prevent XSS."""
    return html.escape(s)


def _write_file(path: str, content: str) -> None:
    """Write content to a file, ensuring parent dirs exist."""
    import os

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
