import pytest
"""Tests for API reliability: health status and graceful analytics degradation."""

from fastapi.testclient import TestClient

from retailtwin_api.analytics_repository import (
    AnalyticsError,
    AnomalyRepository,
    PromotionRepository,
    RevenueRepository,
)
from retailtwin_api.schemas import (
    AnomaliesResponse,
    PromotionsResponse,
    RevenueResponse,
)


# ─── Analytics failure stubs ────────────────────────────────────────────────────

class FailingAnomalyRepository:
    """Always raises AnalyticsError, simulating a GCP outage."""
    available = False

    def list_anomalies(self, store_id, severity=None, anomaly_type=None, since=None, limit=100):
        raise AnalyticsError("GCP quota exceeded")


class FailingRevenueRepository:
    """Always raises AnalyticsError, simulating a BigQuery outage."""
    available = False

    def get_revenue(self, store_id, period, start, end):
        raise AnalyticsError("BigQuery timeout")


class FailingPromotionRepository:
    """Always raises AnalyticsError, simulating a Firestore outage."""
    available = False

    def list_promotions(self, store_id, status=None, sku=None, category=None, limit=100):
        raise AnalyticsError("Firestore permission denied")


# ─── /anomalies graceful degradation ───────────────────────────────────────────

class TestAnomaliesReliability:
    def test_returns_empty_when_repo_unavailable(self, client_with_failures):
        """Unavailable anomaly repo returns empty list via unavailable stub, not 503."""
        response = client_with_failures.get("/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert data["anomalies"] == []
        assert data["total"] == 0

    def test_raises_503_on_analytics_error(self, settings):
        """Real AnalyticsError from failing repo is caught and mapped to 503."""
        from retailtwin_api.analytics_repository import (
            _UnavailableRevenueRepository,
            _UnavailablePromotionRepository,
        )
        from retailtwin_api.main import create_app

        app = create_app(settings)
        app.state.anomalies = FailingAnomalyRepository()
        app.state.revenue = _UnavailableRevenueRepository()
        app.state.promotions = _UnavailablePromotionRepository()

        with TestClient(app, raise_server_exceptions=False) as tc:
            resp = tc.get("/anomalies")

        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "analytics_unavailable"
        # No stack trace or internal path
        assert "Traceback" not in resp.text

    def test_error_response_never_leaks_internal_paths(self, settings):
        """Error envelope contains no paths, stack traces, or secret values."""
        from retailtwin_api.analytics_repository import (
            _UnavailableRevenueRepository,
            _UnavailablePromotionRepository,
        )
        from retailtwin_api.main import create_app

        app = create_app(settings)
        app.state.anomalies = FailingAnomalyRepository()
        app.state.revenue = _UnavailableRevenueRepository()
        app.state.promotions = _UnavailablePromotionRepository()

        with TestClient(app, raise_server_exceptions=False) as tc:
            resp = tc.get("/anomalies")

        text = resp.text
        # No filesystem paths
        assert ".json" not in text
        assert "site-packages" not in text
        # No stack traces
        assert "Traceback" not in text
        assert "raise " not in text


# ─── /revenue graceful degradation ─────────────────────────────────────────────

class TestRevenueReliability:
    def test_returns_zero_when_repo_unavailable(self, client_with_failures):
        """Unavailable revenue repo returns zero totals, not 503."""
        response = client_with_failures.get("/revenue")
        assert response.status_code == 200
        data = response.json()
        assert data["total_revenue"] == 0.0
        assert data["total_transactions"] == 0
        assert data["buckets"] == []

    def test_raises_503_on_analytics_error(self, settings):
        """Real AnalyticsError from failing repo is caught and mapped to 503."""
        from retailtwin_api.analytics_repository import (
            _UnavailableAnomalyRepository,
            _UnavailablePromotionRepository,
        )
        from retailtwin_api.main import create_app

        app = create_app(settings)
        app.state.anomalies = _UnavailableAnomalyRepository()
        app.state.revenue = FailingRevenueRepository()
        app.state.promotions = _UnavailablePromotionRepository()

        with TestClient(app, raise_server_exceptions=False) as tc:
            resp = tc.get("/revenue")

        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "analytics_unavailable"
        assert "Traceback" not in resp.text


# ─── /promotions graceful degradation ─────────────────────────────────────────

class TestPromotionsReliability:
    def test_returns_empty_when_repo_unavailable(self, client_with_failures):
        """Unavailable promotions repo returns empty list, not 503."""
        response = client_with_failures.get("/promotions")
        assert response.status_code == 200
        data = response.json()
        assert data["promotions"] == []
        assert data["total"] == 0
        assert data["active_count"] == 0

    def test_raises_503_on_analytics_error(self, settings):
        """Real AnalyticsError from failing repo is caught and mapped to 503."""
        from retailtwin_api.analytics_repository import (
            _UnavailableAnomalyRepository,
            _UnavailableRevenueRepository,
        )
        from retailtwin_api.main import create_app

        app = create_app(settings)
        app.state.anomalies = _UnavailableAnomalyRepository()
        app.state.revenue = _UnavailableRevenueRepository()
        app.state.promotions = FailingPromotionRepository()

        with TestClient(app, raise_server_exceptions=False) as tc:
            resp = tc.get("/promotions")

        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "analytics_unavailable"
        assert "Traceback" not in resp.text


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client_with_failures(settings):
    """Test client with unavailable analytics repositories (available=False stubs)."""
    from retailtwin_api.analytics_repository import (
        _UnavailableAnomalyRepository,
        _UnavailableRevenueRepository,
        _UnavailablePromotionRepository,
    )
    from retailtwin_api.main import create_app

    app = create_app(settings)
    app.state.anomalies = _UnavailableAnomalyRepository()
    app.state.revenue = _UnavailableRevenueRepository()
    app.state.promotions = _UnavailablePromotionRepository()
    with TestClient(app) as tc:
        yield tc
