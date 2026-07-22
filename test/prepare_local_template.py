"""Create a blank local part template for the ComAct baseline environment."""

from __future__ import annotations

from pathlib import Path

import pythoncom
import win32com.client
from win32com.client import gencache


TYPELIB_GUID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"


def cast(obj, interface_name: str):
    module = gencache.EnsureModule(TYPELIB_GUID, 0, 33, 0)
    interface = getattr(module, interface_name)
    dispatch = obj._oleobj_.QueryInterface(interface.CLSID, pythoncom.IID_IDispatch)
    return interface(dispatch)


def find_feature(model, type_names: set[str]):
    feature = model.FirstFeature()
    while feature is not None:
        if feature.GetTypeName2 in type_names:
            return feature
        feature = feature.GetNextFeature
    return None


def main() -> None:
    template_path = (
        Path(__file__).resolve().parents[1] / "output" / "comact_blank_part.prtdot"
    ).resolve()
    template_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    try:
        sw_app = cast(
            win32com.client.GetActiveObject("SldWorks.Application"),
            "ISldWorks",
        )
        model_raw = sw_app.ActiveDoc
        if model_raw is None or model_raw.GetType != 1:
            raise RuntimeError("Open a part document in SolidWorks before preparing the template.")

        model = cast(model_raw, "IModelDoc2")
        part = cast(model_raw, "IPartDoc")
        extension = cast(model.Extension, "IModelDocExtension")

        # Remove user-created features while preserving the standard planes and origin.
        for feature_type in ("Extrusion", "ProfileFeature"):
            while True:
                feature = find_feature(model, {feature_type})
                if feature is None:
                    break
                model.ClearSelection2(True)
                if not feature.Select2(False, 0):
                    raise RuntimeError(f"Could not select feature {feature.Name!r}.")
                if not extension.DeleteSelection2(3):
                    raise RuntimeError(f"Could not delete feature {feature.Name!r}.")

        if part.GetBodies2(0, False):
            raise RuntimeError("The document still contains solid bodies; refusing to use it as a template.")

        saved = model.SaveAs3(str(template_path), 0, 1)
        if not saved:
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            saved = model_raw.Save3(1, errors, warnings)
            if not saved:
                raise RuntimeError(
                    f"Template save failed (errors={errors.value}, warnings={warnings.value})."
                )

        if not sw_app.SetUserPreferenceStringValue(8, str(template_path)):
            raise RuntimeError("SolidWorks rejected the default part template setting.")

        print(f"Default part template: {sw_app.GetUserPreferenceStringValue(8)}")
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
