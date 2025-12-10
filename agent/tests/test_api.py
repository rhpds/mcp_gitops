"""API tests for FastAPI endpoints."""
import pytest
from unittest.mock import patch, AsyncMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked MCP registry."""
    with patch('main.mcp_registry') as mock_registry:
        mock_registry.initialize_all = AsyncMock()
        mock_registry.get_all_tools.return_value = []

        from main import app
        with TestClient(app) as test_client:
            yield test_client


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self, client):
        """Health endpoint should return 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_healthy_status(self, client):
        """Health endpoint should return healthy status."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"


class TestReportFailureEndpoint:
    """Tests for the /report-failure endpoint."""

    def test_report_failure_requires_namespace(self, client):
        """Should reject request without namespace."""
        response = client.post("/report-failure", json={"pod_name": "my-pod"})
        assert response.status_code == 422

    def test_report_failure_requires_pod_name(self, client):
        """Should reject request without pod_name."""
        response = client.post("/report-failure", json={"namespace": "default"})
        assert response.status_code == 422

    def test_report_failure_accepts_valid_request(self, client):
        """Should accept valid request with required fields."""
        with patch('main.run_agent', new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = "Issue created successfully"

            response = client.post("/report-failure", json={
                "namespace": "default",
                "pod_name": "my-pod-abc123"
            })

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "Issue created" in data["result"]

    def test_report_failure_accepts_optional_container(self, client):
        """Should accept request with optional container_name."""
        with patch('main.run_agent', new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = "Analysis complete"

            response = client.post("/report-failure", json={
                "namespace": "production",
                "pod_name": "api-server-xyz",
                "container_name": "main"
            })

            assert response.status_code == 200
            mock_agent.assert_called_once_with(
                namespace="production",
                pod_name="api-server-xyz",
                container_name="main"
            )

    def test_report_failure_handles_agent_error(self, client):
        """Should return 500 when agent raises exception."""
        with patch('main.run_agent', new_callable=AsyncMock) as mock_agent:
            mock_agent.side_effect = Exception("LLM connection failed")

            response = client.post("/report-failure", json={
                "namespace": "default",
                "pod_name": "failing-pod"
            })

            assert response.status_code == 500
            assert "LLM connection failed" in response.json()["detail"]
