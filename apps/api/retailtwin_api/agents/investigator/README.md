# Investigator

ADR 0011. `investigate` turns one `InvestigationStart` into an `EvidenceBundle`.

The injected provider may request read tools. The investigator executes those calls through the tool registry with the `READ` grant and ignores the model's prose. It does not import a model SDK and it does not change the Live Twin.

Mandatory sources are inventory (`get_inventory`), shelf (`get_shelf_state`), recent sales (`get_sales_history`), forecast (`forecast_demand`), promotions (`get_promotions`), and planogram (`get_planogram`). Each successful item carries `source`, `entity_id`, `version`, `observed_at`, and `value` inside the payload. A mandatory source with no versioned result is an `insufficient_evidence` item and has no `value`. `is_sufficient` is true only when every mandatory source was observed.

`get_promotions` is a catalog tool. It stays off the default exposed list until `bind_read_port` attaches a reader. Forecast numbers come from that injected reader. Tests pass the deterministic `forecast_demand` service. Stockout risk is not mandatory and is not guessed from inventory.
