"""Business analytics with pandas. ALL numbers shown to users are computed here, never by an LLM.

Definitions (also shown in the UI and reports):
  * Revenue  = sum(quantity * unit_price - discount) over order_items of orders with status 'completed'.
               Pending, cancelled and refunded orders are excluded; refunded value is reported separately.
  * Orders   = all orders regardless of status unless a metric says "completed".
  * AOV      = revenue / completed orders.
  * Churned customer = has >= 1 completed order and none in the 90 days up to the reference date
               (the latest order date in the data).
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

REVENUE_DEFINITION = (
    "Revenue counts only completed orders: sum(quantity x unit_price - discount). "
    "Pending, cancelled and refunded orders are excluded."
)
CHURN_DEFINITION = (
    "A customer is churned when they have at least one completed order but none in the "
    "90 days before the reference date (the latest order date in the data)."
)
CHURN_DAYS = 90

SALES_COLUMNS = [
    "order_id", "customer_id", "order_date", "status", "channel", "region",
    "product_id", "product_name", "category", "quantity", "unit_price", "discount",
]

SALES_SQL = """
SELECT o.id AS order_id, o.customer_id, o.order_date, o.status, o.channel, c.region,
       oi.product_id, p.name AS product_name, p.category,
       oi.quantity, oi.unit_price, oi.discount
FROM orders o
JOIN customers c ON c.id = o.customer_id
LEFT JOIN order_items oi ON oi.order_id = o.id
LEFT JOIN products p ON p.id = oi.product_id
"""
CUSTOMERS_SQL = "SELECT id, name, region, signup_date FROM customers"
PAYMENTS_SQL = "SELECT order_id, amount, method, status FROM payments"


# ----------------------------------------------------------------------------- loading
def build_sales_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=SALES_COLUMNS)
    df["order_date"] = pd.to_datetime(df["order_date"])
    for col in ("quantity", "unit_price", "discount"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
    df["line_revenue"] = df["quantity"] * df["unit_price"] - df["discount"]
    df["quarter"] = df["order_date"].dt.year.astype(str) + "-Q" + df["order_date"].dt.quarter.astype(str)
    df["month"] = df["order_date"].dt.strftime("%Y-%m")
    return df


def load_frames(conn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load (sales, customers, payments) frames from a SQLAlchemy connection."""
    from sqlalchemy import text

    sales = build_sales_frame([dict(r) for r in conn.execute(text(SALES_SQL)).mappings().all()])
    cust = pd.DataFrame([dict(r) for r in conn.execute(text(CUSTOMERS_SQL)).mappings().all()],
                        columns=["id", "name", "region", "signup_date"])
    cust["signup_date"] = pd.to_datetime(cust["signup_date"])
    pay = pd.DataFrame([dict(r) for r in conn.execute(text(PAYMENTS_SQL)).mappings().all()],
                       columns=["order_id", "amount", "method", "status"])
    pay["amount"] = pd.to_numeric(pay["amount"], errors="coerce").fillna(0.0).astype(float)
    return sales, cust, pay


# ----------------------------------------------------------------------------- helpers
def _r(x: Any, n: int = 2) -> float:
    return round(float(x), n) if x is not None and not (isinstance(x, float) and np.isnan(x)) else 0.0


def money(x: float) -> str:
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def reference_date(df: pd.DataFrame) -> pd.Timestamp:
    return df["order_date"].max()


def quarter_label(ts: pd.Timestamp) -> str:
    return f"{ts.year}-Q{(ts.month - 1) // 3 + 1}"


