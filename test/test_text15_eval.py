from __future__ import annotations

import ast
import unittest
from pathlib import Path

from text15_eval import load_cases, score_case


class Text15EvalTests(unittest.TestCase):
    def test_snapshot_matches_solidworks_tutorial_evaluator(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[2]
            / "SolidWorksTutorial"
            / "LLMPlanner"
            / "eval"
            / "eval_text_singleturn_qwen.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "CASES" for target in node.targets)
        )
        calls = assignment.value.elts
        source_cases = []
        for call in calls:
            values = [ast.literal_eval(argument) for argument in call.args]
            source_cases.append(
                {
                    "case_id": values[0],
                    "name": values[1],
                    "prompt": values[2],
                    "expected_bbox_mm": list(values[3]),
                    "bbox_tolerance_mm": values[4],
                    "volume_range_mm3": list(values[5]),
                    "expected_details": dict(values[6]),
                }
            )
        self.assertEqual(load_cases(), source_cases)

    def test_perfect_result_scores_100(self) -> None:
        case = load_cases()[5]
        geometry = {
            "bounding_box_mm": {"sizeX": 8.0, "sizeY": 30.0, "sizeZ": 34.641},
            "volume_mm3": 5500.0,
            "actual_details": {"extrusions": 1, "polygons": 1, "circles": 1},
        }
        score = score_case(case, geometry, [{"returncode": 0}])
        self.assertEqual(score["score"], 100.0)
        self.assertTrue(score["acceptance_ok"])

    def test_no_execution_or_geometry_scores_zero(self) -> None:
        score = score_case(load_cases()[0], {}, [])
        self.assertEqual(score["score"], 0.0)
        self.assertFalse(score["acceptance_ok"])


if __name__ == "__main__":
    unittest.main()
