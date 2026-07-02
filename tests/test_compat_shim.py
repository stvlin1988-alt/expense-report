import importlib
import sys
from app.compat import resource_filename, install_pkg_resources_shim


def test_resource_filename_returns_existing_path_for_known_package():
    # app 套件一定存在；用它自己的檔案驗證回傳真實存在的路徑
    path = resource_filename("app", "compat.py")
    import os
    assert os.path.isfile(path)


def test_resource_filename_raises_for_unknown_resource():
    import pytest
    with pytest.raises(FileNotFoundError):
        resource_filename("nonexistent_pkg_xyz", "whatever")


def test_install_shim_when_pkg_resources_missing(monkeypatch):
    # 移除真 pkg_resources 並讓 import 失敗 → 迫使 except 分支跑
    monkeypatch.setitem(sys.modules, "pkg_resources", None)
    installed = install_pkg_resources_shim()
    assert installed is True
    import pkg_resources
    assert hasattr(pkg_resources, "resource_filename")
    # shim 的 resource_filename 真能拼出存在的路徑
    import os
    assert os.path.isfile(pkg_resources.resource_filename("app", "compat.py"))
