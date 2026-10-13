"""Tests for /anomalies, /revenue, /promotions routes."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.analytics_repository import (
    InMemoryAnomalyRepository,
    InMemoryPromotionRepository,
    InMemoryRevenueRepository,
)
from retailtwin_api.schemas import (
    Anomaly,
    AnomalySeverity,
    AnomalyType,
    Promotion,
    PromotionStatus,
    PromotionType,
    RevenueBucket,
)

# #129 merged these tests without their route handlers, so main serves none of
# these routes. The public contracts and handlers land with #79 / #131, which
# removes this skip.
pytestmark = pytest.mark.skip(reason="GET /anomalies, /revenue, /promotions land with #79 (#131)")


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
        for period in ("hourly", "daily", "weekly", "monthly"):
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
