import io
import logging
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

MAIN_EDGE = 3200
MAIN_QUALITY = 85
THUMB_EDGE = 640
THUMB_QUALITY = 78
_SUPPORTED = {"image/jpeg", "image/png", "image/webp"}
_executor = ThreadPoolExecutor(max_workers=2)


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _resized(img: Image.Image, edge: int) -> Image.Image:
    out = img.copy()
    out.thumbnail((edge, edge), Image.LANCZOS)  # thumbnail 只縮不放大
    return out


def process_upload_image(raw_bytes: bytes, content_type: str):
    """回 (main_bytes, thumb_bytes)；不支援型別或壞 bytes → (raw_bytes, None)。"""
    if content_type not in _SUPPORTED:
        return raw_bytes, None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = ImageOps.exif_transpose(img)      # 修正方向
        main = _encode_jpeg(_resized(img, MAIN_EDGE), MAIN_QUALITY)
        thumb = _encode_jpeg(_resized(img, THUMB_EDGE), THUMB_QUALITY)
        return main, thumb
    except Exception as e:
        logger.warning("process_upload_image failed: %s", e)
        return raw_bytes, None


def process_upload_image_async(raw_bytes: bytes, content_type: str, timeout: float = 10.0):
    """在 thread executor 跑壓縮（CPU-heavy），逾時/失敗回 (raw_bytes, None)。"""
    try:
        return _executor.submit(process_upload_image, raw_bytes, content_type).result(timeout=timeout)
    except Exception as e:
        logger.warning("process_upload_image_async failed: %s", e)
        return raw_bytes, None
