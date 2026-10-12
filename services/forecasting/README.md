# Forecasting

Demand forecast and anomaly signals. Issue #31 is the deterministic forecast in [demand/README.md](demand/README.md). Formula id `forecast-demand-v1`. BigQuery ML is not called. A disabled or unavailable model keeps the window-rate fallback.

Stockout risk for issue #32 is the deterministic calculator in [risk/README.md](risk/README.md). It does not call this forecast service. A forecast, when a later issue supplies one, can only raise the observed sales rate.
