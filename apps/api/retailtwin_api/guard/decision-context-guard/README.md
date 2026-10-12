# Decision Context Guard (DCG)

Deterministic enforcement layer between simulated decisions and the live Digital Twin.

MVP gates:
1. decision integrity
2. context version match
3. context freshness
4. physical/business constraints
5. action authorization

Possible outcomes:
- ALLOW
- DENY
- REFRESH_REQUIRED
- HUMAN_REVIEW

Core invariant: **No stale decision may commit to live state.**
