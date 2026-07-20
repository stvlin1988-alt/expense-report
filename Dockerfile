FROM python:3.12-slim

LABEL "language"="python"
LABEL "framework"="flask"

# dlib runtime 相依
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libopenblas0 \
    liblapack3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 預編 wheel — 零編譯、排在 app code 之前吃 layer cache
COPY wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --no-deps /tmp/wheels/*.whl && rm -rf /tmp/wheels

# face_recognition wrapper（純 python）用 --no-deps 裝：比照 webapp/Weather，避免把 dlib +
# face_recognition_models 從 PyPI 重拉/重編（那兩個已由上面的 vendored wheels 提供）。
# 其執行期依賴（numpy / Pillow / Click）由下方 hash-locked requirements.txt 提供。
RUN pip install --no-cache-dir --no-deps face_recognition==1.3.0

# hash-locked（pip-compile --generate-hashes 產；有 hash 時 pip 自動 --require-hashes）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 驗證 dlib 已裝好（零編譯）
RUN python -c "import dlib; print('dlib OK')"

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app && \
    chown -R appuser:appuser /usr/local/lib/python3.12/site-packages
USER appuser

EXPOSE 8080
ENV PYTHONUNBUFFERED=1
ENV SESSION_COOKIE_SECURE=true

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
