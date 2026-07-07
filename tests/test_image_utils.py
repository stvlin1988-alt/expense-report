import io
import logging
from PIL import Image
from app.images.image_utils import (
    process_upload_image, process_upload_image_async,
    MAIN_EDGE, THUMB_EDGE,
)


def _jpeg(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 130, 140)).save(buf, format="JPEG")
    return buf.getvalue()


def _dims(b):
    return Image.open(io.BytesIO(b)).size


def test_large_image_downscaled_to_main_edge():
    raw = _jpeg(5000, 2500)
    main, thumb = process_upload_image(raw, "image/jpeg")
    assert max(_dims(main)) == MAIN_EDGE           # 長邊縮到 3200
    assert max(_dims(thumb)) == THUMB_EDGE          # 縮圖長邊 640


def test_small_image_not_upscaled():
    raw = _jpeg(400, 300)
    main, thumb = process_upload_image(raw, "image/jpeg")
    assert _dims(main) == (400, 300)                # 不放大
    assert max(_dims(thumb)) == 400                 # thumb 也不放大（原長邊<640，維持 400）


def test_thumb_is_jpeg():
    raw = _jpeg(1000, 800)
    _, thumb = process_upload_image(raw, "image/jpeg")
    assert Image.open(io.BytesIO(thumb)).format == "JPEG"


def test_corrupt_bytes_returns_raw_and_none():
    main, thumb = process_upload_image(b"not-an-image", "image/jpeg")
    assert main == b"not-an-image"
    assert thumb is None


def test_unsupported_content_type_returns_raw_and_none(caplog):
    raw = _jpeg(1000, 800)
    caplog.set_level(logging.WARNING)
    main, thumb = process_upload_image(raw, "application/pdf")
    assert main == raw
    assert thumb is None
    assert any("unsupported content_type" in r.message for r in caplog.records)


def test_async_matches_sync_dims():
    raw = _jpeg(5000, 2500)
    main, thumb = process_upload_image_async(raw, "image/jpeg")
    assert max(_dims(main)) == MAIN_EDGE
    assert max(_dims(thumb)) == THUMB_EDGE
