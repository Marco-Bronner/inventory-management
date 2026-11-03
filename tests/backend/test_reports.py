"""
Tests for the filterable Reports endpoints (/api/reports/quarterly, /api/reports/monthly-trends).

Expected values are recomputed from main.orders so the tests do not hard-code mock data.
"""
import pytest

import main

QUARTER_MONTHS = main.QUARTER_MAP


def _select(warehouse=None, category=None, status=None, months=None):
    return [
        o for o in main.orders
        if (warehouse is None or o["warehouse"] == warehouse)
        and (category is None or o["category"] == category)
        and (status is None or o["status"] == status)
        and (months is None or any(m in o["order_date"] for m in months))
    ]


def _by_quarter(client, **params):
    return {q["quarter"]: q for q in client.get("/api/reports/quarterly", params=params).json()}


def _by_month(client, **params):
    return {m["month"]: m for m in client.get("/api/reports/monthly-trends", params=params).json()}


class TestQuarterlyReports:
    def test_unfiltered_totals_match_orders(self, client):
        quarters = _by_quarter(client)
        assert sum(q["total_orders"] for q in quarters.values()) == len(main.orders)
        assert list(quarters) == sorted(quarters)

    def test_all_means_no_filter(self, client):
        assert _by_quarter(client, warehouse="all", category="all", status="all", month="all") == _by_quarter(client)

    def test_warehouse_filter(self, client):
        quarters = _by_quarter(client, warehouse="London")
        assert sum(q["total_orders"] for q in quarters.values()) == len(_select(warehouse="London"))

    def test_category_filter_is_case_insensitive(self, client):
        expected = len(_select(category="Sensors"))
        assert sum(q["total_orders"] for q in _by_quarter(client, category="sensors").values()) == expected

    def test_status_filter_delivered_gives_full_fulfillment(self, client):
        quarters = _by_quarter(client, status="Delivered")
        assert sum(q["total_orders"] for q in quarters.values()) == len(_select(status="Delivered"))
        assert all(q["fulfillment_rate"] == 100 for q in quarters.values())

    def test_status_filter_not_delivered_gives_zero_fulfillment(self, client):
        quarters = _by_quarter(client, status="Shipped")
        assert quarters and all(q["fulfillment_rate"] == 0 for q in quarters.values())

    def test_quarter_month_filter_returns_only_that_quarter(self, client):
        quarters = _by_quarter(client, month="Q2-2025")
        assert list(quarters) == ["Q2-2025"]
        assert quarters["Q2-2025"]["total_orders"] == len(_select(months=QUARTER_MONTHS["Q2-2025"]))

    def test_single_month_filter(self, client):
        quarters = _by_quarter(client, month="2025-05")
        assert list(quarters) == ["Q2-2025"]
        assert quarters["Q2-2025"]["total_orders"] == len(_select(months=["2025-05"]))

    def test_combined_filters(self, client):
        quarters = _by_quarter(client, warehouse="Tokyo", category="Sensors", status="Delivered", month="Q1-2025")
        expected = _select("Tokyo", "Sensors", "Delivered", QUARTER_MONTHS["Q1-2025"])
        assert sum(q["total_orders"] for q in quarters.values()) == len(expected)
        assert sum(q["total_revenue"] for q in quarters.values()) == pytest.approx(
            sum(o["total_value"] for o in expected))

    def test_no_match_returns_empty_list(self, client):
        response = client.get("/api/reports/quarterly", params={"warehouse": "Atlantis"})
        assert response.status_code == 200
        assert response.json() == []

    def test_average_order_value(self, client):
        for q in _by_quarter(client).values():
            assert q["avg_order_value"] == pytest.approx(q["total_revenue"] / q["total_orders"], abs=0.01)


class TestMonthlyTrends:
    def test_unfiltered_totals_match_orders(self, client):
        months = _by_month(client)
        assert sum(m["order_count"] for m in months.values()) == len(main.orders)
        assert list(months) == sorted(months)

    def test_warehouse_and_category_filter(self, client):
        months = _by_month(client, warehouse="San Francisco", category="Actuators")
        expected = _select(warehouse="San Francisco", category="Actuators")
        assert sum(m["order_count"] for m in months.values()) == len(expected)
        assert sum(m["revenue"] for m in months.values()) == pytest.approx(sum(o["total_value"] for o in expected))

    def test_status_filter_counts_delivered(self, client):
        months = _by_month(client, status="Delivered")
        assert all(m["delivered_count"] == m["order_count"] for m in months.values())

    def test_month_filter_returns_single_month(self, client):
        months = _by_month(client, month="2025-03")
        assert list(months) == ["2025-03"]
        assert months["2025-03"]["order_count"] == len(_select(months=["2025-03"]))

    def test_quarter_filter_returns_three_months(self, client):
        months = _by_month(client, month="Q3-2025")
        assert sorted(months) == QUARTER_MONTHS["Q3-2025"]

    def test_combined_filters(self, client):
        months = _by_month(client, warehouse="London", status="Delivered", month="Q4-2025")
        expected = _select(warehouse="London", status="Delivered", months=QUARTER_MONTHS["Q4-2025"])
        assert sum(m["order_count"] for m in months.values()) == len(expected)

    def test_no_match_returns_empty_list(self, client):
        assert client.get("/api/reports/monthly-trends", params={"category": "Nothing"}).json() == []
