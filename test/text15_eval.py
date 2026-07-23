"""SolidWorks observation, lifecycle, and scoring for the Text15 benchmark."""

from __future__ import annotations

import gc
import json
import subprocess
import time
from pathlib import Path
from typing import Any


CASES_PATH = Path(__file__).with_name("swtutorial_text_cases.json")


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _get(obj: Any, name: str, *args: Any) -> Any:
    member = getattr(obj, name)
    return member(*args) if callable(member) else member


def _cast(obj: Any, interface_name: str) -> Any:
    import pythoncom
    from win32com.client import gencache

    module = gencache.EnsureModule(
        "{83A33D31-27C5-11CE-BFD4-00400513BB57}", 0, 33, 0
    )
    interface = getattr(module, interface_name)
    dispatch = obj._oleobj_.QueryInterface(interface.CLSID, pythoncom.IID_IDispatch)
    return interface(dispatch)


def _feature_metrics(model: Any) -> tuple[list[dict[str, str]], dict[str, int]]:
    features: list[dict[str, str]] = []
    metrics = {
        "extrusions": 0,
        "cuts": 0,
        "fillets": 0,
        "chamfers": 0,
        "revolves": 0,
        "polygons": 0,
        "centerlines": 0,
        "circles": 0,
        "slots": 0,
    }
    try:
        feature = model.FirstFeature()
    except Exception:
        feature = None
    visited = 0
    while feature is not None and visited < 1000:
        visited += 1
        try:
            name = str(_get(feature, "Name"))
        except Exception:
            name = ""
        try:
            kind = str(_get(feature, "GetTypeName2"))
        except Exception:
            kind = ""
        features.append({"name": name, "type": kind})
        marker = f"{name} {kind}".lower()
        if "extrusion" in marker or "boss" in marker or "凸台" in marker:
            metrics["extrusions"] += 1
        if "cut" in marker or "切除" in marker or "孔" in marker:
            metrics["cuts"] += 1
        if "fillet" in marker or "圆角" in marker:
            metrics["fillets"] += 1
        if "chamfer" in marker or "倒角" in marker:
            metrics["chamfers"] += 1
        if "revol" in marker or "旋转" in marker:
            metrics["revolves"] += 1
        if "profilefeature" in marker or "sketch" in marker or "草图" in marker:
            try:
                sketch = feature.GetSpecificFeature2
                segments = sketch.GetSketchSegments or []
                line_count = 0
                construction_count = 0
                arc_count = 0
                for segment in segments:
                    try:
                        segment_type = int(segment.GetType)
                    except Exception:
                        segment_type = -1
                    if segment_type == 0:
                        line_count += 1
                    elif segment_type == 1:
                        arc_count += 1
                    try:
                        construction_count += int(bool(segment.ConstructionGeometry))
                    except Exception:
                        pass
                metrics["circles"] += arc_count
                metrics["centerlines"] += construction_count
                if line_count >= 6:
                    metrics["polygons"] += line_count // 6
            except Exception:
                pass
        try:
            feature = feature.GetNextFeature
        except Exception:
            feature = None
    return features, metrics


