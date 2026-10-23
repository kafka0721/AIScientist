# Traffic Forecasting OOD Review Matrix

## Scenario Coverage

| Axis | Minimum evidence |
|---|---|
| Heavy rain | Intensity thresholds, event windows, forecast availability, recovery |
| Incident | Type, severity, location, detection delay, duration, recovery |
| Holiday | Statutory holiday, adjusted workday, pre/post-holiday, local calendar |
| Compound event | Rain+incident or rain+holiday when supported by sample size |
| Temporal shift | Complete future periods held out; seasonal and long-term drift |
| Spatial shift | Unseen sensors, corridors, networks, or cities for transfer claims |

Do not merge weekends, statutory holidays, and adjusted workdays into one label.

## Leakage Audit

- Fit scalers, imputers, graph construction, clustering, and feature selection on
  training data only.
- Prevent overlapping windows from crossing train/test event boundaries.
- Use only weather forecasts available at prediction issue time; report lead time.
- Respect incident reporting latency; hide clearance time and final severity.
- Prevent test events from influencing thresholds, early stopping, hyperparameters,
  augmentation, or model selection.

## Metrics and Uncertainty

Report MAE and RMSE plus WAPE or another stable relative metric. Treat MAPE cautiously
near zero flow. Also require:

- Per-scenario and per-horizon metrics.
- Relative degradation from normal conditions.
- Worst-group error and a tail-risk summary such as CVaR.
- Event-cluster bootstrap intervals or equivalent event-level analysis.
- Calibration/coverage for probabilistic predictions.
- Recovery performance after incidents or severe weather.
- Aggregate and sensor/corridor results for spatial claims.

## Baselines and Ablations

Include a historical/statistical baseline and competitive spatiotemporal models such as
DCRNN, STGCN, Graph WaveNet, or AGCRN. For robustness claims, compare applicable:

- Exogenous feature fusion without robust training.
- Reweighting or group distributionally robust optimization.
- Domain generalization or invariant representation learning.
- Event-aware mixture-of-experts or regime models.
- Test-time adaptation when deployment assumptions permit it.
- Uncertainty-aware fallback or abstention.

Ablate event features, robust loss, adaptation, uncertainty head, and fallback policy.
Report the normal-condition tradeoff.

## Minimal Falsifiers

- Re-split by complete events and refit all preprocessing.
- Replace observed future weather with archived forecasts at matching lead times.
- Hold out one city/network or a complete future season.
- Compare standard ERM with feature-matched Group DRO or reweighting.
- Bootstrap by event instead of treating correlated time points as independent.
- Report worst-group and normal-group changes at every horizon.

## Claim Boundaries

Do not generalize beyond tested event definitions, regions, sensors, horizons, data
quality, or deployment-time covariate availability. Require explicit limitations for
rare-event sample size and unobserved compound scenarios.
