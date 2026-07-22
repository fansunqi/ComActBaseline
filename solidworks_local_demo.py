"""Create a deterministic SolidWorks block through the local COM API."""

from __future__ import annotations

import argparse
from pathlib import Path

import pythoncom
import win32com.client
from win32com.client import gencache


MM_TO_M = 0.001
SW_TYPELIB_GUID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
SW_TYPELIB_2025_MAJOR = 33


def solidworks_cast(obj, interface_name: str):
    """Cast a dynamic COM object to a SolidWorks early-bound interface."""
    module = gencache.EnsureModule(SW_TYPELIB_GUID, 0, SW_TYPELIB_2025_MAJOR, 0)
    interface = getattr(module, interface_name)
    dispatch = obj._oleobj_.QueryInterface(interface.CLSID, pythoncom.IID_IDispatch)
    return interface(dispatch)


def create_block(width_mm: float, height_mm: float, depth_mm: float, output: Path) -> Path:
    """Create and save a centered rectangular extrusion without closing open documents."""
    pythoncom.CoInitialize()
    try:
        sw_app = solidworks_cast(
            win32com.client.GetActiveObject("SldWorks.Application"),
            "ISldWorks",
        )
        sw_app.Visible = True

        part_template = sw_app.GetUserPreferenceStringValue(8)
        model = sw_app.NewDocument(part_template, 0, 0, 0)
        if model is None:
            # Some installations expose ~BLANK_PART_TEMPLATE.prtdot instead of
            # a real template. In that case, reuse only a safe, empty, unsaved part.
            active_doc = sw_app.ActiveDoc
            is_empty_unsaved_part = (
                active_doc is not None
                and active_doc.GetType == 1
                and not active_doc.GetPathName
                and not (active_doc.GetBodies2(0, False) or [])
            )
            if not is_empty_unsaved_part:
                raise RuntimeError(
                    f"SolidWorks could not create a part from template {part_template!r}, "
                    "and the active document is not an empty unsaved part."
                )
            model = active_doc

        model = solidworks_cast(model, "IModelDoc2")
        extension = solidworks_cast(model.Extension, "IModelDocExtension")
        sketch_manager = solidworks_cast(model.SketchManager, "ISketchManager")
        feature_manager = solidworks_cast(model.FeatureManager, "IFeatureManager")

        width = width_mm * MM_TO_M
        height = height_mm * MM_TO_M
        depth = depth_mm * MM_TO_M

        # Reuse a profile left by an interrupted run; otherwise create one.
        sketch_feature = None
        feature = model.FirstFeature()
        while feature is not None:
            if feature.GetTypeName2 == "ProfileFeature":
                sketch_feature = feature
            feature = feature.GetNextFeature

        if sketch_feature is None:
            selected = False
            for plane_name in ("Front Plane", "前视基准面", "前基准面"):
                if extension.SelectByID2(plane_name, "PLANE", 0, 0, 0, False, 0, None, 0):
                    selected = True
                    break
            if not selected:
                raise RuntimeError("Could not select the Front Plane (tried English and Chinese names).")

            sketch_manager.InsertSketch(True)
            sketch_manager.CreateCornerRectangle(
                -width / 2,
                -height / 2,
                0,
                width / 2,
                height / 2,
                0,
            )
            sketch_manager.InsertSketch(True)

            feature = model.FirstFeature()
            while feature is not None:
                if feature.GetTypeName2 == "ProfileFeature":
                    sketch_feature = feature
                feature = feature.GetNextFeature
            if sketch_feature is None:
                raise RuntimeError("SolidWorks created geometry but no sketch feature was found.")

        model.ClearSelection2(True)
        if not sketch_feature.Select2(False, 0):
            raise RuntimeError("Could not select the newly created sketch.")

        extrusion = feature_manager.FeatureExtrusion3(
            True,
            False,
            False,
            0,
            0,
            depth,
            0.0,
            False,
            False,
            False,
            False,
            0.0,
            0.0,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            0,
            0.0,
            False,
        )
        if extrusion is None:
            raise RuntimeError("SolidWorks failed to create the extrusion.")

        model.EditRebuild3()
        model.ViewZoomtofit2()

        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        saved = model.SaveAs3(str(output), 0, 1)
        if not saved:
            # SaveAs3 can assign the path yet return False on a first save.
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            saved = model.Save3(1, errors, warnings)
            if not saved:
                raise RuntimeError(
                    f"SolidWorks failed to save the part to {output} "
                    f"(errors={errors.value}, warnings={warnings.value})"
                )
        if not output.exists():
            raise RuntimeError(f"SolidWorks reported success, but the file does not exist: {output}")

        return output
    finally:
        pythoncom.CoUninitialize()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=float, default=100.0, help="Block width in millimeters")
    parser.add_argument("--height", type=float, default=60.0, help="Block height in millimeters")
    parser.add_argument("--depth", type=float, default=20.0, help="Extrusion depth in millimeters")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output") / "com_demo_block.SLDPRT",
        help="Output SLDPRT path",
    )
    args = parser.parse_args()

    if min(args.width, args.height, args.depth) <= 0:
        parser.error("width, height, and depth must all be positive")

    result = create_block(args.width, args.height, args.depth, args.output)
    print(f"Created SolidWorks part: {result}")
    print(f"Dimensions: {args.width:g} x {args.height:g} x {args.depth:g} mm")


if __name__ == "__main__":
    main()
