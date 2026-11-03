"""
Restocking logic: candidate items, greedy budget allocation and lead times.

Pure functions, no FastAPI dependency.

Data rules (documented assumptions, because demand forecasts only partly
overlap with inventory.json):

* Unit cost: taken from inventory.json when the SKU is stocked, otherwise from
  PRODUCT_PROFILES (indicative supplier cost per SKU prefix).
* Stock on hand: sum of quantity_on_hand over all warehouses when the SKU is in
  inventory.json. For SKUs missing from inventory it is assumed that stock
  covers the *current* demand (on_hand = current_demand), so the shortfall is
  only the forecasted growth.
* Shortfall = max(0, forecasted_demand - on_hand). Items with no shortfall are
  not restock candidates.
* Already ordered: quantities of submitted restocking orders whose expected
  delivery date is still in the future count as incoming stock and are
  subtracted from the shortfall (otherwise the same recommendation could be
  ordered again and again). Once the delivery date has passed, the goods are
  assumed to be delivered; they are then expected to show up in inventory.json.
* Priority: largest shortfall first; ties broken by trend
  (increasing > stable > decreasing), then SKU.
* Lead time: fixed number of calendar days per SKU prefix (supplier lead time,
  PRODUCT_PROFILES). Expected delivery = order date + lead time; an order's
  expected delivery is the latest of its lines.
"""
import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

DEFAULT_PROFILE = {"unit_cost": 40.0, "lead_time_days": 14}

# SKU prefix -> indicative unit cost (USD) and supplier lead time (days)
PRODUCT_PROFILES: Dict[str, Dict[str, float]] = {
    "WDG": {"unit_cost": 45.0, "lead_time_days": 10},
    "BRG": {"unit_cost": 32.0, "lead_time_days": 14},
    "GSK": {"unit_cost": 12.5, "lead_time_days": 7},
    "MTR": {"unit_cost": 210.0, "lead_time_days": 28},
    "FLT": {"unit_cost": 8.75, "lead_time_days": 5},
    "VLV": {"unit_cost": 64.0, "lead_time_days": 18},
    "PSU": {"unit_cost": 18.99, "lead_time_days": 12},
    "SNR": {"unit_cost": 55.0, "lead_time_days": 21},
    "CTL": {"unit_cost": 140.0, "lead_time_days": 25},
}

TREND_RANK = {"increasing": 0, "stable": 1, "decreasing": 2}


def _profile(sku: str) -> Dict[str, float]:
    return PRODUCT_PROFILES.get(sku.split("-")[0], DEFAULT_PROFILE)


def get_lead_time_days(sku: str) -> int:
    return int(_profile(sku)["lead_time_days"])


# Upper bound for a budget; keeps float arithmetic and int() conversions sane.
MAX_BUDGET = 1_000_000_000.0


def open_quantities(orders: List[dict], today: Optional[date] = None) -> Dict[str, int]:
    """Sum quantities per SKU of submitted orders that are not yet delivered."""
    today = today or date.today()
    incoming: Dict[str, int] = {}
    for order in orders:
        if order.get("status") != "Submitted":
            continue
        for line in order["items"]:
            # A line stays open until its expected delivery day has passed
            if date.fromisoformat(line["expected_delivery"]) >= today:
                incoming[line["sku"]] = incoming.get(line["sku"], 0) + line["quantity"]
    return incoming


def build_candidates(demand_forecasts: List[dict], inventory_items: List[dict],
                     incoming: Optional[Dict[str, int]] = None) -> List[dict]:
    """Return restock candidates (shortfall > 0) sorted by priority.

    `incoming` maps SKU -> quantity already ordered and not yet delivered; it is
    subtracted from the shortfall.
    """
    incoming = incoming or {}
    stock: Dict[str, int] = {}
    cost: Dict[str, float] = {}
    for item in inventory_items:
        stock[item["sku"]] = stock.get(item["sku"], 0) + item["quantity_on_hand"]
        cost.setdefault(item["sku"], item["unit_cost"])

    candidates = []
    for f in demand_forecasts:
        sku = f["item_sku"]
        on_hand = stock.get(sku, f["current_demand"])
        shortfall = f["forecasted_demand"] - on_hand - incoming.get(sku, 0)
        if shortfall <= 0:
            continue
        candidates.append({
            "sku": sku,
            "name": f["item_name"],
            "trend": f["trend"],
            "current_demand": f["current_demand"],
            "forecasted_demand": f["forecasted_demand"],
            "quantity_on_hand": on_hand,
            "shortfall": shortfall,
            "unit_cost": round(cost.get(sku, _profile(sku)["unit_cost"]), 2),
            "lead_time_days": get_lead_time_days(sku),
        })
    candidates.sort(key=lambda c: (-c["shortfall"], TREND_RANK.get(c["trend"], 3), c["sku"]))
    return candidates


def recommend(candidates: List[dict], budget: float) -> dict:
    """Greedy allocation by priority; the last affordable item may be partially filled."""
    budget = float(budget)
    # inf/nan would turn `remaining // unit_cost` into nan and crash int();
    # the API layer rejects them with 422, this guards direct callers.
    if not math.isfinite(budget) or budget > MAX_BUDGET:
        raise ValueError("Budget must be a finite number not above %d" % MAX_BUDGET)
    remaining = max(0.0, budget)
    lines = []
    for c in candidates:
        qty = min(c["shortfall"], int(remaining // c["unit_cost"]))
        if qty <= 0:
            continue
        total = round(qty * c["unit_cost"], 2)
        remaining = round(remaining - total, 2)
        lines.append({**c, "quantity": qty, "line_total": total})
    spent = round(sum(l["line_total"] for l in lines), 2)
    return {
        "budget": round(float(budget), 2),
        "max_budget": max_budget(candidates),
        "total_cost": spent,
        "remaining_budget": round(float(budget) - spent, 2),
        "items": lines,
    }


def max_budget(candidates: List[dict]) -> float:
    """Cost of covering every shortfall in full (upper end of the budget slider)."""
    return round(sum(c["shortfall"] * c["unit_cost"] for c in candidates), 2)


def build_order(lines: List[dict], candidates: List[dict], now: Optional[datetime] = None) -> dict:
    """Price and date requested lines (sku, quantity) from server-side data.

    Raises ValueError for unknown SKUs, duplicate SKUs, or quantities above the shortfall.
    """
    now = now or datetime.now()
    by_sku = {c["sku"]: c for c in candidates}
    seen = set()
    items = []
    for line in lines:
        sku, qty = line["sku"], line["quantity"]
        if sku not in by_sku:
            raise ValueError(f"SKU {sku} is not a restock candidate")
        if sku in seen:
            raise ValueError(f"SKU {sku} appears more than once")
        seen.add(sku)
        c = by_sku[sku]
        if qty <= 0 or qty > c["shortfall"]:
            raise ValueError(f"Quantity for {sku} must be between 1 and {c['shortfall']}")
        items.append({
            "sku": sku,
            "name": c["name"],
            "quantity": qty,
            "unit_cost": c["unit_cost"],
            "line_total": round(qty * c["unit_cost"], 2),
            "lead_time_days": c["lead_time_days"],
            "expected_delivery": (now + timedelta(days=c["lead_time_days"])).date().isoformat(),
        })
    if not items:
        raise ValueError("Order must contain at least one item")
    return {
        "items": items,
        "total_cost": round(sum(i["line_total"] for i in items), 2),
        "lead_time_days": max(i["lead_time_days"] for i in items),
        "expected_delivery": max(i["expected_delivery"] for i in items),
        "submitted_at": now.replace(microsecond=0).isoformat(),
    }
