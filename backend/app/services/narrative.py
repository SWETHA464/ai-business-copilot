"""Deterministic plain-language descriptions of calculated analytics. Used when no LLM is available (or when an LLM
answer fails number verification), and as the fact sheet an LLM is allowed to paraphrase.

Every number printed here comes straight from the analytics result."""
from __future__ import annotations

from app.services.analytics_service import money


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"


def describe_analytics(result: dict) -> list[str]:
    intent, m = result.get("intent"), result.get("metrics", {})
    out: list[str] = []
    if intent == "overview":
        k = m["kpis"]
        out += [f"Total revenue (completed orders): {money(k['total_revenue'])}.",
                f"Orders: {k['total_orders']:,} in total, {k['completed_orders']:,} completed.",
                f"Customers: {k['total_customers']:,}; average order value {money(k['average_order_value'])}."]
    elif intent == "product_performance":
        label = f" in {m['quarter']}" if m.get("quarter") else ""
        for r in m["products"][:3]:
            out.append(f"#{r['rank']} {r['product']} ({r['category']}): {money(r['revenue'])}{label}, "
                       f"{r['units']:,} units, {r['share_pct']:.1f}% of revenue.")
    elif intent == "quarter_comparison":
        out.append(f"Revenue in {m['current_quarter']} was {money(m['current_revenue'])} versus "
                   f"{money(m['previous_revenue'])} in {m['previous_quarter']} "
                   f"({money(m['change'])}, {_pct(m['change_pct'])}).")
        out.append(f"Completed orders: {m['current_completed_orders']:,} vs {m['previous_completed_orders']:,}; "
                   f"average order value {money(m['current_aov'])} vs {money(m['previous_aov'])}; "
                   f"cancellation rate {m['current_cancellation_rate_pct']:.1f}% vs "
                   f"{m['previous_cancellation_rate_pct']:.1f}%.")
        for r in m["top_decliners"]:
            out.append(f"Declined: {r['product']} {money(r['previous'])} -> {money(r['current'])} "
                       f"({money(r['change'])}, {_pct(r['change_pct'])}).")
        for r in m["top_gainers"][:2]:
            out.append(f"Grew: {r['product']} {money(r['previous'])} -> {money(r['current'])} "
                       f"({money(r['change'])}, {_pct(r['change_pct'])}).")
    elif intent == "monthly_revenue":
        rows = m["monthly_revenue"]
        if rows:
            hi, lo = max(rows, key=lambda r: r["revenue"]), min(rows, key=lambda r: r["revenue"])
            out += [f"Highest month: {hi['month']} ({money(hi['revenue'])}).",
                    f"Lowest month: {lo['month']} ({money(lo['revenue'])}).",
                    f"Latest month in the data: {rows[-1]['month']} ({money(rows[-1]['revenue'])})."]
    elif intent == "quarterly_revenue":
        for r in m["quarterly_revenue"]:
            out.append(f"{r['quarter']}: {money(r['revenue'])} from {r['orders']:,} orders "
                       f"(QoQ {_pct(r['qoq_change_pct'])}).")
    elif intent == "order_status":
        for r in m["order_status"]:
            out.append(f"{r['status']}: {r['orders']:,} orders ({r['share_pct']:.1f}%).")
    elif intent == "customer_segments":
        for r in m["segments"]:
            out.append(f"{r['segment']}: {r['customers']:,} customers ({r['share_pct']:.1f}%), "
                       f"revenue {money(r['revenue'])}.")
    elif intent == "churn":
        out += [f"Churn rate: {m['churn_rate_pct']:.1f}% ({m['churned_customers']:,} of "
                f"{m['customers_with_purchases']:,} purchasing customers).",
                f"Repeat purchase rate: {m['repeat_purchase_rate_pct']:.1f}%.",
                f"Revenue historically from churned customers: {money(m['revenue_from_churned_customers'])}."]
    elif intent == "customers":
        out.append(f"{m['customers_with_purchases']:,} customers have purchased; average "
                   f"{m['avg_orders_per_customer']:.2f} orders and {money(m['avg_revenue_per_customer'])} each.")
        for r in m["top_customers"][:3]:
            out.append(f"Top customer: {r['customer']} ({r['region']}) {money(r['revenue'])} over {r['orders']} orders.")
    return out
