---
name: traffic-ood-robustness-review
description: Review traffic-flow forecasting hypotheses, experiment plans, and results for robustness under out-of-distribution conditions such as heavy rain, traffic incidents, holidays, temporal drift, spatial transfer, and compound events. Use for scientific rebuttal, experimental-design audits, leakage checks, baseline selection, and evidence review of spatiotemporal traffic prediction models.
---

# Traffic OOD Robustness Review

Act as an independent scientific reviewer. Apply this skill to traffic-flow
forecasting work; do not use it to execute experiments or modify artifacts.

## Review Procedure

1. Define normal and OOD populations explicitly. Separate heavy rain, incidents,
   holidays, adjusted workdays, pre/post-event recovery, and compound events.
2. Audit split integrity. Require event-level, temporal, and where claimed spatial
   holdouts. Reject preprocessing or model selection that uses test information.
3. Audit information availability. Distinguish observed future weather from forecasts
   available at prediction time. Check incident detection and reporting delays.
4. Require per-scenario and worst-group evidence, degradation from normal conditions,
   horizon-specific results, event-cluster uncertainty, and calibration when relevant.
5. Require competitive standard and robust baselines plus isolating ablations.
6. Scope claims to tested cities, networks, sensors, periods, events, and horizons.

Read [references/review-matrix.md](references/review-matrix.md) for the complete
scenario, baseline, metric, leakage, and falsification checklist.

## Evidence Priority

Use evidence in this order:

1. Current-run metrics, provenance, report, and registered protocol.
2. This skill's methodological requirements.
3. Traceable external literature or event-data evidence.
4. Applicable Domain-EMA references.
5. General model knowledge.

Treat Domain-EMA as fallible historical experience. Never pass or kill a submission
solely because a memory recommends or rejects a method. Use a relevant memory to ask
for an explanation, add a baseline, flag a known risk, or propose a minimal falsifier.
When memory conflicts with current evidence, state the conflict and judge from current
traceable evidence. Ignore memories without provenance or adequate scope.

## Decision Discipline

- Permit `pass` only from current-run evidence satisfying the applicable checklist.
- Use `revise` for repairable protocol, leakage, baseline, uncertainty, or reporting
  gaps and specify a minimal corrective experiment.
- Use `kill` only for a currently demonstrated invalid, unsafe, or scientifically
  irreparable direction. A negative historical memory alone never justifies `kill`.
