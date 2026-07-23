"""Recompute Text15 scores from saved trajectories and geometry snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_text15_batch import build_report
from text15_eval import load_cases, score_case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    snapshot = run_dir / "cases_snapshot.json"
    cases = (
        json.loads(snapshot.read_text(encoding="utf-8"))
        if snapshot.exists()
        else load_cases()
    )
    rescored = 0
    for case in cases:
        case_dir = run_dir / case["case_id"]
        summary_path = case_dir / "summary.json"
        geometry_path = case_dir / "geometry.json"
        if not summary_path.exists() or not geometry_path.exists():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
        result = {
            "case": case,
            "summary": summary,
            "geometry": geometry,
            "score": score_case(case, geometry, summary.get("executions") or []),
        }
        (case_dir / "case_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rescored += 1
    report = build_report(run_dir, cases)
    print(
        json.dumps(
            {"rescored_cases": rescored, "batch_report": report},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
