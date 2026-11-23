from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

MAX_VIDEO_BYTES = 4 * 1024**3          # 4 GB
MAX_DURATION_MS = 2 * 60 * 60 * 1000   # 2 小时


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "lessontrace"
    postgres_password: str = "lessontrace"
    postgres_db: str = "lessontrace"
    postgres_host: str = "postgres"
    database_url: str = ""               # 测试时可直接指定

    redis_url: str = "redis://redis:6379/0"

    s3_endpoint: str = "http://minio:9000"       # 容器网络内访问
    public_base_url: str = "http://localhost"    # 浏览器访问入口，签名地址用它
    s3_bucket: str = "lessontrace"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    signed_url_ttl: int = 3 * 3600               # 播放地址有效期（秒）

    jwt_secret: str = "change-me"
    jwt_ttl_hours: int = 12

    asr_url: str = "http://asr:9000"

    llm_provider: str = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_refusal_fallback: bool = True
    anthropic_api_key: str = ""

    dimensions_file: str = str(BASE_DIR / "config" / "dimensions.yaml")

    # 每个阶段的时间上限（秒），超时按失败处理
    timeout_transcribing: int = 3 * 3600
    timeout_segmenting: int = 20 * 60
    timeout_analyzing: int = 30 * 60

    init_teacher_password: str = ""
    init_center_password: str = ""
    init_admin_password: str = ""

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:5432/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_dimensions() -> list[dict]:
    """分析维度定义，写在配置文件里。"""
    with open(get_settings().dimensions_file, encoding="utf-8") as f:
        return yaml.safe_load(f)["dimensions"]
