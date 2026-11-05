"""Generate sample business documents whose figures come from the computed dataset.

Because every number is produced by analytics_service from the same data the SQL agent queries,
the documents can never contradict the database. Qualitative commentary (the "why") is scripted to
match the story baked into seed_data.py. Text is ASCII-only so PDF extraction stays clean.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services import analytics_service as A

Block = tuple  # ("h1"|"h2"|"p"|"bullets"|"table", ...)


def money(x: float) -> str:
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"


# ----------------------------------------------------------------------------- context
def build_context(df: pd.DataFrame, customers: pd.DataFrame, payments: pd.DataFrame) -> dict:
    quarters = {r["quarter"]: r for r in A.quarterly_revenue(df)}
    ctx: dict = {"df": df, "customers": customers, "payments": payments, "quarters": quarters,
                 "kpis": A.kpis(df, customers)}
    for q in ("2026-Q1", "2026-Q2", "2026-Q3"):
        sub = df[df["quarter"] == q]
        prev = A.previous_quarter(q)
        ctx[q] = {
            "cmp": A.compare_quarters(df, q, prev),
            "products": A.product_performance(df, q),
            "categories": A.revenue_by_category(df, q),
            "status": A.order_status_breakdown(df, q),
            "regions": A.revenue_by_region(df, q),
            "orders": A._order_count(sub),
        }
    hub = df[(df["product_name"] == "Smart Home Hub") & (df["order_date"] >= "2026-08-01")].drop_duplicates("order_id")
    ctx["hub_aug_sep_orders"] = int(len(hub))
    ctx["hub_aug_sep_cancel_rate"] = round(100 * (hub["status"] == "cancelled").mean(), 1) if len(hub) else 0.0
    return ctx


# ----------------------------------------------------------------------------- content
def _quarter_report(ctx: dict, q: str) -> tuple[str, list[Block]]:
    n = q.split("-Q")[1]
    c = ctx[q]["cmp"]
    prods = ctx[q]["products"]
    cats = ctx[q]["categories"]
    title = f"Q{n} 2026 Sales Report"
    blocks: list[Block] = [("h1", title),
                           ("p", f"Reporting period: {A.quarter_bounds(q)[0].date()} to {A.quarter_bounds(q)[1].date()}. "
                                 f"Revenue definition: {A.REVENUE_DEFINITION}"),
                           ("h2", "Executive summary")]
    direction = "increased" if c["change"] >= 0 else "declined"
    blocks.append(("p", (
        f"Revenue in Q{n} 2026 was {money(c['current_revenue'])} from {c['current_completed_orders']:,} completed orders. "
        f"Compared with {c['previous_quarter']} ({money(c['previous_revenue'])}), revenue {direction} by "
        f"{money(abs(c['change']))} ({pct(c['change_pct'])}).")))
    blocks.append(("h2", "Key metrics"))
    blocks.append(("table", ["Metric", f"Q{n} 2026", c["previous_quarter"]], [
        ["Revenue", money(c["current_revenue"]), money(c["previous_revenue"])],
        ["Total orders (all statuses)", f"{c['current_orders']:,}", f"{c['previous_orders']:,}"],
        ["Completed orders", f"{c['current_completed_orders']:,}", f"{c['previous_completed_orders']:,}"],
        ["Average order value", money(c["current_aov"]), money(c["previous_aov"])],
        ["Cancellation rate", f"{c['current_cancellation_rate_pct']:.1f}%", f"{c['previous_cancellation_rate_pct']:.1f}%"],
    ]))
    blocks.append(("h2", "Top products by revenue"))
    blocks.append(("table", ["Rank", "Product", "Revenue", "Units"],
                   [[str(p["rank"]), p["product"], money(p["revenue"]), str(p["units"])] for p in prods[:5]]))
    blocks.append(("h2", "Revenue by category"))
    blocks.append(("bullets", [f"{x['category']}: {money(x['revenue'])}" for x in cats]))

    blocks.append(("h2", "Product movements versus " + c["previous_quarter"]))
    if c["top_decliners"]:
        blocks.append(("bullets", [
            f"{d['product']}: {money(d['change'])} ({pct(d['change_pct'])}), "
            f"{d['share_of_total_change_pct']:.0f}% of the total change" for d in c["top_decliners"]]))
    if c["top_gainers"]:
        blocks.append(("p", "Products that grew: " + "; ".join(
            f"{g['product']} ({money(g['change'])}, {pct(g['change_pct'])})" for g in c["top_gainers"]) + "."))

    blocks.append(("h2", "Management commentary"))
    if q == "2026-Q1":
        blocks.append(("p", "Q1 followed the holiday quarter, and a post-holiday slowdown was expected. No company-wide "
                            "promotion ran during the quarter. Demand was steady for accessories and fitness products, "
                            "while high-ticket electronics softened after the Black Friday and December peaks."))
        recs = ["Plan a spring promotion for late April to lift Q2 demand.",
                "Keep inventory of Wireless Earbuds Pro and Smart Home Hub healthy ahead of Q2."]
    elif q == "2026-Q2":
        blocks.append(("p", "Q2 was the strongest quarter in the reporting year. A spring promotion (10% discount, "
                            "28 April to 12 May 2026) drove higher volumes. Wireless Earbuds Pro and Smart Home Hub "
                            "outperformed expectations and were the main contributors to growth."))
        recs = ["Review promotion depth: volume grew, but margin impact should be tracked.",
                "Secure supplier capacity for Smart Home Hub for the second half of the year."]
    else:
        blocks.append(("p", (
            "Q3 revenue declined against Q2. The decline is concentrated in two products. "
            "(1) Wireless Earbuds Pro lost demand after the spring promotion ended and competitors cut prices on "
            "comparable earbuds. (2) Smart Home Hub suffered supply shortages from August onward; stock-outs reduced "
            f"order volume and raised cancellations ({ctx['hub_aug_sep_orders']} Hub orders in Aug-Sep, "
            f"{ctx['hub_aug_sep_cancel_rate']:.1f}% cancelled). The overall cancellation rate rose from "
            f"{c['previous_cancellation_rate_pct']:.1f}% in Q2 to {c['current_cancellation_rate_pct']:.1f}% in Q3.")))
        blocks.append(("p", "Other categories were broadly stable. Smart Air Fryer XL benefited from steady kitchen demand."))
        recs = ["Expedite replenishment of Smart Home Hub and communicate realistic delivery dates to customers.",
                "Evaluate a price-match or bundle offer for Wireless Earbuds Pro.",
                "Track cancellations weekly until the Smart Home Hub supply issue is resolved."]
    blocks.append(("h2", "Recommended actions"))
    blocks.append(("bullets", recs))
    return title, blocks


def _refund_policy(ctx: dict) -> tuple[str, list[Block]]:
    k = ctx["kpis"]
    return "Company Refund Policy", [
        ("h1", "Company Refund Policy"),
        ("p", "This policy applies to all orders placed on our web store, mobile app and marketplace channels. "
              "Effective date: 1 October 2025."),
        ("h2", "1. Eligibility"),
        ("bullets", [
            "Customers may request a refund within 30 days of delivery.",
            "Unopened items in original packaging are eligible for a full refund.",
            "Opened non-defective electronics may be returned within 14 days and are subject to a 10% restocking fee.",
            "Defective or damaged items are refunded in full, including shipping, within 30 days of delivery.",
            "Fitness equipment must be unused, with all original parts, to qualify for a full refund.",
        ]),
        ("h2", "2. Cancellations"),
        ("p", "Orders can be cancelled free of charge before they are dispatched. If an item is out of stock or "
              "delayed, we will notify the customer and offer either a cancellation with a full refund or a backorder."),
        ("h2", "3. Processing"),
        ("bullets", [
            "Approved refunds are issued to the original payment method within 7 business days.",
            "Bank transfers can take up to 10 business days to appear.",
            "Standard shipping fees are non-refundable unless the item was defective or sent in error.",
        ]),
        ("h2", "4. Non-refundable items"),
        ("p", "Gift cards and items marked final sale cannot be refunded. Items returned without a return "
              "authorization number may be refused."),
        ("h2", "5. Refund activity (October 2025 to September 2026)"),
        ("p", f"{k['refunded_orders']:,} of {k['total_orders']:,} orders ({k['refund_rate_pct']:.1f}%) were refunded, "
              f"with a refunded order value of {money(k['refunded_value'])}. "
              f"{k['cancelled_orders']:,} orders ({k['cancellation_rate_pct']:.1f}%) were cancelled."),
        ("h2", "6. Contact"),
        ("p", "Requests are handled by the Customer Support team. See the Customer Support Guidelines for response targets."),
    ]


def _retention(ctx: dict) -> tuple[str, list[Block]]:
    df, cu = ctx["df"], ctx["customers"]
    ch = A.churn_analysis(df, cu)
    seg = A.segment_customers(df, cu)
    return "Customer Retention Strategy", [
        ("h1", "Customer Retention Strategy"),
        ("h2", "Situation"),
        ("p", f"As of {ch['reference_date']}, {ch['churned_customers']:,} of {ch['customers_with_purchases']:,} customers "
              f"with purchases are churned ({ch['churn_rate_pct']:.1f}%). {A.CHURN_DEFINITION} "
              f"The repeat purchase rate is {ch['repeat_purchase_rate_pct']:.1f}%. Churned customers generated "
              f"{money(ch['revenue_from_churned_customers'])} in lifetime revenue."),
        ("h2", "Segment sizes"),
        ("table", ["Segment", "Customers", "Share", "Revenue"],
         [[s["segment"], str(s["customers"]), f"{s['share_pct']:.1f}%", money(s["revenue"])] for s in seg["segments"]]),
        ("p", seg["definition"]),
        ("h2", "Tactics by segment"),
        ("bullets", [
            "Champions: early access to new launches and a loyalty tier with free expedited shipping.",
            "Loyal: personalised replenishment reminders and bundle offers.",
            "Recent / new: a welcome series and a second-purchase incentive within 30 days.",
            "At risk (46-90 days since last order): win-back email with a time-limited 10% offer before they reach 90 days.",
            "Churned: a quarterly reactivation campaign and a short survey on reasons for leaving.",
        ]),
        ("h2", "Targets (goals, not results)"),
        ("bullets", ["Reduce the churn rate by 5 percentage points over the next two quarters.",
                     "Increase the repeat purchase rate by 5 percentage points.",
                     "Contact every At risk customer before day 90."]),
        ("h2", "Known drivers"),
        ("p", "Customers affected by Smart Home Hub cancellations in August and September 2026 are at higher risk and "
              "should receive proactive outreach with a delivery update or an alternative product."),
    ]


def _product_report(ctx: dict) -> tuple[str, list[Block]]:
    df = ctx["df"]
    prods = A.product_performance(df)
    cats = A.revenue_by_category(df)
    c3 = ctx["2026-Q3"]["cmp"]
    return "Product Performance Report", [
        ("h1", "Product Performance Report"),
        ("p", "Period: October 2025 to September 2026 (all four quarters in the dataset). " + A.REVENUE_DEFINITION),
        ("h2", "Revenue by product"),
        ("table", ["Rank", "Product", "Category", "Revenue", "Units", "Share"],
         [[str(p["rank"]), p["product"], p["category"], money(p["revenue"]), str(p["units"]), f"{p['share_pct']:.1f}%"]
          for p in prods]),
        ("h2", "Revenue by category"),
        ("bullets", [f"{x['category']}: {money(x['revenue'])}" for x in cats]),
        ("h2", "Quarter-over-quarter highlights (2026-Q3 vs 2026-Q2)"),
        ("bullets", [f"{d['product']}: {money(d['change'])} ({pct(d['change_pct'])})" for d in c3["top_decliners"]]
         + [f"{g['product']}: {money(g['change'])} ({pct(g['change_pct'])})" for g in c3["top_gainers"]]),
        ("h2", "Notes"),
        ("p", "Wireless Earbuds Pro and Smart Home Hub were the largest contributors to both the Q2 peak and the Q3 decline. "
              "Smart Home Hub performance in Q3 was constrained by supply shortages, not by weak customer interest."),
    ]


def _marketing(ctx: dict) -> tuple[str, list[Block]]:
    df = ctx["df"]
    o = df.drop_duplicates("order_id")
    ch = o.groupby("channel").size()
    total = int(ch.sum()) or 1
    return "Marketing Strategy", [
        ("h1", "Marketing Strategy"),
        ("h2", "Channel mix"),
        ("p", "Share of orders by channel in the reporting year: " + ", ".join(
            f"{c} {100 * n / total:.1f}%" for c, n in ch.sort_values(ascending=False).items()) + "."),
        ("h2", "Promotion calendar"),
        ("bullets", ["Black Friday week (24-30 November 2025): 15% discount on all products.",
                     "Spring promotion (28 April - 12 May 2026): 10% discount; the largest uplift was in "
                     "Wireless Earbuds Pro and Smart Home Hub.",
                     "No promotions ran in Q1 2026 or in Q3 2026."]),
        ("h2", "Priorities for the next quarter"),
        ("bullets", ["Respond to competitor pricing on Wireless Earbuds Pro with a bundle offer rather than a deep discount.",
                     "Pause paid advertising for Smart Home Hub until stock is replenished to avoid cancellations.",
                     "Prepare the Black Friday and holiday campaign, focusing on gift bundles.",
                     "Grow the mobile app channel through push notifications to existing customers."]),
        ("h2", "Measurement"),
        ("p", "Campaign results are measured on completed-order revenue, customer acquisition cost and the repeat "
              "purchase rate. Cancelled, pending and refunded orders are never counted as revenue."),
    ]


def _support(ctx: dict) -> tuple[str, list[Block]]:
    return "Customer Support Guidelines", [
        ("h1", "Customer Support Guidelines"),
        ("h2", "Response targets"),
        ("bullets", ["First response within 4 business hours.",
                     "Resolution of standard requests within 2 business days.",
                     "Refund requests acknowledged the same business day."]),
        ("h2", "Handling refund and return requests"),
        ("p", "Follow the Company Refund Policy: 30 days from delivery, 14 days for opened non-defective electronics "
              "with a 10% restocking fee. Escalate exceptions to a team lead."),
        ("h2", "Handling cancellations and stock-outs"),
        ("p", "When an item is out of stock, tell the customer the expected restock date if known, and offer a "
              "cancellation with full refund or a backorder. Smart Home Hub orders placed since August 2026 are "
              "subject to delays; use the approved delay message template."),
        ("h2", "Escalation"),
        ("bullets", ["Level 1: support agent.", "Level 2: team lead for refunds above $500 or repeated complaints.",
                     "Level 3: operations manager for supply issues and chargebacks."]),
        ("h2", "Security"),
        ("p", "Never ask customers for full card numbers or passwords. Verify identity using order number and email."),
    ]


def regional_csv(ctx: dict) -> str:
    df = ctx["df"]
    comp = A.completed(df)
    g = comp.groupby(["region", "quarter"]).agg(revenue=("line_revenue", "sum"),
                                                orders=("order_id", "nunique")).reset_index()
    lines = ["region,quarter,revenue,completed_orders"]
    for r in g.itertuples():
        lines.append(f"{r.region},{r.quarter},{r.revenue:.2f},{r.orders}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- writers
def write_txt(path: Path, blocks: list[Block]) -> None:
    out: list[str] = []
    for b in blocks:
        kind = b[0]
        if kind == "h1":
            out += [b[1].upper(), "=" * len(b[1]), ""]
        elif kind == "h2":
            out += [b[1], "-" * len(b[1])]
        elif kind == "p":
            out += [b[1], ""]
        elif kind == "bullets":
            out += [f"- {x}" for x in b[1]] + [""]
        elif kind == "table":
            out.append(" | ".join(b[1]))
            out += [" | ".join(r) for r in b[2]] + [""]
    path.write_text("\n".join(out), encoding="utf-8")


def write_docx(path: Path, blocks: list[Block]) -> None:
    from docx import Document

    doc = Document()
    for b in blocks:
        kind = b[0]
        if kind == "h1":
            doc.add_heading(b[1], level=1)
        elif kind == "h2":
            doc.add_heading(b[1], level=2)
        elif kind == "p":
            doc.add_paragraph(b[1])
        elif kind == "bullets":
            for x in b[1]:
                doc.add_paragraph(x, style="List Bullet")
        elif kind == "table":
            t = doc.add_table(rows=1, cols=len(b[1]))
            t.style = "Light Grid Accent 1"
            for i, h in enumerate(b[1]):
                t.rows[0].cells[i].text = h
            for r in b[2]:
                cells = t.add_row().cells
                for i, v in enumerate(r):
                    cells[i].text = str(v)
    doc.save(str(path))


def write_pdf(path: Path, blocks: list[Block]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    story = []
    for b in blocks:
        kind = b[0]
        if kind == "h1":
            story += [Paragraph(b[1], styles["Title"]), Spacer(1, 8)]
        elif kind == "h2":
            story += [Spacer(1, 6), Paragraph(b[1], styles["Heading2"])]
        elif kind == "p":
            story += [Paragraph(b[1].replace("&", "&amp;"), styles["BodyText"]), Spacer(1, 4)]
        elif kind == "bullets":
            story.append(ListFlowable([ListItem(Paragraph(x.replace("&", "&amp;"), styles["BodyText"])) for x in b[1]],
                                      bulletType="bullet"))
        elif kind == "table":
            data = [b[1]] + [[Paragraph(str(v).replace("&", "&amp;"), styles["BodyText"]) for v in r] for r in b[2]]
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                   ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [t, Spacer(1, 6)]
    SimpleDocTemplate(str(path), pagesize=LETTER, title=blocks[0][1]).build(story)


# ----------------------------------------------------------------------------- orchestration
def generate_sample_documents(out_dir: Path, df: pd.DataFrame, customers: pd.DataFrame,
                              payments: pd.DataFrame) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = build_context(df, customers, payments)
    manifest: list[dict] = []

    def add(filename: str, writer, blocks, category: str, department: str):
        writer(out_dir / filename, blocks)
        manifest.append({"filename": filename, "category": category, "department": department})

    add("Company_Refund_Policy.pdf", write_pdf, _refund_policy(ctx)[1], "policy", "support")
    for q, name in (("2026-Q1", "Q1_2026_Sales_Report.docx"), ("2026-Q2", "Q2_2026_Sales_Report.docx"),
                    ("2026-Q3", "Q3_2026_Sales_Report.docx")):
        add(name, write_docx, _quarter_report(ctx, q)[1], "sales_report", "sales")
    add("Customer_Retention_Strategy.txt", write_txt, _retention(ctx)[1], "strategy", "marketing")
    add("Product_Performance_Report.pdf", write_pdf, _product_report(ctx)[1], "sales_report", "sales")
    add("Marketing_Strategy.txt", write_txt, _marketing(ctx)[1], "strategy", "marketing")
    add("Customer_Support_Guidelines.txt", write_txt, _support(ctx)[1], "policy", "support")
    csv_name = "Regional_Sales_Summary.csv"
    (out_dir / csv_name).write_text(regional_csv(ctx), encoding="utf-8")
    manifest.append({"filename": csv_name, "category": "sales_report", "department": "sales"})
    return manifest
