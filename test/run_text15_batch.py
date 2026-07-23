"""Run the 15 SolidWorksTutorial Web text cases with ComAct, resumably."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil

from run_local_baseline import run_case
from text15_eval import CASES_PATH, load_cases, score_case, shutdown_solidworks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=datetime.now().strftime("text15_%Y%m%d@%H%M%S"))
    parser.add_argument(
        "--result-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "results" / "local_baseline",
    )
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--model", default="Qwen3.5-397B-A17B")
    parser.add_argument("--base-url", default="https://aiping.cn/api")
    parser.add_argument("--api-key-env", default="AIPING_API_KEY")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--max-trajectory-length", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def build_report(run_dir: Path, cases: list[dict]) -> dict:
    results = []
    for case in cases:
        path = run_dir / case["case_id"] / "case_result.json"
        if path.exists():
            results.append(json.loads(path.read_text(encoding="utf-8")))
    scores = [float(item["score"]["score"]) for item in results]
    accepted = sum(bool(item["score"]["acceptance_ok"]) for item in results)
    report = {
        "run_id": run_dir.name,
        "updated_at": datetime.now().isoformat(),
        "completed_cases": len(results),
        "total_cases": len(cases),
        "mean_score": round(sum(scores) / len(scores), 2) if scores else None,
        "acceptance_count": accepted,
        "acceptance_rate": round(accepted / len(results), 4) if results else None,
        "case_results": results,
    }
    (run_dir / "batch_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s %(levelname)s %(name)s] %(message)s",
    )
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Set the {args.api_key_env} environment variable before running.")
    all_cases = load_cases()
    requested = set(args.cases)
    if requested:
        unknown = requested - {case["case_id"] for case in all_cases}
        if unknown:
            raise ValueError(f"Unknown case IDs: {sorted(unknown)}")
        cases = [case for case in all_cases if case["case_id"] in requested]
    else:
        cases = all_cases
    run_dir = args.result_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CASES_PATH, run_dir / "cases_snapshot.json")
    config = {
        "run_id": args.run_id,
        "model": args.model,
        "base_url": args.base_url,
        "max_steps": args.max_steps,
        "max_trajectory_length": args.max_trajectory_length,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "top_p": None if "glm-4.6v" in args.model.lower() else args.top_p,
        "thinking": (
            "provider_default"
            if "glm-4.6v" in args.model.lower()
            else "disabled" if "qwen3.5" in args.model.lower() else "unspecified"
        ),
        "with_example": True,
        "with_rag": False,
        "case_ids": [case["case_id"] for case in cases],
        "scoring_mapping": (
            "Execution uses ComAct CODE subprocess return codes; dimensions, volume, "
            "and details use SolidWorks COM geometry/feature observations."
        ),
    }
    (run_dir / "batch_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutdown_solidworks(timeout=10)
    for index, case in enumerate(cases, 1):
        case_dir = run_dir / case["case_id"]
        result_path = case_dir / "case_result.json"
        if result_path.exists() and not args.force:
            logging.info("[%d/%d] Resume: skipping %s", index, len(cases), case["case_id"])
            continue
        if case_dir.exists() and (args.force or not result_path.exists()):
            shutil.rmtree(case_dir)
        logging.info("[%d/%d] Running %s (%s)", index, len(cases), case["case_id"], case["name"])
        summary = run_case(
            instruction=case["prompt"],
            task_id=case["case_id"],
            api_key=api_key,
            run_dir=case_dir,
            model=args.model,
            base_url=args.base_url,
            max_steps=args.max_steps,
            max_trajectory_length=args.max_trajectory_length,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
        )
        geometry = json.loads((case_dir / "geometry.json").read_text(encoding="utf-8"))
        score = score_case(case, geometry, summary["executions"])
        case_result = {
            "case": case,
            "summary": summary,
            "geometry": geometry,
            "score": score,
        }
        result_path.write_text(
            json.dumps(case_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        build_report(run_dir, cases)
        logging.info(
            "Completed %s: %.2f/100, acceptance=%s, SolidWorks exited=%s",
            case["case_id"],
            score["score"],
            score["acceptance_ok"],
            summary["solidworks_shutdown"].get("exited"),
        )
    report = build_report(run_dir, cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
