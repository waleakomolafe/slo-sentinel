import textwrap

import yaml

from slo_sentinel import cli
from slo_sentinel.burn import (
    BURN_TIERS, RECORDING_WINDOWS, Spec, SpecError, assemble, parse_spec,
)

SPEC = """
    service: checkout-api
    target: 0.999
    window: 28d
    indicator:
      error_ratio: |
        sum(rate(http_requests_total{job="checkout",code=~"5.."}[{{window}}]))
          /
        sum(rate(http_requests_total{job="checkout"}[{{window}}]))
"""


def spec():
    return parse_spec(yaml.safe_load(textwrap.dedent(SPEC)))


def test_placeholder_substituted_per_window():
    s = spec()
    assert "[5m]" in s.ratio_expr("5m")
    assert "[3d]" in s.ratio_expr("3d")
    assert "{{window}}" not in s.ratio_expr("1h")


def test_budget_math():
    s = spec()
    assert abs(s.budget - 0.001) < 1e-12


def test_slug_sanitized():
    assert spec().slug == "checkout_api"


def test_invalid_targets_rejected():
    doc = yaml.safe_load(textwrap.dedent(SPEC))
    for bad in (1.0, 0, -0.5, "99.9", None):
        doc["target"] = bad
        try:
            parse_spec(doc)
        except SpecError:
            continue
        raise AssertionError("target %r accepted" % bad)


def test_missing_indicator_rejected():
    doc = yaml.safe_load(textwrap.dedent(SPEC))
    del doc["indicator"]
    try:
        parse_spec(doc)
    except SpecError:
        return
    raise AssertionError("spec without indicator accepted")


def test_assembly_shape():
    doc = assemble(spec())
    assert [g["name"] for g in doc["groups"]] == [
        "checkout-api.slo.recording", "checkout-api.slo.alerts"]
    recording, alerts = doc["groups"]
    assert len(recording["rules"]) == 2 * len(RECORDING_WINDOWS)
    records = {r["record"] for r in recording["rules"]}
    for w in RECORDING_WINDOWS:
        assert "slo:checkout_api:error_ratio_rate%s" % w in records
        assert "slo:checkout_api:burn_rate%s" % w in records
    assert len(alerts["rules"]) == len(BURN_TIERS)


def test_burn_records_divide_by_budget():
    doc = assemble(spec())
    burn = [r for r in doc["groups"][0]["rules"] if ":burn_rate" in r["record"]]
    assert burn and all("0.001" in r["expr"] for r in burn)


def test_alerts_carry_both_windows_and_threshold():
    doc = assemble(spec())
    alerts = doc["groups"][1]["rules"]
    by_suffix = {a["alert"].rsplit("Burn", 1)[1]: a for a in alerts}
    for long_w, short_w, threshold, _frac, severity, suffix in BURN_TIERS:
        a = by_suffix[suffix]
        assert "burn_rate%s" % long_w in a["expr"]
        assert "burn_rate%s" % short_w in a["expr"]
        assert "> %g" % threshold in a["expr"]
        assert a["labels"]["severity"] == severity
        assert a["for"] in ("2m", "15m", "1h")


def test_camel_case_alert_names():
    doc = assemble(spec())
    names = [r["alert"] for r in doc["groups"][1]["rules"]]
    assert names == ["CheckoutApiErrorBudgetBurnFast",
                     "CheckoutApiErrorBudgetBurnSlow",
                     "CheckoutApiErrorBudgetBurnTicket"]


def test_expression_without_placeholder_passes_through():
    s = Spec(service="fixed", target=0.99, window="30d", expr="up == 0")
    assert s.ratio_expr("5m") == "up == 0"


def test_cli_writes_parseable_yaml(tmp_path, capsys):
    spec_path = tmp_path / "s.yaml"
    spec_path.write_text(textwrap.dedent(SPEC), encoding="utf-8")
    out = tmp_path / "generated"
    assert cli.main([str(spec_path), "-o", str(out)]) == 0
    dest = out / "checkout_api_slo.yaml"
    doc = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert doc["groups"][1]["rules"][0]["alert"] == "CheckoutApiErrorBudgetBurnFast"
    assert "recording rules, 3 alerts" in capsys.readouterr().out


def test_cli_rejects_bad_spec(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("service: x\ntarget: 1.5\nwindow: 28d\nindicator:\n"
                   "  error_ratio: up\n", encoding="utf-8")
    assert cli.main([str(bad), "-o", str(tmp_path / "o")]) == 2
    assert "target" in capsys.readouterr().err
