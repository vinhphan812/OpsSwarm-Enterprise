"""Tests for /anomalies, /revenue, /promotions routes."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.analytics_repository import (
    InMemoryAnomalyRepository,
    InMemoryPromotionRepository,
    InMemoryRevenueRepository,
    InMemoryCheckoutRepository,
)
from retailtwin_api.schemas import (
    Anomaly,
    AnomalySeverity,
    AnomalyType,
    Promotion,
    PromotionStatus,
    PromotionType,
    RevenueBucket,
    CheckoutResponse,
    CheckoutSummary,
    CheckoutTransaction,
    CheckoutLine,
    Cashier,
)


# ─── /anomalies tests ─────────────────────────────────────────────────────────

class TestAnomalies:
    def test_returns_empty_list(self, client: TestClient):
        response = client.get("/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert data["anomalies"] == []
        assert data["total"] == 0

    def test_returns_anomalies(
        self,
        client: TestClient,
        anomaly_repo: InMemoryAnomalyRepository,
    ):
        """anomaly_repo from conftest is already wired into client.app.state.anomalies."""
        now = datetime.now(timezone.utc)
        anomaly_repo.seed([
            Anomaly(
                anomaly_id="a-001",
                anomaly_type=AnomalyType.STOCKOUT,
                severity=AnomalySeverity.HIGH,
                store_id="store-001",
                sku="SKU001",
                shelf_id="S-A1",
                title="Stockout on SKU001",
                description="SKU001 is out of stock on shelf S-A1",
                detected_at=now - timedelta(hours=2),
                event_ids=["evt-1", "evt-2"],
                metadata={"zone": "fresh"},
            ),
        ])
        response = client.get("/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["anomalies"][0]["anomaly_id"] == "a-001"
        assert data["anomalies"][0]["severity"] == "high"
        assert data["anomalies"][0]["anomaly_type"] == "stockout"

    def test_filters_by_severity(self, client: TestClient, anomaly_repo: InMemoryAnomalyRepository):
        now = datetime.now(timezone.utc)
        anomaly_repo.seed([
            Anomaly(
                anomaly_id="a-001",
                anomaly_type=AnomalyType.STOCKOUT,
                severity=AnomalySeverity.HIGH,
                store_id="store-001",
                title="High anomaly",
                description="High severity",
                detected_at=now,
            ),
            Anomaly(
                anomaly_id="a-002",
                anomaly_type=AnomalyType.STOCKOUT,
                severity=AnomalySeverity.LOW,
                store_id="store-001",
                title="Low anomaly",
                description="Low severity",
                detected_at=now,
            ),
        ])
        response = client.get("/anomalies", params={"severity": "high"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["anomalies"][0]["anomaly_id"] == "a-001"

    def test_filters_by_type(self, client: TestClient, anomaly_repo: InMemoryAnomalyRepository):
        now = datetime.now(timezone.utc)
        anomaly_repo.seed([
            Anomaly(
                anomaly_id="a-001",
                anomaly_type=AnomalyType.STOCKOUT,
                severity=AnomalySeverity.HIGH,
                store_id="store-001",
                title="Stockout",
                description="Stockout",
                detected_at=now,
            ),
            Anomaly(
                anomaly_id="a-002",
                anomaly_type=AnomalyType.DEMAND_SURGE,
                severity=AnomalySeverity.HIGH,
                store_id="store-001",
                title="Demand surge",
                description="Demand surge",
                detected_at=now,
            ),
        ])
        response = client.get("/anomalies", params={"anomaly_type": "demand_surge"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["anomalies"][0]["anomaly_type"] == "demand_surge"

    def test_filters_by_since(self, client: TestClient, anomaly_repo: InMemoryAnomalyRepository):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=10)
        recent = now - timedelta(days=1)
        anomaly_repo.seed([
            Anomaly(
                anomaly_id="a-old",
                anomaly_type=AnomalyType.STOCKOUT,
                severity=AnomalySeverity.HIGH,
                store_id="store-001",
                title="Old",
                description="Old anomaly",
                detected_at=old,
            ),
            Anomaly(
                anomaly_id="a-recent",
                anomaly_type=AnomalyType.STOCKOUT,
                severity=AnomalySeverity.HIGH,
                store_id="store-001",
                title="Recent",
                description="Recent anomaly",
                detected_at=recent,
            ),
        ])
        since = (now - timedelta(days=5)).isoformat()
        response = client.get("/anomalies", params={"since": since})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["anomalies"][0]["anomaly_id"] == "a-recent"

    def test_respects_limit(self, client: TestClient, anomaly_repo: InMemoryAnomalyRepository):
        now = datetime.now(timezone.utc)
        anomaly_repo.seed([
            Anomaly(
                anomaly_id=f"a-{i:03d}",
                anomaly_type=AnomalyType.STOCKOUT,
                severity=AnomalySeverity.MEDIUM,
                store_id="store-001",
                title=f"Anomaly {i}",
                description=f"Description {i}",
                detected_at=now - timedelta(minutes=i),
            )
            for i in range(5)
        ])
        response = client.get("/anomalies", params={"limit": 2})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["anomalies"]) == 2


# ─── /revenue tests ───────────────────────────────────────────────────────────

class TestRevenue:
    def test_returns_empty_revenue(self, client: TestClient):
        response = client.get("/revenue")
        assert response.status_code == 200
        data = response.json()
        assert data["total_revenue"] == 0.0
        assert data["total_transactions"] == 0
        assert data["currency"] == "USD"
        assert data["period"] == "daily"

    def test_returns_revenue_with_buckets(
        self, client: TestClient, revenue_repo: InMemoryRevenueRepository
    ):
        now = datetime.now(timezone.utc)
        revenue_repo.seed([
            RevenueBucket(
                timestamp=now - timedelta(hours=1),
                revenue=150.0,
                transactions=3,
                items_sold=5,
            ),
            RevenueBucket(
                timestamp=now - timedelta(hours=2),
                revenue=200.0,
                transactions=4,
                items_sold=8,
            ),
        ])
        start = (now - timedelta(days=1)).isoformat()
        end = now.isoformat()
        response = client.get("/revenue", params={"start": start, "end": end, "period": "hourly"})
        assert response.status_code == 200
        data = response.json()
        assert data["total_revenue"] == 350.0
        assert data["total_transactions"] == 7
        assert data["total_items_sold"] == 13
        assert data["avg_transaction_value"] == 50.0
        assert data["period"] == "hourly"
        assert len(data["buckets"]) == 2

    def test_invalid_period_start_before_end(self, client: TestClient):
        now = datetime.now(timezone.utc)
        start = now.isoformat()
        end = (now - timedelta(days=1)).isoformat()
        response = client.get("/revenue", params={"start": start, "end": end})
        assert response.status_code == 422

    def test_accepts_period_parameter(self, client: TestClient):
        for period in ("hourly", "daily", "weekly", "monthly", "7d", "30d"):
            response = client.get("/revenue", params={"period": period})
            assert response.status_code == 200, f"period={period} failed"
            assert response.json()["period"] == period

    def test_default_period_is_daily(self, client: TestClient):
        response = client.get("/revenue")
        assert response.status_code == 200
        assert response.json()["period"] == "daily"


# ─── /promotions tests ────────────────────────────────────────────────────────

class TestPromotions:
    def test_returns_empty_promotions(self, client: TestClient):
        response = client.get("/promotions")
        assert response.status_code == 200
        data = response.json()
        assert data["promotions"] == []
        assert data["total"] == 0
        assert data["active_count"] == 0

    def test_returns_promotions(
        self, client: TestClient, promotion_repo: InMemoryPromotionRepository
    ):
        now = datetime.now(timezone.utc)
        promotion_repo.seed([
            Promotion(
                promotion_id="p-001",
                name="Summer Sale 20% Off",
                promotion_type=PromotionType.DISCOUNT_PERCENT,
                status=PromotionStatus.ACTIVE,
                store_id="store-001",
                sku="SKU001",
                discount_value=20.0,
                start_time=now - timedelta(days=5),
                end_time=now + timedelta(days=5),
                redemption_count=42,
            ),
        ])
        response = client.get("/promotions")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["active_count"] == 1
        assert data["promotions"][0]["promotion_id"] == "p-001"
        assert data["promotions"][0]["status"] == "active"

    def test_filters_by_status(
        self, client: TestClient, promotion_repo: InMemoryPromotionRepository
    ):
        now = datetime.now(timezone.utc)
        promotion_repo.seed([
            Promotion(
                promotion_id="p-active",
                name="Active Promo",
                promotion_type=PromotionType.DISCOUNT_PERCENT,
                status=PromotionStatus.ACTIVE,
                store_id="store-001",
                discount_value=10.0,
                start_time=now - timedelta(days=1),
                end_time=now + timedelta(days=1),
            ),
            Promotion(
                promotion_id="p-ended",
                name="Ended Promo",
                promotion_type=PromotionType.DISCOUNT_PERCENT,
                status=PromotionStatus.ENDED,
                store_id="store-001",
                discount_value=10.0,
                start_time=now - timedelta(days=10),
                end_time=now - timedelta(days=5),
            ),
        ])
        response = client.get("/promotions", params={"status": "active"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["promotions"][0]["promotion_id"] == "p-active"

    def test_filters_by_sku(
        self, client: TestClient, promotion_repo: InMemoryPromotionRepository
    ):
        now = datetime.now(timezone.utc)
        promotion_repo.seed([
            Promotion(
                promotion_id="p-sku001",
                name="SKU001 promo",
                promotion_type=PromotionType.DISCOUNT_ABSOLUTE,
                status=PromotionStatus.ACTIVE,
                store_id="store-001",
                sku="SKU001",
                discount_value=5.0,
                start_time=now - timedelta(days=1),
                end_time=now + timedelta(days=1),
            ),
            Promotion(
                promotion_id="p-sku002",
                name="SKU002 promo",
                promotion_type=PromotionType.DISCOUNT_ABSOLUTE,
                status=PromotionStatus.ACTIVE,
                store_id="store-001",
                sku="SKU002",
                discount_value=3.0,
                start_time=now - timedelta(days=1),
                end_time=now + timedelta(days=1),
            ),
        ])
        response = client.get("/promotions", params={"sku": "SKU001"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["promotions"][0]["sku"] == "SKU001"

    def test_respects_limit(
        self, client: TestClient, promotion_repo: InMemoryPromotionRepository
    ):
        now = datetime.now(timezone.utc)
        promotion_repo.seed([
            Promotion(
                promotion_id=f"p-{i:03d}",
                name=f"Promo {i}",
                promotion_type=PromotionType.DISCOUNT_PERCENT,
                status=PromotionStatus.ACTIVE,
                store_id="store-001",
                discount_value=10.0,
                start_time=now - timedelta(days=i),
                end_time=now + timedelta(days=5),
            )
            for i in range(10)
        ])
        response = client.get("/promotions", params={"limit": 3})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["promotions"]) == 3

    def test_active_count_excludes_non_active(
        self, client: TestClient, promotion_repo: InMemoryPromotionRepository
    ):
        now = datetime.now(timezone.utc)
        promotion_repo.seed([
            Promotion(
                promotion_id="p-active",
                name="Active",
                promotion_type=PromotionType.BUY_ONE_GET_ONE,
                status=PromotionStatus.ACTIVE,
                store_id="store-001",
                start_time=now - timedelta(days=1),
                end_time=now + timedelta(days=1),
            ),
            Promotion(
                promotion_id="p-upcoming",
                name="Upcoming",
                promotion_type=PromotionType.BUY_ONE_GET_ONE,
                status=PromotionStatus.UPCOMING,
                store_id="store-001",
                start_time=now + timedelta(days=1),
                end_time=now + timedelta(days=10),
            ),
            Promotion(
                promotion_id="p-ended",
                name="Ended",
                promotion_type=PromotionType.BUY_ONE_GET_ONE,
                status=PromotionStatus.ENDED,
                store_id="store-001",
                start_time=now - timedelta(days=10),
                end_time=now - timedelta(days=5),
            ),
        ])
        response = client.get("/promotions")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["active_count"] == 1  # only ACTIVE counts


# ─── /checkouts tests ──────────────────────────────────────────────────────────

class TestCheckouts:
    def test_returns_checkout(self, client: TestClient, checkout_repo: InMemoryCheckoutRepository):
        now = datetime.now(timezone.utc)
        checkout_repo.seed([
            CheckoutResponse(
                summary=CheckoutSummary(
                    checkout_id="CK01",
                    store_id="store-001",
                    status="open",
                    cashier=Cashier(staff_id="EMP-014", name="Linh Tran"),
                    shift_started_at=now - timedelta(hours=4),
                    business_date="2026-10-09",
                    revenue_today=26.52,
                    transactions_today=3,
                    items_scanned_today=8,
                    queue_length=2,
                    last_transaction_at=now,
                ),
                transactions=[
                    CheckoutTransaction(
                        transaction_id="CK01-0001",
                        checkout_id="CK01",
                        store_id="store-001",
                        completed_at=now,
                        cashier=Cashier(staff_id="EMP-014", name="Linh Tran"),
                        items=3,
                        total=9.97,
                        payment_method="cash",
                        lines=[
                            CheckoutLine(sku="P001", quantity=2, unit_price=3.49, line_total=6.98),
                            CheckoutLine(sku="P002", quantity=1, unit_price=2.99, line_total=2.99),
                        ],
                    )
                ],
            )
        ])
        response = client.get("/checkouts/CK01")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["checkout_id"] == "CK01"
        assert data["summary"]["revenue_today"] == 26.52
        assert len(data["transactions"]) == 1
        assert data["transactions"][0]["transaction_id"] == "CK01-0001"

    def test_checkout_not_found(self, client: TestClient):
        response = client.get("/checkouts/UNKNOWN")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "checkout_not_found"

    def test_checkout_analytics_unavailable(self, client: TestClient):
        from retailtwin_api.analytics_repository import _UnavailableCheckoutRepository
        client.app.state.checkouts = _UnavailableCheckoutRepository()
        response = client.get("/checkouts/CK01")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "analytics_unavailable"

    def test_cashier_pii_redacted_by_default(self, client: TestClient, checkout_repo: InMemoryCheckoutRepository):
        """Cashier staff_id and name are redacted unless redact_cashier=false."""
        now = datetime.now(timezone.utc)
        checkout_repo.seed([
            CheckoutResponse(
                summary=CheckoutSummary(
                    checkout_id="CK01",
                    store_id="store-001",
                    status="open",
                    cashier=Cashier(staff_id="EMP-014", name="Linh Tran"),
                    shift_started_at=now - timedelta(hours=4),
                    business_date="2026-10-09",
                    revenue_today=26.52,
                    transactions_today=3,
                    items_scanned_today=8,
                    queue_length=2,
                    last_transaction_at=now,
                ),
                transactions=[
                    CheckoutTransaction(
                        transaction_id="CK01-0001",
                        checkout_id="CK01",
                        store_id="store-001",
                        completed_at=now,
                        cashier=Cashier(staff_id="EMP-014", name="Linh Tran"),
                        items=3,
                        total=9.97,
                        payment_method="cash",
                        lines=[],
                    )
                ],
            )
        ])
        # Default: cashier is redacted from summary
        resp = client.get("/checkouts/CK01")
        assert resp.status_code == 200
        assert resp.json()["summary"]["cashier"] is None
        # Default: cashier is redacted from transactions
        assert resp.json()["transactions"][0]["cashier"] is None

        # Cashier data remains redacted even when a caller supplies unrelated query values.
        resp2 = client.get("/checkouts/CK01", params={"store_id": "store-001"})
        assert resp2.status_code == 200
        assert resp2.json()["summary"]["cashier"] is None
        assert resp2.json()["transactions"][0]["cashier"] is None

    def test_cross_store_isolation(self, client: TestClient, checkout_repo: InMemoryCheckoutRepository):
        """Same checkout_id exists in two stores — must NOT leak across stores."""
        now = datetime.now(timezone.utc)
        checkout_repo.seed([
            CheckoutResponse(
                summary=CheckoutSummary(
                    checkout_id="CK01",
                    store_id="store-001",
                    status="open",
                    cashier=None,
                    shift_started_at=now - timedelta(hours=2),
                    business_date="2026-10-09",
                    revenue_today=100.0,
                    transactions_today=5,
                    items_scanned_today=15,
                    queue_length=3,
                    last_transaction_at=now,
                ),
                transactions=[],
            ),
            CheckoutResponse(
                summary=CheckoutSummary(
                    checkout_id="CK01",
                    store_id="store-002",
                    status="closed",
                    cashier=None,
                    shift_started_at=now - timedelta(hours=6),
                    business_date="2026-10-09",
                    revenue_today=50.0,
                    transactions_today=2,
                    items_scanned_today=6,
                    queue_length=0,
                    last_transaction_at=None,
                ),
                transactions=[],
            ),
        ])
        # store-001 sees its own CK01
        resp = client.get("/checkouts/CK01", params={"store_id": "store-001"})
        assert resp.status_code == 200
        assert resp.json()["summary"]["store_id"] == "store-001"
        assert resp.json()["summary"]["revenue_today"] == 100.0
        # store-002 sees its own CK01
        resp2 = client.get("/checkouts/CK01", params={"store_id": "store-002"})
        assert resp2.status_code == 200
        assert resp2.json()["summary"]["store_id"] == "store-002"
        assert resp2.json()["summary"]["revenue_today"] == 50.0
