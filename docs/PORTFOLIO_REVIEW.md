# Portfolio review guide

Use this page when evaluating PROMETHEUS in an interview or technical review.

## A 90-second walkthrough

1. Start with the [pipeline diagram](assets/prometheus-flow.svg): identity,
   point-in-time collection, provenance, deterministic analysis and delivery.
2. Open the [CURY3 preview](assets/cury3-report-preview.png) to see the human
   output produced by the same reporting layer.
3. Follow the [five-minute demo](PORTFOLIO_DEMO.md) to reproduce the run.
4. Read [engineering decisions](ENGINEERING_DECISIONS.md) and
   [validation status](VALIDATION_STATUS.md) for trade-offs and limitations.

## What this demonstrates

- Python package design with a CLI entry point and test suite;
- source-aware financial data handling rather than silent substitution;
- point-in-time safeguards against look-ahead bias;
- deterministic evidence checks around a human-readable PDF;
- operational thinking: review, approval, corrections and audit export.

## What it deliberately does not claim

This is not a regulated advisory service, a universal sector screener or a
performance track record. Sector KPI coverage is validated only where the
repository says it is, external feeds can be unavailable, and reports require
human review before delivery.
