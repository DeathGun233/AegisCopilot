from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.deps import get_container  # noqa: E402
from app.services.evaluation import EvaluationService  # noqa: E402


def _parse_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _parse_floats(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan retrieval parameters against the logistics evaluation set.")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation" / "parameter_scan_report.json")
    parser.add_argument("--metric", default="recall_at_k")
    parser.add_argument("--top-k", default="3,5,7")
    parser.add_argument("--candidate-k", default="12,20,30")
    parser.add_argument("--keyword-weight", default="0.55")
    parser.add_argument("--semantic-weight", default="0.45")
    parser.add_argument("--rerank-weight", default="0.6")
    parser.add_argument("--min-score", default="0.08")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    container = get_container()
    runs: list[dict] = []
    for top_k, candidate_k, keyword_weight, semantic_weight, rerank_weight, min_score in product(
        _parse_ints(args.top_k),
        _parse_ints(args.candidate_k),
        _parse_floats(args.keyword_weight),
        _parse_floats(args.semantic_weight),
        _parse_floats(args.rerank_weight),
        _parse_floats(args.min_score),
    ):
        if candidate_k < top_k:
            continue
        settings = {
            "top_k": top_k,
            "candidate_k": candidate_k,
            "keyword_weight": keyword_weight,
            "semantic_weight": semantic_weight,
            "rerank_weight": rerank_weight,
            "min_score": min_score,
        }
        container.runtime_retrieval_service.update_settings(**settings)
        run = EvaluationService(
            container.agent_service,
            container.conversations,
            owner_id="admin",
            retrieval=container.retrieval_service,
        ).run()
        metrics = run.model_dump()
        runs.append({"settings": settings, "metrics": metrics})

    best = max(runs, key=lambda item: float(item["metrics"].get(args.metric, 0.0))) if runs else None
    report = {"metric": args.metric, "best": best, "runs": runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
