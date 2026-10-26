"""Spec parsing, burn math and rule assembly.

The window thresholds are the Google SRE workbook multiwindow multi-burn
table (chapter 5, "Alerting on SLOs"): 2% of the budget in 1h pages,
5% in 6h pages, 10% in 3d files a ticket. Two windows per alert so a
five-minute spike cannot page alone and a slow burn cannot hide behind
a healthy hourly average.
"""

import re
from dataclasses import dataclass, field

# (long window, short window, burn threshold, budget fraction, severity, suffix)
BURN_TIERS = (
    ("1h", "5m", 14.4, 0.02, "page", "Fast"),
    ("6h", "30m", 6.0, 0.05, "page", "Slow"),
    ("3d", "6h", 1.0, 0.10, "ticket", "Ticket"),
)
RECORDING_WINDOWS = ("5m", "30m", "1h", "6h", "3d")

PLACEHOLDER = "{{window}}"
WINDOW_RE = re.compile(r"^\d+d$")
SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


class SpecError(ValueError):
    pass


@dataclass
class Spec:
    service: str
    target: float
    window: str
    expr: str
    slug: str = field(init=False)

    def __post_init__(self):
        if not self.service or not isinstance(self.service, str):
            raise SpecError("service: a non-empty name is required")
        self.slug = SLUG_RE.sub("_", self.service).strip("_")
        if not self.slug:
            raise SpecError("service: no usable characters for metric names")
        if not isinstance(self.target, (int, float)) or not 0 < self.target < 1:
            raise SpecError("target: must be between 0 and 1, e.g. 0.999 for 99.9%")
        if not isinstance(self.window, str) or not WINDOW_RE.match(self.window):
            raise SpecError("window: budget horizon in days, e.g. '28d'")
        if not isinstance(self.expr, str) or not self.expr.strip():
            raise SpecError("indicator.error_ratio: a PromQL expression is required")

    @property
    def budget(self):
        return 1 - self.target

    def ratio_expr(self, window):
        return self.expr.replace(PLACEHOLDER, window)


def parse_spec(doc):
    if not isinstance(doc, dict):
        raise SpecError("spec: expected a YAML mapping")
    ind = doc.get("indicator")
    if not isinstance(ind, dict) or "error_ratio" not in ind:
        raise SpecError("indicator.error_ratio: missing")
    return Spec(
        service=doc.get("service"),
        target=doc.get("target"),
        window=doc.get("window"),
        expr=ind["error_ratio"],
    )


def fmt_target(target):
    # 0.999 -> "0.999"; 0.9999 -> "0.9999"; 0.9 -> "0.9"
    return repr(float(target)).rstrip("0").rstrip(".")


def assemble(spec):
    """Build the PrometheusRule document for one spec."""
    recording = []
    for w in RECORDING_WINDOWS:
        recording.append({
            "record": "slo:%s:error_ratio_rate%s" % (spec.slug, w),
            "expr": spec.ratio_expr(w),
        })
    for w in RECORDING_WINDOWS:
        recording.append({
            "record": "slo:%s:burn_rate%s" % (spec.slug, w),
            "expr": "slo:%s:error_ratio_rate%s / %s"
                    % (spec.slug, w, fmt_target(spec.budget)),
        })

    alerts = []
    for long_w, short_w, threshold, fraction, severity, suffix in BURN_TIERS:
        burn = "slo:%s:burn_rate" % spec.slug
        alerts.append({
            "alert": "%sErrorBudgetBurn%s" % (_camel(spec.slug), suffix),
            "expr": "%s%s > %s and %s%s > %s"
                    % (burn, long_w, _num(threshold), burn, short_w, _num(threshold)),
            "for": {"Fast": "2m", "Slow": "15m", "Ticket": "1h"}[suffix],
            "labels": {"severity": severity, "service": spec.service, "slo": spec.service},
            "annotations": {
                "summary": "%s burning error budget at %sx over %s and %s"
                           % (spec.service, _num(threshold), long_w, short_w),
                "description": "%.0f%% of the %s error budget burned in %s "
                               "against a %s target."
                               % (fraction * 100, spec.window, long_w,
                                  _fmt_pct(spec.target)),
            },
        })

    return {
        "groups": [
            {"name": "%s.slo.recording" % spec.service, "rules": recording},
            {"name": "%s.slo.alerts" % spec.service, "rules": alerts},
        ]
    }


def _camel(slug):
    return "".join(p.capitalize() for p in slug.split("_") if p)


def _num(x):
    return ("%g" % x)


def _fmt_pct(target):
    return "%.4g%%" % (target * 100)
