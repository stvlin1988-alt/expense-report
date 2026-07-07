from app.storage.r2 import get_storage, MockStorage


def test_mock_put_get_url_delete(app):
    with app.app_context():
        s = get_storage()
        assert isinstance(s, MockStorage)
        s.put("expenses/1/202607/abc.jpg", b"data", "image/jpeg")
        assert "expenses/1/202607/abc.jpg" in s.objects
        url = s.presigned_url("expenses/1/202607/abc.jpg")
        assert "abc.jpg" in url
        s.delete("expenses/1/202607/abc.jpg")
        assert "expenses/1/202607/abc.jpg" not in s.objects


def test_presigned_url_missing_key_still_returns_str(app):
    with app.app_context():
        s = get_storage()
        assert isinstance(s.presigned_url("nope.jpg"), str)
