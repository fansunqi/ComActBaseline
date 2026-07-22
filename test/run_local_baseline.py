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

from agent import PromptAgent
from lib_run_single import save_obs
from local_env import LocalDesktopEnv


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
    run_dir.mkdir(parents=True, exist_ok=True)
    execution_workspace = run_dir / "execution"

    task_config = {
        "id": args.task_id,
        "instruction": "Model this part in Solidworks: " + args.instruction,
        "close_window": True,
    }

    # Use ComAct's original SolidWorks example; keep RAG disabled.
    agent = PromptAgent(
        model=args.model,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
        max_steps=args.max_steps,
        max_trajectory_length=args.max_trajectory_length,
        api_server="claudeshop",
        base_url=args.base_url,
        api_key=api_key,
        with_example=True,
        task_type="3d_model",
        software="sldworks",
        with_rag=False,
    )
    env = LocalDesktopEnv(execution_workspace)

    agent.reset()
    obs = env.reset(task_config)
    started_at = datetime.now()
    trajectory_path = run_dir / "traj.jsonl"
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
    for step_idx in range(1, args.max_steps + 1):
        logger.info("Agent step %d: thinking...", step_idx)
        response, py_codes, decision, messages, call_llm_time = agent.predict(
            task_config["instruction"],
            obs,
            [],
        )
        action_timestamp = datetime.now().strftime("%Y%m%d@%H%M%S")

        (run_dir / f"step_{step_idx}-messages_{action_timestamp}.json").write_text(
            json.dumps(messages, indent=2),
            encoding="utf-8",
        )
        (run_dir / f"step_{step_idx}-response_{action_timestamp}.json").write_text(
            json.dumps(response, indent=2),
            encoding="utf-8",
        )
        (run_dir / f"step_{step_idx}-pycodes_{action_timestamp}.py").write_text(
            py_codes,
            encoding="utf-8",
        )
        (run_dir / f"step_{step_idx}-decision_{action_timestamp}.txt").write_text(
            decision,
            encoding="utf-8",
        )

        logger.info("Agent decision: %s; executing generated script...", decision)
        obs, terminated, done, fail, run_code_time = env.step(py_codes, decision)
        updated_obs = save_obs(
            obs,
            step_idx,
            action_timestamp,
            str(run_dir),
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
            },
        }
        with trajectory_path.open("a", encoding="utf-8") as trajectory_file:
            trajectory_file.write(json.dumps(step_data) + "\n")

        final_decision = decision
        steps_completed = step_idx
        if terminated:
            break

    summary = {
        "task_id": args.task_id,
        "steps_completed": steps_completed,
        "final_decision": final_decision,
        "result_dir": str(run_dir),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
