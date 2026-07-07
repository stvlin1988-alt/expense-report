"""手動跑真 Gemini 驗辨識準度（需 .env 有 GEMINI_API_KEY，OCR_PROVIDER=gemini）。
用法：FLASK_APP=wsgi.py OCR_PROVIDER=gemini python3 tests/manual/verify_ocr.py
不進 CI（無金鑰）。重點驗全家單金額=1290(非2000)、手寫單金額、多品項摘要濃縮。"""
import glob
import os
from app import create_app
from app.extensions import db
from app.ocr.gemini import GeminiProvider

app = create_app()
with app.app_context():
    provider = GeminiProvider(app.config)
    for path in sorted(glob.glob("tests/fixtures/receipts/*.jpg")):
        with open(path, "rb") as f:
            raw = f.read()
        r = provider.recognize(raw, "image/jpeg")
        print(f"\n=== {os.path.basename(path)} ===")
        print(f"  summary   : {r['summary']}")
        print(f"  amount    : {r['amount']}")
        print(f"  category  : {r['category_id']}")
        print(f"  handwritten: {r['is_handwritten']}  conf: {r['confidence']}")
