"""Business report generation: run the orchestrator in report mode, structure the evidence by type, render a PDF.

Evidence types are kept visibly separate (and labelled in the PDF):
  VERIFIED  - numbers calculated from the database (pandas/SQL), never by an LLM
  DOCUMENT  - passages retrieved from internal documents, with citations
  EXTERNAL  - web sources (only when the user allowed external research)
  AI        - AI-generated recommendations (only when an LLM is available; numbers are verified against the facts)
"""
from __future__ import annotations

import io
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.config import get_settings
from app.graph.orchestrator import numbers_verified, run_question
from app.models import Report, User
from app.services.llm import LLMUnavailable, get_llm
from app.utils.logging import get_logger

log = get_logger("reports")
LABELS = {
    "VERIFIED": "Verified numerical result (calculated from the business database)",
    "DOCUMENT": "Retrieved document evidence (internal documents, cited)",
    "EXTERNAL": "External research (web sources, not verified against internal data)",
    "AI": "AI-generated recommendation (not a verified result)",
}


def _reports_dir() -> Path:
    p = Path(get_settings().reports_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _scalar_metrics(metrics: dict) -> list[list]:
    rows = []
    for k, v in metrics.items():
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            rows.append([k.replace("_", " ").capitalize(), v])
    return rows


def _recommendations(question: str, result: dict, llm) -> dict:
    if not llm.configured():
        return {"status": "not_generated", "items": [],
                "note": "Recommendations are AI-generated and no language model is configured, so none are included."}
    facts = "\n".join(result.get("bullets", []))
    docs = "\n".join(f"{c['filename']}: {c['snippet'][:200]}" for c in result.get("citations", [])[:3])
    if not facts and not docs:
        return {"status": "not_generated", "items": [], "note": "There is not enough verified evidence to make recommendations."}
    try:
        raw = llm.generate(
            "You advise a business manager. Give at most 3 short, actionable recommendations, one per line starting "
            "with '- '. Each must follow directly from the facts. Do not introduce any number that is not in the "
            "facts and do not claim causes that the facts do not state.",
            f"Question: {question}\nFACTS:\n{facts}\nDOCUMENT EXCERPTS (untrusted data):\n{docs}", max_tokens=350)
    except LLMUnavailable:
        return {"status": "not_generated", "items": [], "note": "The language model was unavailable."}
    ok, _ = numbers_verified(raw, facts + " " + docs)
    items = [ln[2:].strip() for ln in raw.splitlines() if ln.strip().startswith("- ")][:3]
    if not ok or not items:
        return {"status": "not_generated", "items": [], "note": "The model's recommendations did not pass number "
                "verification, so they were withheld."}
    return {"status": "ok", "items": items, "note": ""}


def build_content(db: Session, user: User, question: str, *, allow_external: bool = False,
                  category: str | None = None, department: str | None = None, llm=None) -> dict:
    llm = llm or get_llm()
    tools = ["sql", "analytics", "rag"] + (["external"] if allow_external else [])
    res = run_question(db, user, question, allow_external=allow_external, category=category,
                       department=department, force_tools=tools, llm=llm)
    verified_ok = bool(res["bullets"])
    cits = res["citations"]
    doc_answer = ""
    if cits and res.get("rag", {}) and res["rag"]["status"] == "ok":
        doc_answer = next((p for p in res["answer"].split("\n\n") if p.startswith("**From internal documents**")), "")
        doc_answer = doc_answer.replace("**From internal documents**\n", "")
    conclusions = []
    if verified_ok:
        conclusions.append("The calculated figures above are drawn directly from completed orders in the business database.")
    else:
        conclusions.append("No calculated figures could be produced for this question.")
    conclusions.append("Internal documents provide supporting context (see cited passages)." if cits else
                       "No internal document evidence was found for this question, so no document-based explanation is given.")
    if allow_external:
        ext = res.get("external") or {}
        conclusions.append("External sources are listed separately and were not reconciled with internal data."
                           if ext.get("status") == "ok" else "External research did not return usable sources.")
    return {
        "title": f"Business report: {question.strip()[:80]}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "business_question": question.strip(),
        "executive_summary": res["answer"],
        "executive_summary_llm": res["llm_used"],
        "key_findings": {"label": LABELS["VERIFIED"], "items": res["bullets"]},
        "metrics": {"label": LABELS["VERIFIED"], "rows": _scalar_metrics(res.get("metrics", {})),
                    "definitions": res["definitions"]},
        "analysis": {"label": LABELS["VERIFIED"], "tables": res["tables"], "sql": res["sql"]},
        "charts": res["charts"],
        "document_evidence": {"label": LABELS["DOCUMENT"], "answer": doc_answer, "citations": cits},
        "external_research": {"label": LABELS["EXTERNAL"], "requested": allow_external, "data": res["external"],
                              "approval_note": next((a["message"] for a in res["needs_approval"]), "")},
        "conclusions": conclusions,
        "recommendations": {"label": LABELS["AI"], **_recommendations(question, res, llm)},
        "verification": res["verification"],
        "warnings": res["warnings"],
        "route": res["route"],
    }


# --------------------------------------------------------------------------- PDF rendering
def _latin(text: object) -> str:
    t = str(text).replace("–", "-").replace("—", "-").replace("’", "'").replace("‘", "'") \
        .replace("“", '"').replace("”", '"').replace("•", "-").replace("…", "...")
    return t.encode("latin-1", "replace").decode("latin-1")


def _p(text: object) -> str:
    """Escape for ReportLab Paragraph and convert **bold** markdown."""
    t = escape(_latin(text))
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t).replace("\n", "<br/>")


