"""Run the original ComAct PromptAgent loop against local SolidWorks.

This keeps the repository's prompt, response parsing, trajectory context, and
CODE/DONE/FAIL behavior. Only the missing ROCK/VM transport is replaced by
`local_env.LocalDesktopEnv`.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import traceback

from agent import PromptAgent
from lib_run_single import save_obs
from local_env import LocalDesktopEnv
from text15_eval import collect_geometry_and_export, shutdown_solidworks


logger = logging.getLogger("myexp.run_local_baseline")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--task-id", default="local_baseline_001")
    parser.add_argument("--model", default="Qwen3.5-397B-A17B")
    parser.add_argument("--base-url", default="https://aiping.cn/api")
    parser.add_argument("--api-key-env", default="AIPING_API_KEY")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--max-trajectory-length", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "results" / "local_baseline",
    )
    return parser.parse_args()


def run_case(
    *,
    instruction: str,
    task_id: str,
    api_key: str,
    run_dir: Path,
    model: str = "Qwen3.5-397B-A17B",
    base_url: str = "https://aiping.cn/api",
    max_steps: int = 6,
    max_trajectory_length: int = 1,
    max_tokens: int = 8192,
    temperature: float = 0.2,
    top_p: float = 0.9,
) -> dict:
    """Run one reproducible ComAct case and preserve its complete trajectory."""
    run_dir.mkdir(parents=True, exist_ok=True)
    execution_workspace = run_dir / "execution"

    task_config = {
        "id": task_id,
        "instruction": "Model this part in Solidworks: " + instruction,
        "close_window": True,
    }

    agent = PromptAgent(
        model=model,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        max_steps=max_steps,
        max_trajectory_length=max_trajectory_length,
        api_server="claudeshop",
        base_url=base_url,
        api_key=api_key,
        with_example=True,
        task_type="3d_model",
        software="sldworks",
        with_rag=False,
    )
    env = LocalDesktopEnv(execution_workspace)

    started_at = datetime.now()
    trajectory_path = run_dir / "traj.jsonl"
    (run_dir / "prompt.txt").write_text(instruction, encoding="utf-8")
    (run_dir / "full_instruction.txt").write_text(
        task_config["instruction"], encoding="utf-8"
    )
    (run_dir / "system_prompt.txt").write_text(
        agent.system_message, encoding="utf-8"
    )
    run_config = {
        "task_id": task_id,
        "model": model,
        "base_url": base_url,
        "max_steps": max_steps,
        "max_trajectory_length": max_trajectory_length,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": None if "glm-4.6v" in model.lower() else top_p,
        "thinking": (
            "provider_default"
            if "glm-4.6v" in model.lower()
            else "disabled" if "qwen3.5" in model.lower() else "unspecified"
        ),
        "with_example": True,
        "with_rag": False,
    }
    (run_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    agent.reset()
    obs = env.reset(task_config)
    initial = {
        "instruction": task_config["instruction"],
        "task_type": "3d_model",
        "software": "sldworks",
        "init_timestamp": started_at.strftime("%Y%m%d@%H%M%S"),
        "init_obs": save_obs(
            obs,
            0,
            started_at.strftime("%Y%m%d@%H%M%S"),
            str(run_dir),
        ),
    }
    trajectory_path.write_text(json.dumps(initial) + "\n", encoding="utf-8")

    final_decision = "CODE"
    steps_completed = 0
    executions = []
    responses = []
    error_text = None
    geometry = {}
    lifecycle = {}
    try:
        for step_idx in range(1, max_steps + 1):
            logger.info("Agent step %d: thinking...", step_idx)
            response, py_codes, decision, messages, call_llm_time = agent.predict(
                task_config["instruction"], obs, []
            )
            action_timestamp = datetime.now().strftime("%Y%m%d@%H%M%S")
            responses.append(response)
            (run_dir / f"step_{step_idx}-messages_{action_timestamp}.json").write_text(
                json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (run_dir / f"step_{step_idx}-response_{action_timestamp}.json").write_text(
                json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (run_dir / f"step_{step_idx}-pycodes_{action_timestamp}.py").write_text(
                py_codes, encoding="utf-8"
            )
            (run_dir / f"step_{step_idx}-decision_{action_timestamp}.txt").write_text(
                decision, encoding="utf-8"
            )
            logger.info("Agent decision: %s; executing generated script...", decision)
            obs, terminated, done, fail, run_code_time = env.step(py_codes, decision)
            updated_obs = save_obs(obs, step_idx, action_timestamp, str(run_dir))
            terminal = obs.get("terminal") or {}
            if "CODE" in decision.upper():
                executions.append(
                    {
                        "step": step_idx,
                        "code_present": bool(py_codes.strip()),
                        "returncode": terminal.get("returncode"),
                        "stdout": terminal.get("output", ""),
                        "stderr": terminal.get("error", ""),
                    }
                )
            step_data = {
                "step_num": step_idx,
                "thinking": {
                    "thinking_time": call_llm_time,
                    "response": response,
                    "py_codes": py_codes,
                    "decision": decision,
                    "messages": messages,
                },
                "action": {
                    "run_code_time": run_code_time,
                    "terminated": terminated,
                    "done": done,
                    "fail": fail,
                    "updated_obs": updated_obs,
                    "terminal": terminal,
                },
            }
            with trajectory_path.open("a", encoding="utf-8") as trajectory_file:
                trajectory_file.write(
                    json.dumps(step_data, ensure_ascii=False) + "\n"
                )
            final_decision = decision
            steps_completed = step_idx
            if terminated:
                break
    except BaseException:
        error_text = traceback.format_exc()
        (run_dir / "runner_error.txt").write_text(error_text, encoding="utf-8")
    finally:
        geometry = collect_geometry_and_export(run_dir)
        lifecycle = shutdown_solidworks()
        (run_dir / "lifecycle.json").write_text(
            json.dumps(lifecycle, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    token_totals = {
        key: sum(int(response.get(key) or 0) for response in responses)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    summary = {
        "task_id": task_id,
        "steps_completed": steps_completed,
        "final_decision": final_decision,
        "executions": executions,
        "token_totals": token_totals,
        "elapsed_seconds": (datetime.now() - started_at).total_seconds(),
        "error": error_text,
        "geometry_path": str(run_dir / "geometry.json"),
        "solidworks_shutdown": lifecycle,
        "result_dir": str(run_dir),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Set the {args.api_key_env} environment variable before running.")
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s %(levelname)s %(name)s] %(message)s",
    )
    run_dir = (
        args.result_dir.resolve()
        / args.task_id
        / datetime.now().strftime("%Y%m%d@%H%M%S")
    )
    summary = run_case(
        instruction=args.instruction,
        task_id=args.task_id,
        api_key=api_key,
        run_dir=run_dir,
        model=args.model,
        base_url=args.base_url,
        max_steps=args.max_steps,
        max_trajectory_length=args.max_trajectory_length,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