def quarter_bounds(label: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    y, q = label.split("-Q")
    y, q = int(y), int(q)
    start = pd.Timestamp(year=y, month=3 * (q - 1) + 1, day=1)
    end = (start + pd.offsets.QuarterEnd(0)).normalize()
    return start, end


def previous_quarter(label: str) -> str:
    y, q = label.split("-Q")
    y, q = int(y), int(q)
    return f"{y - 1}-Q4" if q == 1 else f"{y}-Q{q - 1}"


def last_complete_quarter(df: pd.DataFrame) -> str:
    ref = reference_date(df)
    label = quarter_label(ref)
    _, end = quarter_bounds(label)
    if ref >= end - pd.Timedelta(days=2):
        return label
    return previous_quarter(label)


def completed(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["status"] == "completed"]


def revenue_of(df: pd.DataFrame) -> float:
    return float(completed(df)["line_revenue"].sum())


def _order_count(df: pd.DataFrame, status: str | None = None) -> int:
    d = df if status is None else df[df["status"] == status]
    return int(d["order_id"].nunique())


# ----------------------------------------------------------------------------- charts
def chart(kind: str, title: str, x_key: str, series: list[tuple[str, str]], data: list[dict],
          value_format: str = "currency") -> dict:
    return {
        "type": kind, "title": title, "xKey": x_key,
        "series": [{"key": k, "label": lbl} for k, lbl in series],
        "data": data, "valueFormat": value_format,
    }


# ----------------------------------------------------------------------------- metrics
def kpis(df: pd.DataFrame, customers: pd.DataFrame) -> dict:
    comp = completed(df)
    rev = revenue_of(df)
    n_completed = _order_count(df, "completed")
    total_orders = _order_count(df)
    refunded_value = float(df[df["status"] == "refunded"]["line_revenue"].sum())
    return {
        "total_revenue": _r(rev),
        "total_orders": total_orders,
        "completed_orders": n_completed,
        "pending_orders": _order_count(df, "pending"),
        "cancelled_orders": _order_count(df, "cancelled"),
        "refunded_orders": _order_count(df, "refunded"),
        "refunded_value": _r(refunded_value),
        "total_customers": int(len(customers)),
        "active_customers": int(comp["customer_id"].nunique()),
        "average_order_value": _r(rev / n_completed) if n_completed else 0.0,
        "cancellation_rate_pct": _r(100 * _order_count(df, "cancelled") / total_orders) if total_orders else 0.0,
        "refund_rate_pct": _r(100 * _order_count(df, "refunded") / total_orders) if total_orders else 0.0,
        "reference_date": str(reference_date(df).date()),
    }


def monthly_revenue(df: pd.DataFrame) -> list[dict]:
    comp = completed(df)
    g = comp.groupby("month").agg(revenue=("line_revenue", "sum"), orders=("order_id", "nunique"))
    return [{"month": m, "revenue": _r(r.revenue), "orders": int(r.orders)} for m, r in g.iterrows()]


def quarterly_revenue(df: pd.DataFrame) -> list[dict]:
    comp = completed(df)
    g = comp.groupby("quarter").agg(revenue=("line_revenue", "sum"), orders=("order_id", "nunique"))
    out, prev = [], None
    for q, r in g.iterrows():
        rev = float(r.revenue)
        out.append({
            "quarter": q, "revenue": _r(rev), "orders": int(r.orders),
            "aov": _r(rev / r.orders) if r.orders else 0.0,
            "qoq_change_pct": _r(100 * (rev - prev) / prev) if prev else None,
        })
        prev = rev
    return out


def product_performance(df: pd.DataFrame, quarter: str | None = None, top_n: int | None = None) -> list[dict]:
    d = df if quarter is None else df[df["quarter"] == quarter]
    comp = completed(d)
    g = comp.groupby(["product_name", "category"]).agg(
        revenue=("line_revenue", "sum"), units=("quantity", "sum"), orders=("order_id", "nunique")
    ).reset_index().sort_values("revenue", ascending=False)
    total = float(g["revenue"].sum()) or 1.0
    rows = [
        {"rank": i + 1, "product": r.product_name, "category": r.category, "revenue": _r(r.revenue),
         "units": int(r.units), "orders": int(r.orders), "share_pct": _r(100 * r.revenue / total)}
        for i, r in enumerate(g.itertuples())
    ]
    return rows[:top_n] if top_n else rows


def revenue_by_category(df: pd.DataFrame, quarter: str | None = None) -> list[dict]:
    d = df if quarter is None else df[df["quarter"] == quarter]
    g = completed(d).groupby("category")["line_revenue"].sum().sort_values(ascending=False)
    return [{"category": c, "revenue": _r(v)} for c, v in g.items()]


def revenue_by_region(df: pd.DataFrame, quarter: str | None = None) -> list[dict]:
    d = df if quarter is None else df[df["quarter"] == quarter]
    g = completed(d).groupby("region")["line_revenue"].sum().sort_values(ascending=False)
    return [{"region": c, "revenue": _r(v)} for c, v in g.items()]


def compare_quarters(df: pd.DataFrame, current: str | None = None, previous: str | None = None) -> dict:
    current = current or last_complete_quarter(df)
    previous = previous or previous_quarter(current)
    cur_df, prev_df = df[df["quarter"] == current], df[df["quarter"] == previous]
    cur_rev, prev_rev = revenue_of(cur_df), revenue_of(prev_df)
    change = cur_rev - prev_rev
    pc = completed(cur_df).groupby("product_name")["line_revenue"].sum()
    pp = completed(prev_df).groupby("product_name")["line_revenue"].sum()
    cat = df.drop_duplicates("product_name").set_index("product_name")["category"]
    rows = []
    for name in sorted(set(pc.index) | set(pp.index)):
        c, p = float(pc.get(name, 0.0)), float(pp.get(name, 0.0))
        ch = c - p
        rows.append({
            "product": name, "category": cat.get(name, ""),
            "current": _r(c), "previous": _r(p), "change": _r(ch),
            "change_pct": _r(100 * ch / p) if p else None,
            "share_of_total_change_pct": _r(100 * ch / change) if change and (ch < 0) == (change < 0) else 0.0,
        })
    rows.sort(key=lambda r: r["change"])
    cur_orders, prev_orders = _order_count(cur_df), _order_count(prev_df)
    cur_comp, prev_comp = _order_count(cur_df, "completed"), _order_count(prev_df, "completed")
    return {
        "current_quarter": current, "previous_quarter": previous,
        "current_revenue": _r(cur_rev), "previous_revenue": _r(prev_rev),
        "change": _r(change), "change_pct": _r(100 * change / prev_rev) if prev_rev else None,
        "current_orders": cur_orders, "previous_orders": prev_orders,
        "current_completed_orders": cur_comp, "previous_completed_orders": prev_comp,
        "current_aov": _r(cur_rev / cur_comp) if cur_comp else 0.0,
        "previous_aov": _r(prev_rev / prev_comp) if prev_comp else 0.0,
        "current_cancellation_rate_pct": _r(100 * _order_count(cur_df, "cancelled") / cur_orders) if cur_orders else 0.0,
        "previous_cancellation_rate_pct": _r(100 * _order_count(prev_df, "cancelled") / prev_orders) if prev_orders else 0.0,
        "products": rows,
        "top_decliners": [r for r in rows if r["change"] < 0][:3],
        "top_gainers": [r for r in sorted(rows, key=lambda r: -r["change"]) if r["change"] > 0][:3],
    }


def order_status_breakdown(df: pd.DataFrame, quarter: str | None = None) -> list[dict]:
    d = df if quarter is None else df[df["quarter"] == quarter]
    o = d.drop_duplicates("order_id")
    total = len(o) or 1
    g = o.groupby("status").size().sort_values(ascending=False)
    return [{"status": s, "orders": int(n), "share_pct": _r(100 * n / total)} for s, n in g.items()]


def payment_status_breakdown(payments: pd.DataFrame) -> list[dict]:
    g = payments.groupby("status").agg(payments=("order_id", "count"), amount=("amount", "sum"))
    return [{"status": s, "payments": int(r.payments), "amount": _r(r.amount)} for s, r in g.iterrows()]


def customer_table(df: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    """Per-customer recency/frequency/monetary on completed orders, relative to the reference date."""
    ref = reference_date(df)
    comp = completed(df)
    g = comp.groupby("customer_id").agg(
        last_order=("order_date", "max"), frequency=("order_id", "nunique"), monetary=("line_revenue", "sum")
    )
    t = customers.set_index("id").join(g, how="left")
    t["frequency"] = t["frequency"].fillna(0).astype(int)
    t["monetary"] = t["monetary"].fillna(0.0)
    t["recency_days"] = (ref - t["last_order"]).dt.days
    return t


def segment_customers(df: pd.DataFrame, customers: pd.DataFrame) -> dict:
    t = customer_table(df, customers)

    def seg(r) -> str:
        if r.frequency == 0:
            return "No purchases"
        if r.recency_days > CHURN_DAYS:
            return "Churned"
        if r.recency_days > 45:
            return "At risk"
        if r.frequency >= 5:
            return "Champions"
        if r.frequency >= 3:
            return "Loyal"
        return "Recent / new"

    t["segment"] = t.apply(seg, axis=1)
    g = t.groupby("segment").agg(customers=("name", "count"), revenue=("monetary", "sum"),
                                 avg_orders=("frequency", "mean")).reset_index()
    total = int(g["customers"].sum()) or 1
    rows = [{"segment": r.segment, "customers": int(r.customers), "share_pct": _r(100 * r.customers / total),
             "revenue": _r(r.revenue), "avg_orders": _r(r.avg_orders)} for r in g.itertuples()]
    rows.sort(key=lambda r: -r["customers"])
    return {"segments": rows, "definition": (
        "Segments use recency/frequency of completed orders: Champions (>=5 orders, bought in last 45 days), "
        "Loyal (3-4 orders, last 45 days), Recent / new (1-2 orders, last 45 days), At risk (46-90 days since "
        f"last order), Churned (>{CHURN_DAYS} days), No purchases.")}


def churn_analysis(df: pd.DataFrame, customers: pd.DataFrame) -> dict:
    t = customer_table(df, customers)
    buyers = t[t["frequency"] > 0]
    churned = buyers[buyers["recency_days"] > CHURN_DAYS]
    by_region = (
        buyers.assign(churned=buyers["recency_days"] > CHURN_DAYS)
        .groupby("region").agg(customers=("name", "count"), churned=("churned", "sum")).reset_index()
    )
    rows = [{"region": r.region, "customers": int(r.customers), "churned": int(r.churned),
             "churn_rate_pct": _r(100 * r.churned / r.customers) if r.customers else 0.0}
            for r in by_region.itertuples()]
    rate = _r(100 * len(churned) / len(buyers)) if len(buyers) else 0.0
    repeat = _r(100 * (buyers["frequency"] >= 2).sum() / len(buyers)) if len(buyers) else 0.0
    return {
        "customers_with_purchases": int(len(buyers)), "churned_customers": int(len(churned)),
        "churn_rate_pct": rate, "repeat_purchase_rate_pct": repeat,
        "revenue_from_churned_customers": _r(churned["monetary"].sum()),
        "by_region": rows, "definition": CHURN_DEFINITION, "reference_date": str(reference_date(df).date()),
    }


def customer_overview(df: pd.DataFrame, customers: pd.DataFrame, top_n: int = 10) -> dict:
    t = customer_table(df, customers)
    buyers = t[t["frequency"] > 0]
    top = buyers.sort_values("monetary", ascending=False).head(top_n)
    return {
        "customers_with_purchases": int(len(buyers)),
        "avg_orders_per_customer": _r(buyers["frequency"].mean()) if len(buyers) else 0.0,
        "avg_revenue_per_customer": _r(buyers["monetary"].mean()) if len(buyers) else 0.0,
        "top_customers": [{"customer": r.name, "region": r.region, "orders": int(r.frequency),
                           "revenue": _r(r.monetary)} for r in top.itertuples()],
    }


# ----------------------------------------------------------------------------- composite builders
def dashboard_summary(df: pd.DataFrame, customers: pd.DataFrame) -> dict:
    last_q = last_complete_quarter(df)
    return {
        "kpis": kpis(df, customers),
        "top_products": product_performance(df, top_n=5),
        "monthly_revenue": monthly_revenue(df),
        "quarterly_revenue": quarterly_revenue(df),
        "latest_quarter": last_q,
        "definitions": {"revenue": REVENUE_DEFINITION, "churn": CHURN_DEFINITION},
    }


def _table(title: str, rows: list[dict]) -> dict:
    cols = list(rows[0].keys()) if rows else []
    return {"title": title, "columns": cols, "rows": [[r[c] for c in cols] for r in rows]}


def _quarters_in_text(text: str) -> list[str]:
    found = re.findall(r"(20\d{2})\s*[-_ ]?\s*q([1-4])", text.lower())
    return [f"{y}-Q{q}" for y, q in found]


def analyze_question(question: str, df: pd.DataFrame, customers: pd.DataFrame,
                     payments: pd.DataFrame | None = None) -> dict:
    """Map a business question to calculated results. Intent detection is deterministic keyword matching
    so results are reproducible; an LLM only explains the output."""
    q = question.lower()
    result: dict[str, Any] = {"intent": "overview", "metrics": {}, "tables": [], "charts": [],
                              "definitions": [REVENUE_DEFINITION]}
    quarters = _quarters_in_text(question)
    compare_words = ("compare", "comparison", "versus", " vs", "declin", "decreas", "drop", "fell",
                     "previous quarter", "grew", "growth", "why")

    if any(w in q for w in ("segment",)):
        result["intent"] = "customer_segments"
        seg = segment_customers(df, customers)
        result["metrics"] = {"segments": seg["segments"]}
        result["definitions"].append(seg["definition"])
        result["tables"].append(_table("Customer segments", seg["segments"]))
        result["charts"].append(chart("pie", "Customers by segment", "segment", [("customers", "Customers")],
                                      seg["segments"], "number"))
    elif any(w in q for w in ("churn", "retention", "lapsed", "retain")):
        result["intent"] = "churn"
        ch = churn_analysis(df, customers)
        result["metrics"] = ch
        result["definitions"].append(CHURN_DEFINITION)
        result["tables"].append(_table("Churn by region", ch["by_region"]))
        result["charts"].append(chart("bar", "Churn rate by region (%)", "region",
                                      [("churn_rate_pct", "Churn rate %")], ch["by_region"], "percent"))
    elif any(w in q for w in ("cancel", "refund", "pending", "order status", "payment")):
        result["intent"] = "order_status"
        qtr = quarters[0] if quarters else None
        rows = order_status_breakdown(df, qtr)
        result["metrics"] = {"order_status": rows, "quarter": qtr, "kpis": kpis(df, customers)}
        result["tables"].append(_table("Orders by status" + (f" ({qtr})" if qtr else ""), rows))
        result["charts"].append(chart("pie", "Orders by status", "status", [("orders", "Orders")], rows, "number"))
        if payments is not None:
            pays = payment_status_breakdown(payments)
            result["metrics"]["payment_status"] = pays
            result["tables"].append(_table("Payments by status", pays))
    elif any(w in q for w in compare_words) and ("quarter" in q or quarters or "sales" in q or "revenue" in q):
        result["intent"] = "quarter_comparison"
        cur = quarters[-1] if len(quarters) >= 1 else None
        prev = quarters[-2] if len(quarters) >= 2 else None
        if len(quarters) == 2 and quarters[0] > quarters[1]:
            cur, prev = quarters
        elif len(quarters) == 2:
            prev, cur = quarters
        cmp_ = compare_quarters(df, cur, prev)
        result["metrics"] = cmp_
        prod_rows = cmp_["products"]
        result["tables"].append(_table(
            f"Product revenue {cmp_['previous_quarter']} vs {cmp_['current_quarter']}", prod_rows))
        result["charts"].append(chart(
            "bar", f"Revenue by product: {cmp_['previous_quarter']} vs {cmp_['current_quarter']}", "product",
            [("previous", cmp_["previous_quarter"]), ("current", cmp_["current_quarter"])],
            sorted(prod_rows, key=lambda r: -max(r["current"], r["previous"]))))
        result["charts"].append(chart("line", "Quarterly revenue", "quarter", [("revenue", "Revenue")],
                                      quarterly_revenue(df)))
    elif "month" in q:
        result["intent"] = "monthly_revenue"
        rows = monthly_revenue(df)
        result["metrics"] = {"monthly_revenue": rows}
        result["tables"].append(_table("Monthly revenue", rows))
        result["charts"].append(chart("line", "Monthly revenue", "month", [("revenue", "Revenue")], rows))
    elif any(w in q for w in ("quarterly", "by quarter", "per quarter", "each quarter", "qoq")):
        result["intent"] = "quarterly_revenue"
        rows = quarterly_revenue(df)
        result["metrics"] = {"quarterly_revenue": rows}
        result["tables"].append(_table("Quarterly revenue", rows))
        result["charts"].append(chart("bar", "Quarterly revenue", "quarter", [("revenue", "Revenue")], rows))
    elif any(w in q for w in ("product", "best", "top", "selling", "highest", "lowest", "item")):
        result["intent"] = "product_performance"
        qtr = quarters[0] if quarters else (last_complete_quarter(df) if ("last quarter" in q or "latest quarter" in q) else None)
        rows = product_performance(df, qtr)
        result["metrics"] = {"quarter": qtr, "products": rows}
        result["tables"].append(_table("Product performance" + (f" ({qtr})" if qtr else ""), rows))
        result["charts"].append(chart("bar", "Revenue by product" + (f" ({qtr})" if qtr else ""),
                                      "product", [("revenue", "Revenue")], rows[:10]))
    elif "quarter" in q and "customer" not in q:
        result["intent"] = "quarterly_revenue"
        rows = quarterly_revenue(df)
        result["metrics"] = {"quarterly_revenue": rows}
        result["tables"].append(_table("Quarterly revenue", rows))
        result["charts"].append(chart("bar", "Quarterly revenue", "quarter", [("revenue", "Revenue")], rows))
    elif "customer" in q:
        result["intent"] = "customers"
        ov = customer_overview(df, customers)
        result["metrics"] = ov
        result["tables"].append(_table("Top customers by revenue", ov["top_customers"]))
        result["charts"].append(chart("bar", "Revenue by region", "region", [("revenue", "Revenue")],
                                      revenue_by_region(df)))
    else:
        result["intent"] = "overview"
        k = kpis(df, customers)
        result["metrics"] = {"kpis": k}
        result["charts"].append(chart("line", "Monthly revenue", "month", [("revenue", "Revenue")],
                                      monthly_revenue(df)))
        result["tables"].append(_table("Top products", product_performance(df, top_n=5)))
    return result


def collect_numbers(obj: Any, acc: set[float] | None = None) -> set[float]:
    """Flatten every number inside a result structure (used to verify numbers in generated text)."""
    acc = set() if acc is None else acc
    if isinstance(obj, bool) or obj is None:
        return acc
    if isinstance(obj, (int, float, np.integer, np.floating)):
        v = float(obj)
        if not np.isnan(v):
            acc.add(round(v, 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_numbers(v, acc)
    return acc
