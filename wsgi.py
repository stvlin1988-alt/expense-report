# face_recognition_models 需要 pkg_resources.resource_filename；新版 setuptools 移除了 pkg_resources
import sys
import types

try:
    import pkg_resources  # noqa: F401
except Exception:
    import importlib.util as _ilu

    def _resource_filename(package_or_requirement, resource_name):
        spec = _ilu.find_spec(package_or_requirement)
        if spec and spec.submodule_search_locations:
            import os
            return os.path.join(list(spec.submodule_search_locations)[0], resource_name)
        raise FileNotFoundError(resource_name)

    _shim = types.ModuleType("pkg_resources")
    _shim.resource_filename = _resource_filename
    sys.modules["pkg_resources"] = _shim

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
