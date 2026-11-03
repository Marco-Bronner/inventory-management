"""
Tests for restocking endpoints and logic.
"""
import pytest

import main
import restocking


@pytest.fixture(autouse=True)
def clear_orders():
    """Reset the in-memory order store around every test."""
    main.restocking_orders.clear()
    yield
    main.restocking_orders.clear()


class TestRestockingRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_zero_budget_recommends_nothing(self, client):
        data = client.get("/api/restocking/recommendations?budget=0").json()
        assert data["items"] == []
        assert data["remaining_budget"] == 0
        assert data["max_budget"] > 0

    def test_full_budget_covers_all_shortfalls(self, client):
        max_budget = client.get("/api/restocking/recommendations").json()["max_budget"]
        data = client.get(f"/api/restocking/recommendations?budget={max_budget}").json()
        assert len(data["items"]) > 0
        assert all(i["quantity"] == i["shortfall"] for i in data["items"])
        assert data["remaining_budget"] == pytest.approx(0, abs=0.01)

    def test_budget_is_never_exceeded_and_sums_match(self, client):
        data = client.get("/api/restocking/recommendations?budget=3000").json()
        assert data["total_cost"] <= 3000
        assert data["total_cost"] == pytest.approx(sum(i["line_total"] for i in data["items"]))
        assert data["remaining_budget"] == pytest.approx(3000 - data["total_cost"])
        for item in data["items"]:
            assert item["line_total"] == pytest.approx(item["quantity"] * item["unit_cost"])

    def test_items_ordered_by_largest_shortfall(self, client):
        items = client.get("/api/restocking/recommendations?budget=100000").json()["items"]
        shortfalls = [i["shortfall"] for i in items]
        assert shortfalls == sorted(shortfalls, reverse=True)

    def test_negative_budget_rejected(self, client):
        assert client.get("/api/restocking/recommendations?budget=-5").status_code == 422

    def test_items_without_shortfall_are_excluded(self, client):
        skus = [i["sku"] for i in client.get("/api/restocking/recommendations?budget=100000").json()["items"]]
        assert "MTR-304" not in skus  # decreasing demand
        assert "PSU-501" not in skus  # 420 on hand covers forecast of 252

    def test_greedy_partial_fill(self):
        candidates = [
            {"sku": "A", "shortfall": 100, "unit_cost": 10.0, "trend": "increasing"},
            {"sku": "B", "shortfall": 50, "unit_cost": 5.0, "trend": "stable"},
        ]
        result = restocking.recommend(candidates, 1100)
        assert [(i["sku"], i["quantity"]) for i in result["items"]] == [("A", 100), ("B", 20)]
        assert result["remaining_budget"] == 0


class TestRestockingOrders:
    """Test suite for POST/GET /api/restocking/orders."""

    def _first_candidate(self, client):
        return client.get("/api/restocking/recommendations?budget=100000").json()["items"][0]

    def test_create_order(self, client):
        item = self._first_candidate(client)
        response = client.post("/api/restocking/orders", json={
            "items": [{"sku": item["sku"], "quantity": 10}], "budget": 5000})
        assert response.status_code == 201
        order = response.json()
        assert order["id"] == "RST-0001"
        assert order["status"] == "Submitted"
        assert order["total_cost"] == pytest.approx(10 * item["unit_cost"])
        assert order["lead_time_days"] == item["lead_time_days"]
        assert len(order["expected_delivery"]) == 10  # YYYY-MM-DD
        assert order["items"][0]["lead_time_days"] == item["lead_time_days"]

    def test_get_orders_newest_first(self, client):
        item = self._first_candidate(client)
        for qty in (1, 2):
            client.post("/api/restocking/orders", json={"items": [{"sku": item["sku"], "quantity": qty}]})
        orders = client.get("/api/restocking/orders").json()
        assert [o["id"] for o in orders] == ["RST-0002", "RST-0001"]

    def test_get_orders_empty(self, client):
        assert client.get("/api/restocking/orders").json() == []

    def test_order_lead_time_is_max_of_lines(self, client):
        items = client.get("/api/restocking/recommendations?budget=100000").json()["items"]
        lines = [{"sku": i["sku"], "quantity": 1} for i in items]
        order = client.post("/api/restocking/orders", json={"items": lines}).json()
        assert order["lead_time_days"] == max(i["lead_time_days"] for i in items)
        assert order["expected_delivery"] == max(i["expected_delivery"] for i in order["items"])

    def test_empty_order_rejected(self, client):
        assert client.post("/api/restocking/orders", json={"items": []}).status_code == 400

    def test_unknown_sku_rejected(self, client):
        response = client.post("/api/restocking/orders", json={"items": [{"sku": "NOPE-1", "quantity": 1}]})
        assert response.status_code == 400

    def test_invalid_quantity_rejected(self, client):
        item = self._first_candidate(client)
        for qty in (0, -1, item["shortfall"] + 1):
            response = client.post("/api/restocking/orders", json={"items": [{"sku": item["sku"], "quantity": qty}]})
            assert response.status_code == 400

    def test_duplicate_sku_rejected(self, client):
        item = self._first_candidate(client)
        line = {"sku": item["sku"], "quantity": 1}
        assert client.post("/api/restocking/orders", json={"items": [line, line]}).status_code == 400

    def test_over_budget_rejected(self, client):
        item = self._first_candidate(client)
        response = client.post("/api/restocking/orders", json={
            "items": [{"sku": item["sku"], "quantity": 10}], "budget": 1})
        assert response.status_code == 400
        assert client.get("/api/restocking/orders").json() == []

    def test_missing_fields_rejected(self, client):
        assert client.post("/api/restocking/orders", json={}).status_code == 422
