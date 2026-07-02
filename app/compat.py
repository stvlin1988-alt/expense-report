import importlib.util
import os
import sys
import types


def resource_filename(package_or_requirement, resource_name):
    """pkg_resources.resource_filename fallback：用 importlib 找套件目錄再拼路徑。"""
    spec = importlib.util.find_spec(package_or_requirement)
    if spec and spec.submodule_search_locations:
        return os.path.join(list(spec.submodule_search_locations)[0], resource_name)
    raise FileNotFoundError(resource_name)


def install_pkg_resources_shim():
    """若真的 pkg_resources 不存在（新版 setuptools），安裝提供 resource_filename 的 shim。
    回傳 True 表示裝了 shim、False 表示已有真 pkg_resources。"""
    try:
        import pkg_resources  # noqa: F401
        return False
    except Exception:
        shim = types.ModuleType("pkg_resources")
        shim.resource_filename = resource_filename
        sys.modules["pkg_resources"] = shim
        return True
