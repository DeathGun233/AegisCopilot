from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "evaluation" / "scan_parameters.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("scan_parameters", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parameter_scan_runs_grid_and_writes_best_report(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()

    class FakeRuntimeRetrieval:
        def update_settings(self, **updates):
            self.settings = updates
            return updates

    class FakeEvaluationService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run(self):
            settings = fake_container.runtime_retrieval_service.settings
            score = 0.7 + settings["top_k"] * 0.01 + settings["candidate_k"] * 0.001
            return SimpleNamespace(
                model_dump=lambda: {
                    "recall_at_k": round(score, 3),
                    "retrieval_citation_accuracy": 0.8,
                    "answer_citation_accuracy": 0.6,
                    "mrr": 0.5,
                    "table_exact_match": 0.4,
                    "version_accuracy": 0.3,
                }
            )

    fake_container = SimpleNamespace(
        runtime_retrieval_service=FakeRuntimeRetrieval(),
        agent_service=object(),
        conversations=object(),
        retrieval_service=object(),
    )
    monkeypatch.setattr(module, "get_container", lambda: fake_container)
    monkeypatch.setattr(module, "EvaluationService", FakeEvaluationService)
    output_path = tmp_path / "scan.json"

    assert module.main(["--output", str(output_path), "--top-k", "3,5", "--candidate-k", "8,12"]) == 0

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["best"]["settings"]["top_k"] == 5
    assert report["best"]["settings"]["candidate_k"] == 12
    assert len(report["runs"]) == 4
    assert report["metric"] == "recall_at_k"
