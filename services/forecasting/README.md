# Forecasting

Demand forecast and anomaly signals backed by BigQuery / BigQuery ML or a deterministic MVP fallback.

Stockout risk for issue #32 is the deterministic calculator in [risk/README.md](risk/README.md). It does not call this forecast service. A forecast, when a later issue supplies one, can only raise the observed sales rate.
