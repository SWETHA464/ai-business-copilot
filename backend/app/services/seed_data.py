"""Deterministic synthetic e-commerce dataset (no real people, no real data).

`generate_dataset` is pure Python so it can be tested without a database.
`insert_dataset` writes it through SQLAlchemy.

Built-in business story (so documents, SQL and analytics all agree):
  * Data covers 2025-10-01 .. 2026-09-30 (quarters 2025-Q4, 2026-Q1..Q3).
  * Q2 2026 is strong (spring promo, Wireless Earbuds Pro and Smart Home Hub surge).
  * Q3 2026 declines: Wireless Earbuds Pro loses demand (competitor price cuts, promo ended) and
    Smart Home Hub suffers supply shortages from August (fewer orders, many cancellations).
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

DATA_START = date(2025, 10, 1)
DATA_END = date(2026, 9, 30)

# sku, name, category, price, cost, base popularity weight
PRODUCTS = [
    ("EL-001", "Wireless Earbuds Pro", "Electronics", 149.00, 62.00, 14),
    ("EL-002", "Smart Home Hub", "Electronics", 199.00, 96.00, 10),
    ("EL-003", "4K Action Camera", "Electronics", 279.00, 150.00, 5),
    ("EL-004", "Portable Bluetooth Speaker", "Electronics", 79.00, 31.00, 11),
    ("HK-001", "Smart Air Fryer XL", "Home & Kitchen", 129.00, 58.00, 10),
    ("HK-002", "Robot Vacuum Lite", "Home & Kitchen", 249.00, 128.00, 6),
    ("HK-003", "Espresso Maker Compact", "Home & Kitchen", 169.00, 79.00, 6),
    ("FT-001", "Fitness Tracker Band", "Fitness", 89.00, 34.00, 11),
    ("FT-002", "Yoga Mat Premium", "Fitness", 49.00, 15.00, 8),
    ("FT-003", "Adjustable Dumbbell Set", "Fitness", 219.00, 110.00, 5),
    ("AC-001", "Laptop Backpack Pro", "Accessories", 99.00, 38.00, 8),
    ("AC-002", "USB-C Fast Charger 65W", "Accessories", 39.00, 11.00, 14),
]
BASE_WEIGHT = {p[1]: p[5] for p in PRODUCTS}

# Base monthly order volume before product-mix effects.
BASE_MONTH_ORDERS = {
    (2025, 10): 260, (2025, 11): 330, (2025, 12): 370,
    (2026, 1): 250, (2026, 2): 255, (2026, 3): 300,
    (2026, 4): 320, (2026, 5): 335, (2026, 6): 340,
    (2026, 7): 330, (2026, 8): 330, (2026, 9): 320,
}

REGIONS = ["North", "South", "East", "West", "Central"]
FIRST = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Priya", "Ethan", "Zara", "Lucas", "Anika",
         "Mateo", "Isha", "Oliver", "Leila", "Arjun", "Emma", "Kabir", "Nora", "Rohan", "Ava",
         "Diego", "Meera", "Jack", "Tara", "Samir", "Lena", "Omar", "Hana", "Felix", "Riya"]
LAST = ["Sharma", "Patel", "Nguyen", "Garcia", "Kim", "Singh", "Brown", "Khan", "Silva", "Rossi",
        "Ivanov", "Cohen", "Okafor", "Tanaka", "Muller", "Reddy", "Costa", "Novak", "Haddad", "Iyer"]
CHANNELS = ["web", "mobile_app", "marketplace"]
CHANNEL_W = [0.55, 0.3, 0.15]
METHODS = ["card", "paypal", "upi", "bank_transfer"]
METHOD_W = [0.62, 0.18, 0.12, 0.08]


def product_weight(name: str, d: date) -> float:
    w = float(BASE_WEIGHT[name])
    if name == "Wireless Earbuds Pro":
        if date(2026, 4, 28) <= d <= date(2026, 6, 30):
            w *= 1.15
        if d >= date(2026, 7, 1):
            w *= 0.5
    elif name == "Smart Home Hub":
        if date(2026, 4, 1) <= d <= date(2026, 6, 30):
            w *= 1.1
        elif date(2026, 7, 1) <= d <= date(2026, 7, 31):
            w *= 0.9
        elif d >= date(2026, 8, 1):
            w *= 0.4
    elif name == "Smart Air Fryer XL" and d >= date(2026, 7, 1):
        w *= 1.1
    elif name == "Fitness Tracker Band" and d >= date(2026, 7, 1):
        w *= 0.95
    return w


def discount_pct(d: date) -> float:
    if date(2025, 11, 24) <= d <= date(2025, 11, 30):
        return 0.15  # Black Friday week
    if date(2026, 4, 28) <= d <= date(2026, 5, 12):
        return 0.10  # Spring promotion
    return 0.0


def _month_days(y: int, m: int) -> list[date]:
    d = date(y, m, 1)
    out = []
    while d.month == m and d <= DATA_END:
        out.append(d)
        d += timedelta(days=1)
    return out


def generate_dataset(seed: int = 42, n_customers: int = 600) -> dict[str, list[dict]]:
    rng = random.Random(seed)

    # ---- products
    products = [
        {"id": i + 1, "sku": p[0], "name": p[1], "category": p[2], "unit_price": p[3], "cost": p[4]}
        for i, p in enumerate(PRODUCTS)
    ]
    by_name = {p["name"]: p for p in products}

    # ---- customers
    span = (date(2026, 8, 15) - date(2025, 1, 1)).days
    customers, propensity, churn_date = [], {}, {}
    for cid in range(1, n_customers + 1):
        signup = date(2025, 1, 1) + timedelta(days=int(rng.random() ** 1.3 * span))
        first, last = rng.choice(FIRST), rng.choice(LAST)
        customers.append(
            {
                "id": cid,
                "name": f"{first} {last}",
                "email": f"{first.lower()}.{last.lower()}{cid}@example.test",
                "region": rng.choices(REGIONS, [0.26, 0.2, 0.22, 0.2, 0.12])[0],
                "signup_date": signup,
            }
        )
        propensity[cid] = min(rng.paretovariate(2.2), 12.0)
        if rng.random() < 0.30:  # this customer stops buying at some point
            lo = max(signup + timedelta(days=30), DATA_START)
            hi = date(2026, 8, 1)
            if lo < hi:
                churn_date[cid] = lo + timedelta(days=rng.randint(0, (hi - lo).days))
    cust_by_id = {c["id"]: c for c in customers}

    # ---- orders
    orders, items, payments = [], [], []
    oid = iid = pid = 0
    for (y, m), base in BASE_MONTH_ORDERS.items():
        mid = date(y, m, 15)
        ratio = sum(product_weight(p["name"], mid) for p in products) / sum(BASE_WEIGHT.values())
        n_orders = round(base * ratio)
        days = _month_days(y, m)
        picked = []
        for _ in range(n_orders):
            if (y, m) == (2025, 11) and rng.random() < 0.35:
                d = date(2025, 11, rng.randint(24, 30))
            else:
                d = rng.choice(days)
            picked.append(d)
        picked.sort()
        elig_all = [c["id"] for c in customers if cust_by_id[c["id"]]["signup_date"] <= days[-1]]
        weights_all = [propensity[c] for c in elig_all]
        for d in picked:
            cid = None
            for _try in range(25):
                cand = rng.choices(elig_all, weights_all)[0]
                if cust_by_id[cand]["signup_date"] <= d and not (
                    cand in churn_date and d > churn_date[cand]
                ):
                    cid = cand
                    break
            if cid is None:
                continue
            oid += 1
            n_items = rng.choices([1, 2, 3], [0.6, 0.3, 0.1])[0]
            names = list(by_name)
            chosen: list[str] = []
            for _ in range(n_items):
                w = [product_weight(n, d) if n not in chosen else 0.0 for n in names]
                chosen.append(rng.choices(names, w)[0])
            pct = discount_pct(d)
            order_items = []
            for n in chosen:
                qty = rng.choices([1, 2, 3], [0.75, 0.2, 0.05])[0]
                price = by_name[n]["unit_price"]
                iid += 1
                order_items.append(
                    {
                        "id": iid, "order_id": oid, "product_id": by_name[n]["id"],
                        "quantity": qty, "unit_price": price,
                        "discount": round(qty * price * pct, 2),
                    }
                )
            total = round(sum(i["quantity"] * i["unit_price"] - i["discount"] for i in order_items), 2)

            hub_shortage = "Smart Home Hub" in chosen and d >= date(2026, 8, 1)
            if d >= date(2026, 9, 20):
                status = rng.choices(["completed", "pending", "cancelled"], [0.55, 0.40, 0.05])[0]
            elif hub_shortage:
                status = rng.choices(["completed", "cancelled", "refunded"], [0.66, 0.28, 0.06])[0]
            else:
                p_cancel = 0.09 if d >= date(2026, 7, 1) else 0.07
                status = rng.choices(
                    ["completed", "cancelled", "refunded"], [1 - p_cancel - 0.05, p_cancel, 0.05]
                )[0]
            orders.append(
                {
                    "id": oid, "customer_id": cid, "order_date": d, "status": status,
                    "channel": rng.choices(CHANNELS, CHANNEL_W)[0],
                }
            )
            items.extend(order_items)
            pay_status = {"completed": "paid", "pending": "pending", "cancelled": "failed",
                          "refunded": "refunded"}[status]
            pid += 1
            payments.append(
                {
                    "id": pid, "order_id": oid, "amount": total,
                    "method": rng.choices(METHODS, METHOD_W)[0], "status": pay_status,
                    "paid_at": datetime.combine(d, datetime.min.time()) + timedelta(hours=rng.randint(1, 20))
                    if pay_status in ("paid", "refunded") else None,
                }
            )
    return {
        "customers": customers, "products": products, "orders": orders,
        "order_items": items, "payments": payments,
    }


def insert_dataset(db, data: dict[str, list[dict]], reset: bool = True) -> dict[str, int]:
    """Insert generated rows. Imports models lazily to keep generate_dataset dependency-free."""
    from sqlalchemy import delete, insert

    from app.models import Customer, Order, OrderItem, Payment, Product

    if reset:
        for model in (Payment, OrderItem, Order, Product, Customer):
            db.execute(delete(model))
        db.flush()
    for model, key in ((Customer, "customers"), (Product, "products"), (Order, "orders"),
                       (OrderItem, "order_items"), (Payment, "payments")):
        rows = data[key]
        for i in range(0, len(rows), 1000):
            db.execute(insert(model), rows[i:i + 1000])
    db.commit()
    return {k: len(v) for k, v in data.items()}
