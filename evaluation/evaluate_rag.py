"""Evaluate the RAG pipeline on evaluation/questions.json and compare retrieval configurations.

Two layers, deliberately separate:

1. Built-in retrieval metrics (always available, no LLM needed, deterministic):
     hit@k          - an expected source document appears in the top-k hits
     mrr            - reciprocal rank of the first expected source document
     fact_recall    - share of key_facts found verbatim (case/space-insensitive) in the retrieved context
     abstain_ok     - for unanswerable questions: retrieval correctly reports insufficient evidence
2. Ragas metrics (optional, `--ragas`): faithfulness, answer relevancy, context precision, context recall.
   Needs `pip install -r evaluation/requirements-eval.txt` and a judge LLM (default: local Ollama).
   Small local models often fail Ragas' structured-output prompts; failed rows are reported, never invented.

Prerequisites: the database is seeded and sample documents are indexed
(`python scripts/seed_database.py`, `create_admin.py`, `index_documents.py`).

Usage (repo root):
    python evaluation/evaluate_rag.py                      # compare all configurations
    python evaluation/evaluate_rag.py --configs hybrid_rerank --ragas
Results are written to evaluation/evaluation_results/ (JSON + Markdown). Nothing is fabricated: scores come only from runs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.rag.retrieval import retrieve, with_config  # noqa: E402

CONFIGS = {
    "bm25_only": dict(use_dense=False, use_bm25=True, use_rerank=False, use_rewrite=False),
    "dense_only": dict(use_dense=True, use_bm25=False, use_rerank=False, use_rewrite=False),
    "hybrid": dict(use_dense=True, use_bm25=True, use_rerank=False, use_rewrite=False),
    "hybrid_rewrite": dict(use_dense=True, use_bm25=True, use_rerank=False, use_rewrite=True),
    "hybrid_rerank": dict(use_dense=True, use_bm25=True, use_rerank=True, use_rewrite=False),
    "full": dict(use_dense=True, use_bm25=True, use_rerank=True, use_rewrite=True),
}
RESULTS = Path(__file__).parent / "evaluation_results"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("–", "-")).strip()


def score_question(item: dict, res, k: int) -> dict:
    hits = res.hits[:k]
    context = norm(" ".join(h.text for h in hits))
    out = {"id": item["id"], "type": item["type"], "n_hits": len(hits), "sufficient": res.sufficient}
    if item["type"] == "unanswerable":
        out["abstain_ok"] = not res.sufficient
        return out
    expected = set(item["expected_sources"])
    rank = next((i for i, h in enumerate(hits, 1) if h.filename in expected), None)
    out["hit"] = rank is not None
    out["rr"] = 1.0 / rank if rank else 0.0
    facts = item["key_facts"]
    out["fact_recall"] = sum(norm(f) in context for f in facts) / len(facts) if facts else None
    out["sources"] = [h.filename for h in hits]
    return out


def aggregate(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["type"] == "answerable"]
    una = [r for r in rows if r["type"] == "unanswerable"]
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
    return {"answerable": len(ans), "unanswerable": len(una),
            "hit_at_k": mean([r["hit"] for r in ans]), "mrr": mean([r["rr"] for r in ans]),
            "fact_recall": mean([r["fact_recall"] for r in ans if r["fact_recall"] is not None]),
            "abstain_accuracy": mean([r["abstain_ok"] for r in una])}


def run_ragas(items: list[dict], contexts: dict[str, list[str]], answers: dict[str, str], judge: str, base_url: str) -> dict:
    """Optional Ragas run. Written against ragas>=0.2; API differences across versions are reported, not hidden."""
    try:
        from langchain_ollama import ChatOllama, OllamaEmbeddings
        from ragas import EvaluationDataset, evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "detail": f"Ragas dependencies missing or incompatible: {exc}. "
                "Run: pip install -r evaluation/requirements-eval.txt"}
    rows = [{"user_input": i["question"], "retrieved_contexts": contexts[i["id"]], "response": answers[i["id"]],
             "reference": i["ground_truth"]} for i in items if i["type"] == "answerable" and contexts.get(i["id"])]
    if not rows:
        return {"status": "no_data", "detail": "No answerable questions produced contexts."}
    llm = LangchainLLMWrapper(ChatOllama(model=judge, base_url=base_url, temperature=0))
    emb = LangchainEmbeddingsWrapper(OllamaEmbeddings(model=judge, base_url=base_url))
    try:
        res = evaluate(EvaluationDataset.from_list(rows),
                       metrics=[Faithfulness(), ResponseRelevancy(), LLMContextPrecisionWithReference(), LLMContextRecall()],
                       llm=llm, embeddings=emb, raise_exceptions=False)
        df = res.to_pandas()
        cols = [c for c in df.columns if c not in ("user_input", "retrieved_contexts", "response", "reference")]
        return {"status": "ok", "judge_model": judge, "rows_scored": len(rows),
                "means": {c: (None if df[c].dropna().empty else round(float(df[c].mean()), 4)) for c in cols},
                "rows_with_missing_scores": {c: int(df[c].isna().sum()) for c in cols}}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "detail": f"Ragas run failed with judge '{judge}': {exc}. "
                "Try a larger judge model (e.g. --judge-model llama3.1:8b)."}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configs", nargs="+", default=list(CONFIGS), choices=list(CONFIGS))
    ap.add_argument("--k", type=int, default=5, help="top-k used when scoring")
    ap.add_argument("--questions", default=str(Path(__file__).parent / "questions.json"))
    ap.add_argument("--ragas", action="store_true", help="also run Ragas (needs eval requirements and a judge LLM)")
    ap.add_argument("--judge-model", default=get_settings().llm_model)
    args = ap.parse_args()

    items = json.loads(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    summary: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "k": args.k, "n_questions": len(items), "configs": {}}
    ragas_inputs: dict = {}

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
        if admin is None:
            print("No admin user found. Run scripts/create_admin.py first.")
            return 2
        probe = retrieve(db, "refund", admin, config=with_config(use_rewrite=False, use_rerank=False))
        if probe.index_size == 0:
            print("The document index is empty. Run scripts/index_documents.py first.")
            return 2
        for name in args.configs:
            cfg = with_config(top_k=max(args.k, 8), **CONFIGS[name])
            rows, t0 = [], time.perf_counter()
            ctxs: dict[str, list[str]] = {}
            for it in items:
                res = retrieve(db, it["question"], admin, config=cfg)
                rows.append(score_question(it, res, args.k))
                ctxs[it["id"]] = [h.text for h in res.hits[:args.k]]
            summary["configs"][name] = {"settings": CONFIGS[name], "metrics": aggregate(rows), "per_question": rows,
                                        "seconds": round(time.perf_counter() - t0, 2)}
            ragas_inputs[name] = ctxs
            m = summary["configs"][name]["metrics"]
            print(f"{name:15s} hit@{args.k}={m['hit_at_k']} mrr={m['mrr']} fact_recall={m['fact_recall']} abstain={m['abstain_accuracy']}")

        if args.ragas:
            from app.agents.rag_agent import answer
            best = args.configs[-1]
            answers = {}
            for it in items:
                if it["type"] != "answerable":
                    continue
                res = retrieve(db, it["question"], admin, config=with_config(**CONFIGS[best]))
                answers[it["id"]] = answer(it["question"], res)["answer"]
            summary["ragas"] = {"config": best, **run_ragas(items, ragas_inputs[best], answers, args.judge_model,
                                                             get_settings().ollama_base_url)}
            print("ragas:", json.dumps(summary["ragas"], indent=2))

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (RESULTS / f"eval_{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = [f"# RAG evaluation {stamp}", "", f"Questions: {len(items)}; scoring top-{args.k}. "
          f"Embedding backend / reranker are whatever the app was configured with when this ran.", "",
          "| Config | hit@k | MRR | fact recall | abstain acc. | seconds |", "|---|---|---|---|---|---|"]
    for n, c in summary["configs"].items():
        m = c["metrics"]
        md.append(f"| {n} | {m['hit_at_k']} | {m['mrr']} | {m['fact_recall']} | {m['abstain_accuracy']} | {c['seconds']} |")
    (RESULTS / f"eval_{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Wrote evaluation/evaluation_results/eval_{stamp}.json and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
