import logging
from flask import current_app

logger = logging.getLogger(__name__)


class MockStorage:
    """記憶體儲存，供測試/無憑證本機開發。"""
    def __init__(self):
        self.objects = {}

    def put(self, key, data, content_type):
        self.objects[key] = {"data": data, "content_type": content_type}

    def presigned_url(self, key, expires=300):
        return f"/mock-storage/{key}"

    def delete(self, key):
        self.objects.pop(key, None)

    def get(self, key):
        obj = self.objects.get(key)
        return obj["data"] if obj else None


class R2Storage:
    def __init__(self, cfg):
        import boto3
        self.bucket = cfg["R2_BUCKET"]
        self.expire = cfg.get("R2_URL_EXPIRE_SECONDS", 300)
        self._client = boto3.client(
            "s3",
            endpoint_url=cfg["R2_ENDPOINT"],
            aws_access_key_id=cfg["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )

    def put(self, key, data, content_type):
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data,
            ContentType=content_type, ServerSideEncryption="AES256",
        )

    def presigned_url(self, key, expires=None):
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires or self.expire,
        )

    def delete(self, key):
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def get(self, key):
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()


_mock_singleton = None


def get_storage():
    backend = current_app.config.get("STORAGE_BACKEND", "mock")
    if backend == "r2":
        return R2Storage(current_app.config)
    global _mock_singleton
    if _mock_singleton is None:
        _mock_singleton = MockStorage()
    return _mock_singleton
