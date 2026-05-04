from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.deps import get_container  # noqa: E402
from app.seed import main as seed_data  # noqa: E402
from app.services.evaluation import EvaluationService  # noqa: E402


def main() -> None:
    seed_data()
    container = get_container()
    run = EvaluationService(container.agent_service, container.conversations, owner_id="admin").run()
    output_path = ROOT / "evaluation" / "latest_report.json"
    output_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps(run.model_dump(), ensure_ascii=False, indent=2))
    print(f"Saved evaluation report to {output_path}")


if __name__ == "__main__":
    main()
