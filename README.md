# slo-sentinel

[![selftest](https://github.com/waleakomolafe/slo-sentinel/actions/workflows/selftest.yml/badge.svg)](https://github.com/waleakomolafe/slo-sentinel/actions/workflows/selftest.yml)

A small SLO spec in. The multiwindow multi-burn error-budget alerts out,
promtool-tested.

An error budget agreed in advance stops the speed-versus-reliability
argument mid-incident. The budget only holds if the alerts speak budget. A
raw error-ratio alert on a 99.9% target pages on traffic that is still
inside budget, and sleeps through a slow burn that quietly eats three weeks
of it.

The Google SRE workbook answer is multiwindow multi-burn
(chapter 5, [Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/)).
Every alert requires two windows, because one window lies in both
directions: a five-minute burst looks like an outage, and a healthy hourly
average hides a steady leak.

| tier | fires when | both windows | meaning |
|---|---|---|---|
| fast page | burn rate > 14.4 | 1h and 5m | 2% of the 28d budget gone in an hour |
| slow page | burn rate > 6 | 6h and 30m | 5% of the budget gone in six hours |
| ticket | burn rate > 1 | 3d and 6h | 10% of the budget gone over three days |

## The spec

    service: checkout-api
    target: 0.999
    window: 28d
    indicator:
      error_ratio: |
        sum(rate(http_requests_total{job="checkout",code=~"5.."}[{{window}}]))
          /
        sum(rate(http_requests_total{job="checkout"}[{{window}}]))

Write the indicator once. `{{window}}` is where each recording rule's rate
window goes, so the same expression is measured at 5m, 30m, 1h, 6h and 3d.
The indicator does not have to be a 5xx ratio; anything that yields an
error ratio works, like a consumer-lag threshold (see
`examples/kafka_consumer.yaml`).

## Use

    pip install .
    slo-sentinel examples/checkout_api.yaml -o generated/

Writes `generated/checkout_api_slo.yaml`: ten recording rules (error ratio
and burn rate at each window) and the three alerts above, ready for
`kubectl apply` or your Prometheus rule loader. Exit codes: 0 written, 2
spec rejected, with the reason on stderr.

## Selftest

CI does four things on every push: runs the Python tests, regenerates the
rules from this repo's own examples, validates them with
`promtool check rules`, and runs `promtool test rules` unit tests that
prove the multiwindow behavior, including the case that matters: a
six-minute 10% burst against a 99.9% target does not page, because the
hourly window is still inside budget. It then audits this repo's own
workflows with
[pipeline-sentinel](https://github.com/waleakomolafe/pipeline-sentinel).

## Scope and limits

One indicator per spec file. Thresholds are the workbook table, not
configurable: if you need different tiers, you need a different postmortem,
not a different tool. The `for:` durations (2m, 15m, 1h) match the tier
urgency.

## License

MIT
