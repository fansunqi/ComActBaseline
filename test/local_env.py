"""Local replacement for ComAct's ROCK/VM desktop environment.

Only the transport changes: generated scripts run in a local subprocess instead
of being posted to the VM `/execute` endpoint. The observation and step
contracts intentionally match `myenv.MyDesktopEnv`.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
import logging
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Optional

from PIL import ImageGrab


logger = logging.getLogger("myexp.local_env")


class LocalEnvController:
    def __init__(self, workspace: Path, python_executable: str = sys.executable):
        self.workspace = workspace.resolve()
        self.python_executable = python_executable
        self.workspace.mkdir(parents=True, exist_ok=True)

    def get_screenshot(self) -> bytes:
        image = ImageGrab.grab(all_screens=True)
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def create_file(self, path: str, content: str = "") -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def run_codes(self, path: str) -> Dict[str, Any]:
        try:
            completed = subprocess.run(
                [self.python_executable, path],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=180,
            )
            return {
                "output": completed.stdout,
                "error": completed.stderr,
                "returncode": completed.returncode,
            }
        except subprocess.TimeoutExpired as error:
            return {
                "output": error.stdout or "",
                "error": f"{error.stderr or ''}\nExecution timed out after 180 seconds.",
                "returncode": -1,
            }

    def clean_up_files(self) -> None:
        generated_script = self.workspace / "pycodes.py"
        if generated_script.exists():
            generated_script.unlink()

    def close_all_window(self) -> None:
        # Equivalent to the CAD cleanup done by the VM controller, without
        # terminating the already-running local SolidWorks application.
        command = (
            "import win32com.client as w; "
            "sw=w.GetActiveObject('SldWorks.Application'); "
            "sw.CloseAllDocuments(True)"
        )
        subprocess.run(
            [self.python_executable, "-c", command],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )


class LocalDesktopEnv:
    """Local implementation of the subset used by ComAct's agent loop."""

    def __init__(self, workspace: Path, python_executable: str = sys.executable):
        self.controller = LocalEnvController(workspace, python_executable)
        self.task_config: Optional[Dict[str, Any]] = None

    def _get_obs(self) -> Dict[str, Any]:
        start_get_obs_time = datetime.now()
        screenshot = self.controller.get_screenshot()
        end_get_obs_time = datetime.now()
        return {
            "screenshot": screenshot,
            "terminal": {},
            "get_obs_time": (end_get_obs_time - start_get_obs_time).total_seconds(),
        }

    def reset(
        self,
        task_config: Optional[Dict[str, Any]] = None,
        seed=None,
        **kwargs,
    ) -> Dict[str, Any]:
        logger.info("Resetting local environment...")
        if task_config and task_config.get("close_window"):
            self.controller.close_all_window()
        self.controller.clean_up_files()
        self.task_config = task_config
        return self._get_obs()

    def step(self, py_code: str, decision: str):
        terminated = False
        done = False
        fail = False

        if "DONE" in decision.upper():
            done = True
            terminated = True
        elif "FAIL" in decision.upper():
            fail = True
            terminated = True
        elif "CODE" not in decision.upper():
            logger.error("Invalid decision: %s", decision)

        path = self.controller.create_file(
            path=str(self.controller.workspace / "pycodes.py"),
            content=py_code,
        )

        run_code_start_time = datetime.now()
        terminal_outputs = self.controller.run_codes(path)
        run_code_end_time = datetime.now()

        observation = self._get_obs()
        observation["terminal"] = terminal_outputs
        return (
            observation,
            terminated,
            done,
            fail,
            (run_code_end_time - run_code_start_time).total_seconds(),
        )
