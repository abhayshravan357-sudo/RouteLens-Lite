import importlib.util
import pathlib
import sys

# Path to the backend FastAPI application package
_backend_app_dir = pathlib.Path(__file__).resolve().parents[1] / "backend" / "app"

# Create a module spec for the backend 'app' package, pointing to its directory for submodule resolution
_spec = importlib.util.spec_from_file_location(
    "app",
    _backend_app_dir / "main.py",
    submodule_search_locations=[str(_backend_app_dir)],
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load backend FastAPI app from {_backend_app_dir / 'main.py'}")

# Load the backend app module as the 'app' package
_backend_app = importlib.util.module_from_spec(_spec)
# Register the package so that relative imports (e.g., .routing) resolve correctly
sys.modules["app"] = _backend_app
_spec.loader.exec_module(_backend_app)

# Expose the FastAPI instance expected by the test suite
app = _backend_app.app

