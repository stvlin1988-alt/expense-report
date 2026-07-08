from app.storage.r2 import MockStorage


def test_mock_put_get_roundtrip():
    s = MockStorage()
    s.put("k1", b"hello", "image/jpeg")
    assert s.get("k1") == b"hello"


def test_mock_get_missing_returns_none():
    assert MockStorage().get("nope") is None
