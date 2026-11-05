import re
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from app.database.session import engine
from app.services import analytics_service as A
from app.services.sample_documents import generate_sample_documents
from app.services.seed_data import generate_dataset


def test_dataset_is_deterministic():
    assert generate_dataset(7)["orders"][:5] == generate_dataset(7)["orders"][:5]
    assert generate_dataset(7)["orders"] != generate_dataset(8)["orders"]


def test_foreign_keys_and_row_counts(seeded, dataset):
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        n = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
    assert n == len(dataset["orders"]) > 3000


def test_every_order_has_items_and_one_payment(dataset):
    order_ids = {o["id"] for o in dataset["orders"]}
    assert {i["order_id"] for i in dataset["order_items"]} == order_ids
    assert sorted(p["order_id"] for p in dataset["payments"]) == sorted(order_ids)


def test_payment_amount_matches_order_total(dataset):
    totals = {}
    for i in dataset["order_items"]:
        totals[i["order_id"]] = totals.get(i["order_id"], 0) + i["quantity"] * i["unit_price"] - i["discount"]
    for p in dataset["payments"]:
        assert p["amount"] == pytest.approx(totals[p["order_id"]], abs=0.01)


def test_revenue_counts_only_completed_orders(seeded, dataset):
    sales, customers, _ = seeded
    status = {o["id"]: o["status"] for o in dataset["orders"]}
    expected = sum(i["quantity"] * i["unit_price"] - i["discount"]
                   for i in dataset["order_items"] if status[i["order_id"]] == "completed")
    k = A.kpis(sales, customers)
    assert k["total_revenue"] == pytest.approx(expected, abs=0.01)
    all_status = sum(i["quantity"] * i["unit_price"] - i["discount"] for i in dataset["order_items"])
    assert all_status > k["total_revenue"]  # cancelled/pending/refunded were NOT mixed in
    assert k["completed_orders"] + k["pending_orders"] + k["cancelled_orders"] + k["refunded_orders"] == k["total_orders"]


def test_q3_decline_story(seeded):
    sales, _, _ = seeded
    assert A.last_complete_quarter(sales) == "2026-Q3"
    c = A.compare_quarters(sales)
    assert c["current_quarter"] == "2026-Q3" and c["previous_quarter"] == "2026-Q2"
    assert c["change"] < 0
    assert {d["product"] for d in c["top_decliners"][:2]} == {"Wireless Earbuds Pro", "Smart Home Hub"}
    assert c["current_cancellation_rate_pct"] > c["previous_cancellation_rate_pct"]
    assert sum(r["change"] for r in c["products"]) == pytest.approx(c["change"], abs=0.05)


def test_quarter_helpers():
    assert A.previous_quarter("2026-Q1") == "2025-Q4" and A.previous_quarter("2026-Q3") == "2026-Q2"
    s, e = A.quarter_bounds("2026-Q3")
    assert str(s.date()) == "2026-07-01" and str(e.date()) == "2026-09-30"


def test_churn_definition_on_handcrafted_data():
    def row(oid, cid, d, status, qty=1, price=100.0):
        return dict(order_id=oid, customer_id=cid, order_date=d, status=status, channel="web", region="North",
                    product_id=1, product_name="P", category="C", quantity=qty, unit_price=price, discount=0)

    df = A.build_sales_frame([
        row(1, 1, "2026-09-20", "completed"),   # active
        row(2, 2, "2026-05-01", "completed"),   # churned (>90 days before 2026-09-30)
        row(3, 3, "2026-09-29", "cancelled"),   # never completed -> not a buyer, not churned
        row(4, 1, "2026-09-30", "pending"),
    ])
    customers = pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"], "region": ["North"] * 3,
                              "signup_date": pd.to_datetime(["2026-01-01"] * 3)})
    ch = A.churn_analysis(df, customers)
    assert ch["customers_with_purchases"] == 2 and ch["churned_customers"] == 1 and ch["churn_rate_pct"] == 50.0
    segs = {s["segment"]: s["customers"] for s in A.segment_customers(df, customers)["segments"]}
    assert segs["Churned"] == 1 and segs["No purchases"] == 1
    assert A.kpis(df, customers)["total_revenue"] == 200.0  # pending/cancelled excluded


def test_segments_sum_to_all_customers(seeded):
    sales, customers, _ = seeded
    segs = A.segment_customers(sales, customers)["segments"]
    assert sum(s["customers"] for s in segs) == len(customers)


def test_analyze_question_routing(seeded):
    sales, customers, payments = seeded
    f = lambda q: A.analyze_question(q, sales, customers, payments)["intent"]
    assert f("Why did sales decline last quarter?") == "quarter_comparison"
    assert f("Which five products generated the highest revenue last quarter?") == "product_performance"
    assert f("Show monthly revenue") == "monthly_revenue"
    assert f("customer churn analysis") == "churn"
    assert f("customer segments") == "customer_segments"
    assert f("how many orders were cancelled?") == "order_status"
    r = A.analyze_question("Why did sales decline?", sales, customers)
    assert r["charts"] and r["tables"] and all(c["type"] in ("bar", "line", "pie") for c in r["charts"])


def test_documents_are_consistent_with_database(seeded, tmp_path: Path):
    sales, customers, payments = seeded
    manifest = generate_sample_documents(tmp_path, sales, customers, payments)
    assert {m["filename"] for m in manifest} >= {"Company_Refund_Policy.pdf", "Q3_2026_Sales_Report.docx",
                                                 "Regional_Sales_Summary.csv"}
    c = A.compare_quarters(sales, "2026-Q3", "2026-Q2")
    from docx import Document

    q3 = "\n".join(p.text for p in Document(str(tmp_path / "Q3_2026_Sales_Report.docx")).paragraphs)
    assert A.money(c["current_revenue"]) in q3 and A.money(c["previous_revenue"]) in q3
    assert c["top_decliners"][0]["product"] in q3
    import fitz

    pdf = "".join(pg.get_text() for pg in fitz.open(str(tmp_path / "Company_Refund_Policy.pdf")))
    k = A.kpis(sales, customers)
    assert f"{k['refunded_orders']:,} of {k['total_orders']:,} orders" in re.sub(r"\s+", " ", pdf)
