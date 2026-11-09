"""Checks the evaluation harness itself: dataset integrity and metric arithmetic (no LLM, no index needed)."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_FILES = {"Company_Refund_Policy.pdf", "Q1_2026_Sales_Report.docx", "Q2_2026_Sales_Report.docx",
                "Q3_2026_Sales_Report.docx", "Customer_Retention_Strategy.txt", "Product_Performance_Report.pdf",
                "Marketing_Strategy.txt", "Customer_Support_Guidelines.txt", "Regional_Sales_Summary.csv"}


def _load():
    spec = importlib.util.spec_from_file_location("evaluate_rag", ROOT / "evaluation" / "evaluate_rag.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_questions_are_well_formed():
    items = json.loads((ROOT / "evaluation" / "questions.json").read_text(encoding="utf-8"))["questions"]
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    for i in items:
        assert i["type"] in ("answerable", "unanswerable")
        if i["type"] == "answerable":
            assert i["key_facts"] and i["ground_truth"]
            assert set(i["expected_sources"]) <= SAMPLE_FILES
    assert any(i["type"] == "unanswerable" for i in items)


def test_scoring_and_aggregation():
    ev = _load()
    hit = lambda name, text: SimpleNamespace(filename=name, text=text)  # noqa: E731
    item = {"id": "x", "type": "answerable", "expected_sources": ["A.txt"], "key_facts": ["30 days", "full refund"]}
    res = SimpleNamespace(hits=[hit("B.txt", "unrelated"), hit("A.txt", "Within  30 Days you get a FULL refund")], sufficient=True)
    r = ev.score_question(item, res, k=5)
    assert r["hit"] and r["rr"] == 0.5 and r["fact_recall"] == 1.0
    miss = ev.score_question(item, SimpleNamespace(hits=[hit("B.txt", "nothing")], sufficient=True), k=5)
    assert miss["hit"] is False and miss["fact_recall"] == 0.0
    una = {"id": "u", "type": "unanswerable"}
    ok = ev.score_question(una, SimpleNamespace(hits=[], sufficient=False), k=5)
    assert ok["abstain_ok"] is True
    agg = ev.aggregate([r, miss, ok])
    assert agg["hit_at_k"] == 0.5 and agg["abstain_accuracy"] == 1.0


def test_relative_sqlite_path_is_anchored_to_repo_root():
    from app.config import REPO_ROOT, Settings

    s = Settings(database_url="sqlite:///./data/app.db")
    assert s.database_url == f"sqlite:///{(REPO_ROOT / 'data' / 'app.db').resolve().as_posix()}"
    absolute = Settings(database_url="sqlite:////tmp/x.db")
    assert absolute.database_url == "sqlite:////tmp/x.db"
