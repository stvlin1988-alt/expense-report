import os

# 綁定 Zeabur 提供的 PORT（本機 / 預設 8080）
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# 2 workers：單一 worker 卡住不會拖垮整個 app。Zeabur 2 vCPU / 8GB 方案；
# 每個 worker 各自持有一份 dlib / face_recognition 模型（人臉辨識 CPU heavy）。
# 需要時用 WEB_CONCURRENCY 覆寫。
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))

# sync worker：expense-report 無 websocket / 長連線需求（webapp 用 gevent 是為了 socketio，
# 這裡不需要，故意不照抄）。
worker_class = "sync"

# 人臉辨識 / OCR 單張請求可能數秒到數十秒（dlib 編碼 + Gemini API）；timeout 給 120s
# 避免砍掉合法的慢請求（webapp 用 60s 因走非同步 gevent，情境不同）。仍能砍掉真卡死的 worker。
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
keepalive = 2

# log 導到 stdout / stderr（容器慣例，交給 Zeabur 收）
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
