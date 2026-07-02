import io
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

logger = logging.getLogger(__name__)

try:
    import face_recognition_models  # noqa: F401  觸發 pkg_resources shim 使用
    import face_recognition
    FACE_AVAILABLE = True
except Exception as _e:  # pragma: no cover - 環境相依
    logger.warning("face_recognition unavailable: %s", _e)
    FACE_AVAILABLE = False

_executor = ThreadPoolExecutor(max_workers=2)


def best_match_among(candidates, submitted_encoding,
                     threshold: float = 0.45,
                     ambiguous_margin: float = 0.05):
    """從 candidates 選 face_distance 最低且 < threshold 者；前兩名距離差
    < ambiguous_margin 視為撞臉、整批拒。candidates 需有 .face_encoding(bytes)。"""
    submitted = np.asarray(submitted_encoding, dtype=np.float64)
    scored = []
    for c in candidates:
        enc = getattr(c, "face_encoding", None)
        if not enc:
            continue
        known = np.frombuffer(enc, dtype=np.float64)
        scored.append((float(np.linalg.norm(known - submitted)), c))
    if not scored:
        return None, {"reason": "no enrolled users"}
    scored.sort(key=lambda x: x[0])
    best_dist, best = scored[0]
    info = {"best_dist": best_dist}
    if best_dist > threshold:
        return None, info
    if len(scored) >= 2:
        info["second_dist"] = scored[1][0]
        if scored[1][0] - best_dist < ambiguous_margin:
            info["ambiguous"] = True
            return None, info
    return best, info


def encode_face(image_bytes: bytes):
    """單張圖 → 128 維 encoding；無臉回 None。CPU heavy（dlib）。"""
    if not FACE_AVAILABLE:
        return None
    img = face_recognition.load_image_file(io.BytesIO(image_bytes))
    locations = face_recognition.face_locations(img, number_of_times_to_upsample=1)
    encodings = face_recognition.face_encodings(img, locations)
    return encodings[0] if encodings else None


def encode_face_async(image_bytes: bytes, timeout: float = 15.0):
    """在 thread executor 跑 encode_face，逾時/失敗回 None（不卡 worker）。"""
    try:
        return _executor.submit(encode_face, image_bytes).result(timeout=timeout)
    except Exception as e:
        logger.warning("encode_face_async failed: %s", e)
        return None
