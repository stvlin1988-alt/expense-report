def test_face_libs_importable():
    import dlib          # noqa: F401
    import face_recognition  # noqa: F401
    import face_recognition_models  # noqa: F401


def test_pkg_resources_available_after_wsgi_shim():
    import wsgi  # noqa: F401  匯入 wsgi 觸發 shim
    import pkg_resources
    assert hasattr(pkg_resources, "resource_filename")