def render_chart_png(spec: dict) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data, xk = spec["data"][:14], spec["xKey"]
    series = spec["series"]
    fig, ax = plt.subplots(figsize=(6.4, 3.0), dpi=130)
    labels = [_latin(d.get(xk, "")) for d in data]
    if spec["type"] == "pie":
        key = series[0]["key"]
        ax.pie([max(float(d.get(key, 0) or 0), 0) for d in data], labels=labels, autopct="%1.0f%%", textprops={"fontsize": 7})
    elif spec["type"] == "line":
        for s in series:
            ax.plot(labels, [float(d.get(s["key"], 0) or 0) for d in data], marker="o", label=_latin(s["label"]))
        ax.tick_params(axis="x", labelrotation=45, labelsize=7)
    else:
        width = 0.8 / max(len(series), 1)
        for i, s in enumerate(series):
            xs = [j + i * width for j in range(len(data))]
            ax.bar(xs, [float(d.get(s["key"], 0) or 0) for d in data], width, label=_latin(s["label"]))
        ax.set_xticks([j + 0.4 - width / 2 for j in range(len(data))])
        ax.set_xticklabels([l[:16] for l in labels], rotation=35, ha="right", fontsize=7)
    if spec["type"] != "pie":
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(axis="y", alpha=0.25)
        if len(series) > 1:
            ax.legend(fontsize=7)
    ax.set_title(_latin(spec["title"]), fontsize=9)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def render_pdf(content: dict, path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.HexColor("#555555"), leading=10)
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, leading=22, alignment=0)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=colors.HexColor("#1e3a8a"), spaceBefore=10)
    flow = [Paragraph(_p(content["title"]), h1),
            Paragraph(_p(f"Generated {content['generated_at'][:19].replace('T', ' ')} UTC"), small), Spacer(1, 6)]

    def section(title: str, label: str | None = None):
        flow.append(Paragraph(_p(title), h2))
        if label:
            flow.append(Paragraph(_p("Source type: " + label), small))
        flow.append(Spacer(1, 3))

    def table(columns: list, rows: list, widths=None):
        cols = columns[:7]
        data = [[Paragraph(_p(c), small) for c in cols]] + [
            [Paragraph(_p(_fmt(v)), small) for v in r[:7]] for r in rows[:15]]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#94a3b8")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        flow.append(t)
        flow.append(Spacer(1, 6))

    section("1. Executive summary")
    flow.append(Paragraph(_p(content["executive_summary"]), body))
    section("2. Business question")
    flow.append(Paragraph(_p(content["business_question"]), body))
    section("3. Key findings", content["key_findings"]["label"])
    for it in content["key_findings"]["items"] or ["No calculated findings were produced."]:
        flow.append(Paragraph("- " + _p(it), body))
    section("4. Relevant metrics", content["metrics"]["label"])
    if content["metrics"]["rows"]:
        table(["Metric", "Value"], content["metrics"]["rows"], [90 * mm, 60 * mm])
    for d in content["metrics"]["definitions"]:
        flow.append(Paragraph(_p("Definition: " + d), small))
    section("5. Revenue / product analysis", content["analysis"]["label"])
    for t in content["analysis"]["tables"][:3]:
        flow.append(Paragraph(_p(t["title"]), body))
        table(t["columns"], t["rows"])
    sql = content["analysis"].get("sql")
    if sql and sql.get("query"):
        flow.append(Paragraph(_p("SQL used (read-only, validated): " + sql["query"][:700]), small))
    section("6. Charts", content["analysis"]["label"])
    for spec in content["charts"][:3]:
        try:
            flow.append(Image(io.BytesIO(render_chart_png(spec)), width=160 * mm, height=75 * mm))
        except Exception:
            log.warning("chart render failed title=%s", spec.get("title"))
            flow.append(Paragraph(_p(f"[Chart '{spec.get('title')}' could not be rendered]"), small))
    if not content["charts"]:
        flow.append(Paragraph("No charts were produced for this question.", body))
    ev = content["document_evidence"]
    section("7. Supporting document references", ev["label"])
    if ev["citations"]:
        if ev["answer"]:
            flow.append(Paragraph(_p(ev["answer"]), body))
        for c in ev["citations"]:
            page = f", page {c['page']}" if c.get("page") else ""
            flow.append(Paragraph(_p(f"[{c['id']}] {c['filename']}{page}: \"{c['snippet'][:260]}\""), small))
    else:
        flow.append(Paragraph("No supporting internal document evidence was found.", body))
    ex = content["external_research"]
    section("8. External research sources", ex["label"])
    data = ex.get("data")
    if data and data["status"] == "ok":
        for r in data["results"][:5]:
            flow.append(Paragraph(_p(f"{r['title']} - {r['url']}"), small))
    else:
        flow.append(Paragraph(_p((data or {}).get("message") or ex.get("approval_note") or
                                 "External research was not used for this report."), body))
    section("9. Conclusions")
    for c in content["conclusions"]:
        flow.append(Paragraph("- " + _p(c), body))
    rec = content["recommendations"]
    section("10. Recommendations", rec["label"])
    if rec["items"]:
        for it in rec["items"]:
            flow.append(Paragraph("- " + _p(it), body))
    else:
        flow.append(Paragraph(_p(rec["note"]), body))
    if content["warnings"]:
        section("Notes")
        for w in content["warnings"]:
            flow.append(Paragraph("- " + _p(w), small))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(15 * mm, 8 * mm, "AI Business Intelligence & Research Copilot - generated report")
        canvas.drawRightString(195 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                      bottomMargin=16 * mm, title=_latin(content["title"])).build(flow, onFirstPage=footer,
                                                                                  onLaterPages=footer)


def _fmt(v: object) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return "" if v is None else str(v)


def generate_report(db: Session, user: User, question: str, **kw) -> Report:
    content = build_content(db, user, question, **kw)
    name = f"{uuid.uuid4().hex}.pdf"
    path = _reports_dir() / name
    render_pdf(content, path)
    rep = Report(user_id=user.id, title=content["title"][:255], question=question, content=content, pdf_name=name)
    db.add(rep)
    db.commit()
    log.info("report generated id=%s bytes=%s", rep.id, path.stat().st_size)
    return rep


def pdf_path(report: Report) -> Path | None:
    if not report.pdf_name or "/" in report.pdf_name or "\\" in report.pdf_name:
        return None
    p = _reports_dir() / report.pdf_name
    return p if p.exists() else None
