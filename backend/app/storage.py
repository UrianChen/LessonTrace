"""对象存储（MinIO，S3 兼容）。不开放公开读，浏览器只拿短期有效的签名地址。

两个客户端：
- 内部客户端走容器网络（S3_ENDPOINT），用于上传下载。
- 公开客户端只用来生成签名地址，主机名是浏览器访问的入口（PUBLIC_BASE_URL），
  Nginx 把 /<bucket>/ 原样转发给 MinIO，Host 不变，签名才能通过。
"""
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import get_settings


def _client(endpoint: str):
    s = get_settings()
    return boto3.client(
        "s3", endpoint_url=endpoint, region_name="us-east-1",
        aws_access_key_id=s.minio_root_user, aws_secret_access_key=s.minio_root_password,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@lru_cache
def internal():
    return _client(get_settings().s3_endpoint)


@lru_cache
def public():
    return _client(get_settings().public_base_url)


def bucket() -> str:
    return get_settings().s3_bucket


def ensure_bucket():
    try:
        internal().head_bucket(Bucket=bucket())
    except ClientError:
        internal().create_bucket(Bucket=bucket())


def presign_put(key: str, expires: int = 6 * 3600) -> str:
    return public().generate_presigned_url("put_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=expires)


def presign_get(key: str, expires: int | None = None, filename: str | None = None) -> str:
    params = {"Bucket": bucket(), "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return public().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires or get_settings().signed_url_ttl)


def presign_get_internal(key: str, expires: int = 6 * 3600) -> str:
    """给容器网络内的服务（语音转写）用的地址。"""
    return internal().generate_presigned_url("get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=expires)


def size_of(key: str) -> int | None:
    try:
        return internal().head_object(Bucket=bucket(), Key=key)["ContentLength"]
    except ClientError:
        return None


def download(key: str, path: str):
    internal().download_file(bucket(), key, path)


def upload(path: str, key: str, content_type: str | None = None):
    extra = {"ContentType": content_type} if content_type else None
    internal().upload_file(path, bucket(), key, ExtraArgs=extra)


def put_bytes(key: str, data: bytes, content_type: str):
    internal().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)


def get_bytes(key: str) -> bytes:
    return internal().get_object(Bucket=bucket(), Key=key)["Body"].read()


def delete_prefix(prefix: str):
    """删除某前缀下的全部对象（删除课程时级联清掉文件）。"""
    paginator = internal().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket(), Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            internal().delete_objects(Bucket=bucket(), Delete={"Objects": keys})


def lesson_prefix(lesson_id: int) -> str:
    return f"lessons/{lesson_id}/"
