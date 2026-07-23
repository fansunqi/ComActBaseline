"""Refresh geometry snapshots by reopening saved parts, without rerunning the LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import win32com.client

from text15_eval import _cast, collect_geometry_and_export, shutdown_solidworks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--case")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    refreshed = []
    skipped = []
    result_paths = sorted(run_dir.glob("*/case_result.json"))
    if args.case:
        result_paths = [path for path in result_paths if path.parent.name == args.case]
    for result_path in result_paths:
        case_dir = result_path.parent
        part_path = case_dir / "exports" / "model.sldprt"
        if not part_path.exists():
            skipped.append(case_dir.name)
            continue
        sw = _cast(win32com.client.Dispatch("SldWorks.Application"), "ISldWorks")
        sw.Visible = True
        model = sw.OpenDoc(str(part_path), 1)
        if model is None:
            shutdown_solidworks()
            skipped.append(case_dir.name)
            continue
        time.sleep(1)
        collect_geometry_and_export(case_dir)
        shutdown_solidworks()
        refreshed.append(case_dir.name)
    print(
        json.dumps(
            {"refreshed": refreshed, "skipped_no_saved_part": skipped},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
