from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    vlm_url: str = "http://localhost:11434/v1/chat/completions"
    vlm_model: str = "qwen2-vl:7b"
    vlm_api_key: str = ""
    vlm_timeout: int = 120
    vlm_concurrency: int = 3
    vlm_batch_size: int = 5
    host: str = "0.0.0.0"
    port: int = 8003
    max_file_size: int = 104_857_600  # 100MB

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
