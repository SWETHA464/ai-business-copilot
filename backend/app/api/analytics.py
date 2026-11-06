from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.session import get_db, get_readonly_engine
from app.models import Conversation, Document, Report, User
from app.security.auth import get_current_user
from app.security.rate_limit import general_limit
from app.services import analytics_service as A
from app.services.narrative import describe_analytics

router = APIRouter(prefix="/api", tags=["analytics"], dependencies=[Depends(general_limit)])
EMPTY = "No business data found. Run `python scripts/seed_database.py` to load the sample dataset."


class AnalyticsQuery(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _frames():
    try:
        with get_readonly_engine().connect() as conn:
            return A.load_frames(conn)
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The business database is currently unavailable.")


@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    sales, customers, _ = _frames()
    activity = []
    for c in db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                        .order_by(Conversation.updated_at.desc()).limit(5)):
        activity.append({"type": "conversation", "title": c.title, "at": c.updated_at.isoformat(), "id": c.id})
    for r in db.scalars(select(Report).where(Report.user_id == user.id).order_by(Report.created_at.desc()).limit(5)):
        activity.append({"type": "report", "title": r.title, "at": r.created_at.isoformat(), "id": r.id})
    for d in db.scalars(select(Document).where(Document.owner_id == user.id).order_by(Document.created_at.desc()).limit(5)):
        activity.append({"type": "document", "title": d.filename, "at": d.created_at.isoformat(), "id": d.id})
    activity.sort(key=lambda a: a["at"], reverse=True)
    doc_count = db.scalar(select(func.count(Document.id)).where(Document.status == "ready")) or 0
    base = {"recent_activity": activity[:8], "documents_indexed": int(doc_count)}
    if sales.empty:
        return {**base, "empty": True, "message": EMPTY}
    return {**base, "empty": False, **A.dashboard_summary(sales, customers)}


@router.get("/analytics/revenue")
def revenue(_: User = Depends(get_current_user)) -> dict:
    sales, customers, _p = _frames()
    if sales.empty:
        return {"empty": True, "message": EMPTY}
    monthly, quarterly = A.monthly_revenue(sales), A.quarterly_revenue(sales)
    cmp_ = A.compare_quarters(sales)
    return {
        "empty": False, "monthly": monthly, "quarterly": quarterly,
        "by_category": A.revenue_by_category(sales), "by_region": A.revenue_by_region(sales),
        "comparison": {k: v for k, v in cmp_.items() if k != "products"},
        "charts": [
            A.chart("line", "Monthly revenue", "month", [("revenue", "Revenue")], monthly),
            A.chart("bar", "Quarterly revenue", "quarter", [("revenue", "Revenue")], quarterly),
            A.chart("pie", "Revenue by category", "category", [("revenue", "Revenue")], A.revenue_by_category(sales)),
            A.chart("bar", "Revenue by region", "region", [("revenue", "Revenue")], A.revenue_by_region(sales)),
        ],
        "definitions": {"revenue": A.REVENUE_DEFINITION},
    }


@router.get("/analytics/products")
def products(quarter: str | None = Query(default=None, pattern=r"^20\d{2}-Q[1-4]$"),
             _: User = Depends(get_current_user)) -> dict:
    sales, customers, _p = _frames()
    if sales.empty:
        return {"empty": True, "message": EMPTY}
    rows = A.product_performance(sales, quarter)
    quarters = sorted(sales["quarter"].unique().tolist())
    cmp_ = A.compare_quarters(sales)
    return {
        "empty": False, "quarter": quarter, "available_quarters": quarters, "products": rows,
        "comparison": {"current_quarter": cmp_["current_quarter"], "previous_quarter": cmp_["previous_quarter"],
                       "products": cmp_["products"]},
        "charts": [A.chart("bar", "Revenue by product" + (f" ({quarter})" if quarter else ""), "product",
                           [("revenue", "Revenue")], rows[:10])],
        "definitions": {"revenue": A.REVENUE_DEFINITION},
    }


@router.get("/analytics/customers")
def customers_view(_: User = Depends(get_current_user)) -> dict:
    sales, customers, payments = _frames()
    if sales.empty:
        return {"empty": True, "message": EMPTY}
    seg, churn = A.segment_customers(sales, customers), A.churn_analysis(sales, customers)
    status_rows, pay_rows = A.order_status_breakdown(sales), A.payment_status_breakdown(payments)
    return {
        "empty": False, "segments": seg["segments"], "churn": churn, "order_status": status_rows,
        "payment_status": pay_rows,
        "charts": [A.chart("pie", "Customers by segment", "segment", [("customers", "Customers")], seg["segments"], "number"),
                   A.chart("bar", "Churn rate by region (%)", "region", [("churn_rate_pct", "Churn rate %")],
                           churn["by_region"], "percent"),
                   A.chart("pie", "Orders by status", "status", [("orders", "Orders")], status_rows, "number")],
        "definitions": {"revenue": A.REVENUE_DEFINITION, "churn": A.CHURN_DEFINITION, "segments": seg["definition"]},
    }


@router.post("/analytics/query")
def analytics_query(body: AnalyticsQuery, _: User = Depends(get_current_user)) -> dict:
    sales, customers, payments = _frames()
    if sales.empty:
        return {"empty": True, "message": EMPTY}
    res = A.analyze_question(body.question, sales, customers, payments)
    res["bullets"] = describe_analytics(res)
    return {"empty": False, **res}
