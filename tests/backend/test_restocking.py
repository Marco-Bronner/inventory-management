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


class TestRestockingEdgeBudgets:
    """inf/nan/huge budgets must be rejected with 422, never crash with 500."""

    @pytest.mark.parametrize("budget", ["inf", "-inf", "nan", "1e308", "1e12"])
    def test_non_finite_or_huge_budget_rejected(self, client, budget):
        assert client.get(f"/api/restocking/recommendations?budget={budget}").status_code == 422

    def test_maximum_allowed_budget_works(self, client):
        response = client.get(f"/api/restocking/recommendations?budget={restocking.MAX_BUDGET}")
        assert response.status_code == 200

    @pytest.mark.parametrize("budget", ["Infinity", "NaN", "1e12", "-1"])
    def test_order_budget_rejected(self, client, budget):
        # raw JSON body: Python's json module would not emit Infinity/NaN as a valid value
        body = '{"items": [{"sku": "X", "quantity": 1}], "budget": %s}' % budget
        response = client.post("/api/restocking/orders", content=body,
                               headers={"Content-Type": "application/json"})
        assert response.status_code == 422

    def test_recommend_rejects_inf_directly(self):
        candidates = [{"sku": "A", "shortfall": 5, "unit_cost": 1.0, "trend": "stable"}]
        with pytest.raises(ValueError):
            restocking.recommend(candidates, float("inf"))


class TestRestockingOpenOrders:
    """Already ordered, not yet delivered quantities reduce the shortfall."""

    def _first(self, client):
        return client.get("/api/restocking/recommendations?budget=100000").json()["items"][0]

    def test_full_order_removes_item_from_recommendations(self, client):
        item = self._first(client)
        assert client.post("/api/restocking/orders", json={
            "items": [{"sku": item["sku"], "quantity": item["shortfall"]}]}).status_code == 201
        skus = [i["sku"] for i in client.get("/api/restocking/recommendations?budget=100000").json()["items"]]
        assert item["sku"] not in skus

    def test_partial_order_reduces_shortfall(self, client):
        item = self._first(client)
        client.post("/api/restocking/orders", json={"items": [{"sku": item["sku"], "quantity": 3}]})
        after = {i["sku"]: i for i in client.get("/api/restocking/recommendations?budget=100000").json()["items"]}
        assert after[item["sku"]]["shortfall"] == item["shortfall"] - 3

    def test_same_recommendation_cannot_be_ordered_twice(self, client):
        item = self._first(client)
        line = {"items": [{"sku": item["sku"], "quantity": item["shortfall"]}]}
        assert client.post("/api/restocking/orders", json=line).status_code == 201
        assert client.post("/api/restocking/orders", json=line).status_code == 400
        assert len(client.get("/api/restocking/orders").json()) == 1

    def test_max_budget_shrinks_after_order(self, client):
        before = client.get("/api/restocking/recommendations").json()["max_budget"]
        item = self._first(client)
        client.post("/api/restocking/orders", json={"items": [{"sku": item["sku"], "quantity": item["shortfall"]}]})
        assert client.get("/api/restocking/recommendations").json()["max_budget"] < before

    def test_open_quantities_ignores_delivered_lines(self):
        from datetime import date
        orders = [{"status": "Submitted", "items": [
            {"sku": "A", "quantity": 5, "expected_delivery": "2030-01-10"},
            {"sku": "B", "quantity": 7, "expected_delivery": "2030-01-01"}]}]
        assert restocking.open_quantities(orders, today=date(2030, 1, 5)) == {"A": 5}
        assert restocking.open_quantities(orders, today=date(2030, 1, 10)) == {"A": 5}
        assert restocking.open_quantities(orders, today=date(2030, 1, 11)) == {}


class TestRestockingConcurrency:
    def test_parallel_posts_get_unique_ids(self, client):
        from concurrent.futures import ThreadPoolExecutor
        item = client.get("/api/restocking/recommendations?budget=100000").json()["items"][0]
        assert item["shortfall"] >= 30

        def post(_):
            return client.post("/api/restocking/orders", json={"items": [{"sku": item["sku"], "quantity": 1}]})

        with ThreadPoolExecutor(max_workers=16) as pool:
            responses = list(pool.map(post, range(30)))
        assert all(r.status_code == 201 for r in responses)
        ids = [r.json()["id"] for r in responses]
        assert len(set(ids)) == 30
        assert len(main.restocking_orders) == 30
