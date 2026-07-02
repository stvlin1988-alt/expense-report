# face_recognition_models 需要 pkg_resources.resource_filename；新版 setuptools 移除了 pkg_resources
from app.compat import install_pkg_resources_shim

install_pkg_resources_shim()

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