def collect_geometry_and_export(run_dir: Path) -> dict[str, Any]:
    """Snapshot the active part and export it before SolidWorks shutdown."""
    geometry: dict[str, Any] = {
        "entity_exists": False,
        "body_count": 0,
        "bounding_box_mm": None,
        "volume_mm3": None,
        "features": [],
        "actual_details": {},
        "exports": {},
        "errors": [],
    }
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        sw = _cast(
            win32com.client.GetActiveObject("SldWorks.Application"), "ISldWorks"
        )
        model_raw = sw.ActiveDoc
        if model_raw is None:
            geometry["errors"].append("No active SolidWorks document.")
            return geometry
        model = _cast(model_raw, "IModelDoc2")
        part = _cast(model_raw, "IPartDoc")
        geometry["entity_exists"] = True
        features, metrics = _feature_metrics(model)
        geometry["features"] = features
        geometry["actual_details"] = metrics
        bodies = []
        try:
            bodies = list(part.GetBodies2(0, False) or [])
        except Exception as error:
            geometry["errors"].append(f"GetBodies2: {error}")
        geometry["body_count"] = len(bodies)
        boxes: list[list[float]] = []
        volumes: list[float] = []
        for body in bodies:
            try:
                boxes.append([float(value) for value in _get(body, "GetBodyBox")])
            except Exception as error:
                geometry["errors"].append(f"GetBodyBox: {error}")
            try:
                props = list(_get(body, "GetMassProperties", 1) or [])
                if len(props) > 3:
                    volumes.append(float(props[3]))
            except Exception as error:
                geometry["errors"].append(f"GetMassProperties: {error}")
        if boxes:
            mins = [min(box[index] for box in boxes) for index in range(3)]
            maxs = [max(box[index + 3] for box in boxes) for index in range(3)]
            geometry["bounding_box_mm"] = {
                "sizeX": round((maxs[0] - mins[0]) * 1000.0, 6),
                "sizeY": round((maxs[1] - mins[1]) * 1000.0, 6),
                "sizeZ": round((maxs[2] - mins[2]) * 1000.0, 6),
            }
        if volumes:
            geometry["volume_mm3"] = round(sum(volumes) * 1_000_000_000.0, 6)
        if bodies:
            exports = run_dir / "exports"
            exports.mkdir(parents=True, exist_ok=True)
            for suffix in ("SLDPRT", "STEP", "STL"):
                target = exports / f"model.{suffix.lower()}"
                try:
                    result = _get(model, "SaveAs3", str(target), 0, 2)
                    geometry["exports"][suffix.lower()] = {
                        "path": str(target),
                        "result": bool(result),
                        "exists": target.exists(),
                    }
                except Exception as error:
                    geometry["exports"][suffix.lower()] = {"error": str(error)}
        return geometry
    except Exception as error:
        geometry["errors"].append(f"Observation failed: {error}")
        return geometry
    finally:
        (run_dir / "geometry.json").write_text(
            json.dumps(geometry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            import pythoncom

            pythoncom.CoUninitialize()
        except Exception:
            pass


def solidworks_running() -> bool:
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/NH"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return "SLDWORKS.exe" in completed.stdout


def shutdown_solidworks(timeout: float = 30.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "graceful_requested": False,
        "force_closed": False,
        "exited": False,
        "errors": [],
    }
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        sw = _cast(
            win32com.client.GetActiveObject("SldWorks.Application"), "ISldWorks"
        )
        sw.CloseAllDocuments(True)
        sw.ExitApp()
        result["graceful_requested"] = True
        del sw
        gc.collect()
    except Exception as error:
        result["errors"].append(str(error))
    deadline = time.time() + timeout
    while time.time() < deadline and solidworks_running():
        time.sleep(1)
    if solidworks_running():
        completed = subprocess.run(
            ["taskkill", "/F", "/IM", "SLDWORKS.exe", "/T"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        result["force_closed"] = completed.returncode == 0
        if completed.returncode != 0:
            result["errors"].append(completed.stderr or completed.stdout)
        time.sleep(2)
    result["exited"] = not solidworks_running()
    try:
        import pythoncom

        pythoncom.CoUninitialize()
    except Exception:
        pass
    return result


def _dimension_score(
    actual: list[float], expected: list[float], tolerance: float
) -> tuple[float, list[float], list[bool]]:
    actual_sorted = sorted(actual)
    expected_sorted = sorted(expected)
    errors = [abs(value - target) for value, target in zip(actual_sorted, expected_sorted)]
    if not any(value > 0 for value in actual_sorted):
        return 0.0, [round(value, 3) for value in errors], [False] * 3
    checks = [error <= tolerance for error in errors]
    points = [
        10.0 if ok else 10.0 * max(0.0, 1.0 - (error - tolerance) / (2 * tolerance))
        for error, ok in zip(errors, checks)
    ]
    return round(sum(points), 2), [round(value, 3) for value in errors], checks


def _volume_score(actual: float, expected: list[float]) -> tuple[float, bool]:
    low, high = expected
    if low <= actual <= high:
        return 20.0, True
    if actual <= 0:
        return 0.0, False
    distance = low - actual if actual < low else actual - high
    return round(20.0 * max(0.0, 1.0 - distance / (high - low)), 2), False


def score_case(
    case: dict[str, Any], geometry: dict[str, Any], executions: list[dict[str, Any]]
) -> dict[str, Any]:
    successful = sum(
        item.get("returncode") == 0 and item.get("code_present", True)
        for item in executions
    )
    all_ok = bool(executions) and successful == len(executions)
    rate = successful / len(executions) if executions else 0.0
    execution_points = round(20.0 * rate + (5.0 if all_ok else 0.0), 2)
    bbox = geometry.get("bounding_box_mm") or {}
    actual_dims = [float(bbox.get(key) or 0) for key in ("sizeX", "sizeY", "sizeZ")]
    dimension_points, dimension_errors, dimension_checks = _dimension_score(
        actual_dims, case["expected_bbox_mm"], case["bbox_tolerance_mm"]
    )
    volume = float(geometry.get("volume_mm3") or 0)
    volume_points, volume_ok = _volume_score(volume, case["volume_range_mm3"])
    metrics = geometry.get("actual_details") or {}
    expected_details = case["expected_details"]
    detail_checks = {
        name: int(metrics.get(name, 0)) >= minimum
        for name, minimum in expected_details.items()
    }
    detail_points = round(
        25.0
        * sum(min(int(metrics.get(name, 0)) / minimum, 1.0) for name, minimum in expected_details.items())
        / len(expected_details),
        2,
    )
    total = round(execution_points + dimension_points + volume_points + detail_points, 2)
    return {
        "score": total,
        "acceptance_ok": all_ok and all(dimension_checks) and volume_ok and all(detail_checks.values()),
        "status": "completed" if all_ok else "failed",
        "execution_steps": len(executions),
        "successful_steps": successful,
        "execution_points": execution_points,
        "dimension_points": dimension_points,
        "volume_points": volume_points,
        "detail_points": detail_points,
        "bbox_mm": bbox or None,
        "expected_bbox_mm": case["expected_bbox_mm"],
        "dimension_errors_mm": dimension_errors,
        "dimension_checks": dimension_checks,
        "volume_mm3": round(volume, 3) if volume else None,
        "expected_volume_range_mm3": case["volume_range_mm3"],
        "volume_ok": volume_ok,
        "actual_details": metrics,
        "expected_details": expected_details,
        "detail_checks": detail_checks,
        "execution_records": executions,
    }
