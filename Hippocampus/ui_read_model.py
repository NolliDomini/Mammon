import importlib.util
import runpy
from pathlib import Path

_ARCHIVED = (
    Path(__file__).resolve().parents[1]
    / "Archive"
    / "ui_legacy"
    / "Hippocampus"
    / "ui_read_model.py"
)

if __name__ == "__main__":
    runpy.run_path(str(_ARCHIVED), run_name="__main__")
else:
    _spec = importlib.util.spec_from_file_location("mammon_ui_read_model_archived", _ARCHIVED)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"Unable to load archived ui_read_model module: {_ARCHIVED}")
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    for _name in dir(_module):
        if _name.startswith("__") and _name not in {"__doc__", "__all__"}:
            continue
        globals()[_name] = getattr(_module, _name)

